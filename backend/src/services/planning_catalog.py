"""检修工位、处置动作与故障/处置损失表的目录管理。"""
import hashlib,json
from fastapi import HTTPException
from sqlalchemy import select
from ..models.station import Station
from ..models.repair_action import RepairAction
from ..models.loss_entry import LossEntry
from ..constants.enums import ACTION_NONE,ACTION_QUICK,ACTION_DEEP,ACTION_ORDER
from ..utils.serialization import now

# 演示口径：两类工位、三种处置、三类故障的损失表（单位：元）
DEFAULT_STATIONS=[
    {'code':'A','name':'快速复检工位','capacity_minutes':480,'manual_minutes':120},
    {'code':'B','name':'停机检修工位','capacity_minutes':480,'manual_minutes':60},
]
DEFAULT_ACTIONS=[
    {'code':ACTION_NONE,'name':'免检放行','station_code':None,'minutes_per_sample':0},
    {'code':ACTION_QUICK,'name':'快速复检','station_code':'A','minutes_per_sample':20},
    {'code':ACTION_DEEP,'name':'停机检修','station_code':'B','minutes_per_sample':45},
]
DEFAULT_LOSS=[
    # 故障标签, 动作, 期望损失（元）
    ('正常',ACTION_NONE,0),('正常',ACTION_QUICK,180),('正常',ACTION_DEEP,520),
    ('轴承磨损',ACTION_NONE,1500),('轴承磨损',ACTION_QUICK,420),('轴承磨损',ACTION_DEEP,650),
    ('转子偏心',ACTION_NONE,2200),('转子偏心',ACTION_QUICK,1100),('转子偏心',ACTION_DEEP,700),
]

def ensure_catalog(db):
    """幂等初始化排产目录；seed 与启动时均可调用，不覆盖人工修改。"""
    created=False
    stations={}
    for item in DEFAULT_STATIONS:
        s=db.scalar(select(Station).where(Station.code==item['code']))
        if not s:
            s=Station(**item,updated_at=now());db.add(s);db.flush();created=True
        stations[item['code']]=s
    for item in DEFAULT_ACTIONS:
        a=db.scalar(select(RepairAction).where(RepairAction.code==item['code']))
        if not a:
            station_id=stations[item['station_code']].id if item['station_code'] else None
            db.add(RepairAction(code=item['code'],name=item['name'],station_id=station_id,
                                minutes_per_sample=item['minutes_per_sample']))
            created=True
    for label,action,loss in DEFAULT_LOSS:
        exists=db.scalar(select(LossEntry.id).where(LossEntry.fault_label==label,LossEntry.action_code==action))
        if not exists:
            db.add(LossEntry(fault_label=label,action_code=action,expected_loss=loss));created=True
    return created

def list_stations(db):
    actions=db.scalars(select(RepairAction).order_by(RepairAction.id)).all()
    out=[]
    for s in db.scalars(select(Station).order_by(Station.id)):
        locked=locked_minutes(db,s.id)
        out.append({'id':s.id,'code':s.code,'name':s.name,'capacity_minutes':s.capacity_minutes,
                    'manual_minutes':s.manual_minutes,
                    'locked_minutes':locked,
                    'remaining_minutes':s.capacity_minutes-s.manual_minutes-locked,
                    'updated_at':s.updated_at,
                    'actions':[{'code':a.code,'name':a.name,'minutes_per_sample':a.minutes_per_sample}
                               for a in actions if a.station_id==s.id]})
    none_action=next((a for a in actions if a.station_id is None),None)
    return {'stations':out,'none_action':({'code':none_action.code,'name':none_action.name} if none_action else None)}

def locked_minutes(db,station_id,exclude_plan_id=None):
    """已确认（含已执行、未撤销）方案锁定的工时总和。"""
    from ..models.plan import Plan
    from ..models.plan_lock import PlanLock
    q=select(PlanLock.locked_minutes).join(Plan,Plan.id==PlanLock.plan_id).where(
        PlanLock.station_id==station_id,PlanLock.released_at=='')
    if exclude_plan_id is not None:q=q.where(Plan.id!=exclude_plan_id)
    return int(sum(db.scalars(q).all()))

