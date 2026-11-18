"""检修排产方案的生命周期：创建计算、重算、确认锁定、撤销释放、执行与可恢复重试。"""
from fastapi import HTTPException
from sqlalchemy import select
from redis import Redis
from ..config.settings import REDIS_URL
from ..models.plan import Plan
from ..models.plan_lock import PlanLock
from ..models.station import Station
from ..utils.serialization import row,now
from .runs import get_run
from .audit import log
from . import planning_catalog as catalog
from .planning import optimize
queue=Redis.from_url(REDIS_URL)
PLAN_QUEUE='planning:queue'
OPEN_STATES=('computing','ready')
LOCKED_STATES=('confirmed','executed')

def get_plan(db,id):
    p=db.get(Plan,id)
    if not p:raise HTTPException(404,'未找到排产方案')
    return p

def plan_view(db,p):
    data=row(p)
    data['stale']=is_stale(db,p)
    if p.result and p.result.get('stats'):
        st=p.result['stats']
        data['summary']={k:st[k] for k in ('expected_total_loss','used_minutes',
                                           'remaining_minutes','action_counts','sample_count')}
    return data

def is_stale(db,p):
    """计算期间口径（工位占用/总工时、动作工时、损失表）变化即过期；已锁定方案不判过期。"""
    if p.state not in OPEN_STATES:return False
    if not p.fingerprint:return False
    return catalog.current_fingerprint(db)!=p.fingerprint

def list_plans(db):
    return [plan_view(db,p) for p in db.scalars(select(Plan).order_by(Plan.id.desc()))]

def _posterior_rows(run):
    result=run.result
    if not result or not result.get('rows'):raise HTTPException(409,'该研究尚无完整结果，无法排产')
    labels=set(result.get('labels') or [])
    rows=[]
    for r in result['rows']:
        posteriors=r.get('posteriors')
        if not isinstance(posteriors,dict) or not posteriors:
            raise HTTPException(409,'该研究缺少完整折外后验向量，请使用新版算法重新执行研究')
        if labels and set(posteriors)!=labels:
            raise HTTPException(422,'折外后验类别与研究标签不一致：'+r.get('reference',''))
        rows.append({'reference':r['reference'],'posteriors':posteriors})
    return rows,result

def create_plan(db,user,data):
    run=get_run(db,data.run_id)
    if run.state!='completed':raise HTTPException(409,'只可为已完成的研究创建排产方案')
    _posterior_rows(run)  # 提前校验完整后验，失败直接409/422，不入队
    catalog.ensure_catalog(db)
    snapshot,fingerprint=catalog.catalog_snapshot(db)
    p=Plan(run_id=run.id,name=data.name,state='computing',created_by=user.email,
           created_at=now(),updated_at=now(),input_snapshot=snapshot,fingerprint=fingerprint)
    db.add(p);db.flush();log(db,user,'plan.queued',p.id,data.name);db.commit()
    try:queue.rpush(PLAN_QUEUE,p.id)
    except Exception:
        p.state='failed';p.error='队列暂不可用，请重新发起计算';db.commit()
        raise HTTPException(503,p.error)
    return plan_view(db,p)

def recompute(db,user,id):
    p=get_plan(db,id)
    if p.state not in OPEN_STATES:raise HTTPException(409,'只有计算中或待确认的方案可以重新计算')
    # 计算中断恢复：computing 状态直接重入队，不产生任何工时扣减（工时只在确认时锁定）
    p.state='computing';p.error='';p.updated_at=now()
    snapshot,fingerprint=catalog.catalog_snapshot(db)
    p.input_snapshot=snapshot;p.fingerprint=fingerprint
    log(db,user,'plan.requeued',p.id);db.commit()
    try:queue.rpush(PLAN_QUEUE,p.id)
    except Exception:
        raise HTTPException(503,'队列暂不可用，请稍后重试')
    return plan_view(db,p)

def compute_plan(id):
    """worker 调用：纯计算，不触碰工位锁定工时；崩溃后重入队可安全重算。"""
    from ..config.database import Session
    with Session() as db:
        p=db.get(Plan,id)
        if not p or p.state!='computing':return
        try:
            run=get_run(db,p.run_id)
            rows,result=_posterior_rows(run)
            snapshot=p.input_snapshot
            loss_map=catalog.build_loss_map(snapshot)
            action_meta=catalog.build_action_meta(snapshot)
            caps=_capacities(db,snapshot,p.id)
            selections,stats=optimize(rows,loss_map,action_meta,caps['A'],caps['B'])
            p.result={'run_id':run.id,'run_checksum':result.get('checksum'),
                      'posterior_note':result.get('explanation'),
                      'capacity_snapshot':caps,'selections':selections,'stats':stats,
                      'loss_table':snapshot['loss_table']}
            p.state='ready';p.error='';p.updated_at=now()
            log(db,'worker','plan.computed',p.id,str(stats['expected_total_loss']))
        except Exception as e:
            p.state='failed';p.error=str(e)[:2000];p.updated_at=now()
            log(db,'worker','plan.failed',p.id,p.error)
        db.commit()

def _capacities(db,snapshot,exclude_plan_id=None):
    """两类工位当前可用工时 = 总工时 − 人工占用 − 其他方案已锁定（未释放）工时。
    并发方案不超订：计算阶段即扣减已锁定容量，而非等到确认时才拒绝。"""
    caps={}
    for s in snapshot['stations']:
        locked=catalog.locked_minutes(db,s['id'],exclude_plan_id=exclude_plan_id)
        remaining=int(s['capacity_minutes'])-int(s['manual_minutes'])-locked
        if remaining<0:
            raise ValueError('工位 %s 已锁定工时超过可用容量，请先撤销相关方案后重算'%s['code'])
        caps[s['code']]=remaining
    if 'A' not in caps or 'B' not in caps:raise ValueError('排产目录必须包含 A、B 两类工位')
    return caps

def confirm_plan(db,user,id):
    p=get_plan(db,id)
    if p.state in LOCKED_STATES:
        raise HTTPException(409,'方案已确认锁定，请勿重复提交')
    if p.state=='cancelled':raise HTTPException(409,'方案已撤销，不能确认')
    if p.state=='failed':raise HTTPException(409,'方案计算失败，请修正后重新计算')
    if p.state=='computing':raise HTTPException(409,'方案仍在计算中，完成后才能确认')
    if is_stale(db,p):
        raise HTTPException(409,'方案已过期：计算期间工位占用或损失口径发生变化，请重新计算后再确认')
    if not p.result:raise HTTPException(409,'方案缺少选择结果，不能确认')
    # 行级锁串行化并发确认，保证不超订；SELECT ... FOR UPDATE
    stations={s.code:s for s in db.scalars(select(Station).order_by(Station.id)).all()}
    locked={code:db.query(Station).filter(Station.id==s.id).with_for_update().one()
            for code,s in sorted(stations.items())}
    used=p.result['stats']['used_minutes']
    for code in ('A','B'):
        s=locked[code]
        remaining=s.capacity_minutes-s.manual_minutes-catalog.locked_minutes(db,s.id)
        if used[code]>remaining:
            db.rollback()
            raise HTTPException(409,f'{s.name}剩余工时不足（需{used[code]}分钟，余{remaining}分钟），并发方案已占满，请重算')
    # 幂等创建锁定行：唯一约束 (plan_id, station_id)，重试不重复扣工时
    for code in ('A','B'):
        minutes=used[code]
        if minutes<=0:continue
        s=stations[code]
        exists=db.scalar(select(PlanLock.id).where(PlanLock.plan_id==p.id,PlanLock.station_id==s.id))
        if not exists:
            db.add(PlanLock(plan_id=p.id,station_id=s.id,locked_minutes=minutes,created_at=now()))
    p.state='confirmed';p.confirmed_by=user.email;p.confirmed_at=now();p.updated_at=now()
    log(db,user,'plan.confirmed',p.id,f"A {used['A']}分钟 / B {used['B']}分钟")
    db.commit()
    return plan_view(db,p)

def cancel_plan(db,user,id):
    p=get_plan(db,id)
    if p.state in ('cancelled',):
        return plan_view(db,p)  # 撤销幂等
    if p.state=='executed':raise HTTPException(409,'方案已执行，不能撤销')
    if p.state=='computing':raise HTTPException(409,'方案仍在计算中，请等待计算结束后再撤销')
    ts=now()
    for lk in db.scalars(select(PlanLock).where(PlanLock.plan_id==p.id,PlanLock.released_at=='')):
        lk.released_at=ts  # 释放工时
    p.state='cancelled';p.cancelled_by=user.email;p.cancelled_at=ts;p.updated_at=ts
    log(db,user,'plan.cancelled',p.id);db.commit()
    return plan_view(db,p)

def execute_plan(db,user,id):
    p=get_plan(db,id)
    if p.state=='executed':return plan_view(db,p)  # 执行幂等，重试不重复扣工时
    if p.state!='confirmed':raise HTTPException(409,'只有整批选择与工时锁定齐备（已确认）的方案才能执行')
    p.state='executed';p.executed_by=user.email;p.executed_at=now();p.updated_at=now()
    log(db,user,'plan.executed',p.id);db.commit()
    return plan_view(db,p)

def recover_orphans(db):
    """worker 启动恢复：计算中任务重新入队；锁定/释放状态不受影响。"""
    ids=[p.id for p in db.scalars(select(Plan).where(Plan.state=='computing'))]
    for id in ids:
        try:queue.rpush(PLAN_QUEUE,id)
        except Exception:pass
    return ids