def update_station(db,user,code,data):
    s=db.scalar(select(Station).where(Station.code==code))
    if not s:raise HTTPException(404,'未找到工位：'+code)
    manual=getattr(data,'manual_minutes',None);capacity=getattr(data,'capacity_minutes',None)
    if manual is not None:
        if not isinstance(manual,int) or manual<0:raise HTTPException(422,'人工占用工时必须为非负整数（分钟）')
        s.manual_minutes=manual
    if capacity is not None:
        if not isinstance(capacity,int) or capacity<=0:raise HTTPException(422,'工位总工时必须为正整数（分钟）')
        s.capacity_minutes=capacity
    if s.manual_minutes>s.capacity_minutes:
        raise HTTPException(422,'人工占用不能超过工位总工时')
    # 调整后不得挤占已锁定工时
    if s.manual_minutes+locked_minutes(db,s.id)>s.capacity_minutes:
        raise HTTPException(409,'调整后剩余工时小于已锁定工时，请先撤销相关方案')
    s.updated_at=now()
    from .audit import log
    log(db,user,'station.updated',s.code,f'人工占用{s.manual_minutes}分钟 / 总{s.capacity_minutes}分钟')
    db.commit()
    return list_stations(db)

def loss_table(db):
    rows=db.scalars(select(LossEntry).order_by(LossEntry.fault_label,LossEntry.action_code)).all()
    actions=db.scalars(select(RepairAction).order_by(RepairAction.id)).all()
    labels=sorted({r.fault_label for r in rows})
    return {'fault_labels':labels,
            'actions':[{'code':a.code,'name':a.name,'station_id':a.station_id,
                        'minutes_per_sample':a.minutes_per_sample} for a in actions],
            'entries':[{'fault_label':r.fault_label,'action_code':r.action_code,
                        'expected_loss':r.expected_loss} for r in rows]}

def update_loss(db,user,data):
    if data.action_code not in ACTION_ORDER:raise HTTPException(422,'不支持的处置动作：'+str(data.action_code))
    if not isinstance(data.expected_loss,(int,float)) or data.expected_loss<0:
        raise HTTPException(422,'期望损失必须为非负数值')
    entry=db.scalar(select(LossEntry).where(LossEntry.fault_label==data.fault_label,
                                            LossEntry.action_code==data.action_code))
    if not entry:raise HTTPException(404,'损失表中没有该故障/处置组合')
    entry.expected_loss=float(data.expected_loss)
    from .audit import log
    log(db,user,'loss.updated',data.fault_label,f'{data.action_code}={entry.expected_loss}')
    db.commit()
    return loss_table(db)

def catalog_snapshot(db):
    """供方案计算时冻结的口径快照与指纹。"""
    stations=db.scalars(select(Station).order_by(Station.id)).all()
    actions=db.scalars(select(RepairAction).order_by(RepairAction.id)).all()
    losses=db.scalars(select(LossEntry).order_by(LossEntry.id)).all()
    snap={'stations':[{'id':s.id,'code':s.code,'name':s.name,'capacity_minutes':s.capacity_minutes,
                       'manual_minutes':s.manual_minutes,'updated_at':s.updated_at} for s in stations],
          'actions':[{'code':a.code,'name':a.name,'station_id':a.station_id,
                      'minutes_per_sample':a.minutes_per_sample} for a in actions],
          'loss_table':[{'fault_label':x.fault_label,'action_code':x.action_code,
                         'expected_loss':x.expected_loss} for x in losses]}
    fingerprint=hashlib.sha256(json.dumps(snap,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return snap,fingerprint

def current_fingerprint(db):
    return catalog_snapshot(db)[1]

def build_loss_map(snapshot):
    return {(e['fault_label'],e['action_code']):float(e['expected_loss']) for e in snapshot['loss_table']}

def build_action_meta(snapshot):
    station_code={s['id']:s['code'] for s in snapshot['stations']}
    meta={}
    for a in snapshot['actions']:
        if a['station_id'] is None:meta[a['code']]=(None,int(a['minutes_per_sample']))
        else:meta[a['code']]=(station_code[a['station_id']],int(a['minutes_per_sample']))
    for code in ACTION_ORDER:
        if code not in meta:raise HTTPException(500,'排产目录缺少处置动作：'+code)
    return meta
