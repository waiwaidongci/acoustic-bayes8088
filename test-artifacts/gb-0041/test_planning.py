"""本地全流程测试：SQLite + 队列替身，不依赖 MySQL/Redis/Docker。
运行：PYTHONPATH=/tmp/pylibs:/workspace/backend:/workspace/test-artifacts/gb-0041/harness \
     DATABASE_URL=sqlite:////tmp/planning_test.db REDIS_URL=fake:// python3 -I test_...（见 TESTING.md）
"""
import os,sys,itertools,math
sys.path.insert(0,'/tmp/pylibs')
sys.path.insert(0,'/workspace/backend')
sys.path.insert(0,'/workspace/test-artifacts/gb-0041/harness')
import fakeredis
# 在导入应用模块前替换 redis.Redis
import redis as _redis
_redis.Redis=fakeredis.FakeRedis
from sqlalchemy import select
from src.config.database import Base,engine,Session
from src.models.user import User
from src.models.source import Source
from src.models.record import Record
from src.models.run import Run
from src.models.plan import Plan
from src.models.plan_lock import PlanLock
from src.models.station import Station
from src.utils.security import hash_password
from src.utils.serialization import now
from src.services.algorithm import calculate
from src.services import planning_catalog as catalog
from src.services.planning import optimize
from src.services import plans as plan_service
from src.services.runs import queue

Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
LABELS=['正常','轴承磨损','转子偏心']
rng_seed=123
import random
rng=random.Random(rng_seed)

def make_records(n=60):
    recs=[]
    for i in range(n):
        cls=i%3
        recs.append({'id':i+1,'source_id':1,'reference':f'TX-T-{i+1:04}',
                     'values':{'rms':round(max(.1,rng.gauss([1.2,3.0,2.0][cls],.35)),3),
                               'centroid':round(max(100,rng.gauss([900,1600,2300][cls],170)),2),
                               'kurtosis':round(max(.1,rng.gauss([2.8,5.2,3.9][cls],.45)),3),
                               'label':LABELS[cls]}})
    return recs

# ---------- 1. 算法输出完整后验 ----------
recs=make_records()
result=calculate(recs,{'folds':3,'smoothing':1e-9})
assert 'posteriors' in result['rows'][0], '缺少完整后验向量'
for r in result['rows']:
    assert set(r['posteriors'])==set(LABELS)
    assert abs(sum(r['posteriors'].values())-1)<1e-9
print('1. 完整折外后验 OK，行数',len(result['rows']))

# ---------- 2. DP 与暴力枚举 oracle 一致（小样本穷举） ----------
with Session() as db:
    catalog.ensure_catalog(db);db.commit()
    snapshot,_=catalog.catalog_snapshot(db)
loss_map=catalog.build_loss_map(snapshot)
meta=catalog.build_action_meta(snapshot)
small_rows=[{'reference':r['reference'],'posteriors':r['posteriors']} for r in result['rows'][:8]]
cap_a,cap_b=60,90  # A: 3 quick slots, B: 2 deep slots
sel,stats=optimize(small_rows,loss_map,meta,cap_a,cap_b)
# 暴力枚举 3^n
best=None;best_combo=None;best_combo_occ=None
for combo in itertools.product(('none','quick','deep'),repeat=len(small_rows)):
    ua=sum(20 for a in combo if a=='quick');ub=sum(45 for a in combo if a=='deep')
    if ua>cap_a or ub>cap_b:continue
    loss=0
    for row,action in zip(small_rows,combo):
        loss+=sum(p*loss_map[(lab,action)] for lab,p in row['posteriors'].items())
    if best is None or loss<best-1e-9 or (abs(loss-best)<=1e-9 and (ua+ub)<sum(best_combo_occ)):
        best=loss;best_combo=combo;best_combo_occ=(ua,ub)
dp_actions=tuple(s['action'] for s in sel)
assert abs(stats['expected_total_loss']-best)<1e-6,(stats['expected_total_loss'],best,dp_actions,best_combo)
print('2. DP 最优性与暴力 oracle 一致 OK，损失',round(best,4),'组合',dp_actions)

# ---------- 3. 容量约束严格、不超订 ----------
assert stats['used_minutes']['A']<=cap_a and stats['used_minutes']['B']<=cap_b
assert stats['remaining_minutes']=={'A':cap_a-stats['used_minutes']['A'],'B':cap_b-stats['used_minutes']['B']}
# 零容量：全部只能免检
sel0,stats0=optimize(small_rows,loss_map,meta,0,0)
assert all(s['action']=='none' for s in sel0)
print('3. 容量约束 OK；零容量全部免检')

# ---------- 4. 端到端：建用户/来源/任务/方案，worker 计算 ----------
with Session() as db:
    u=User(email='analyst@acoustic-bayes.demo',password_hash=hash_password('x'),role='analyst')
    admin=User(email='admin@acoustic-bayes.demo',password_hash=hash_password('x'),role='admin')
    db.add_all([u,admin]);db.flush()
    s=Source(key='TX-T-01',name='测试来源',filename='t.csv',description='d');db.add(s);db.flush()
    for r in recs:db.add(Record(source_id=s.id,reference=r['reference'],values=r['values']))
    run=Run(source_id=s.id,name='测试研究',state='completed',parameters={'folds':3,'smoothing':1e-9},
            snapshot={'source':{'id':s.id,'name':s.name,'filename':'t.csv'},'records':recs},
            result=result,created_at=now())
    db.add(run);db.commit();run_id=run.id;uid=u.id;aid=admin.id

class Data:
    def __init__(self,**k):self.__dict__.update(k)
with Session() as db:
    user=db.get(User,uid)
    p=plan_service.create_plan(db,user,Data(run_id=run_id,name='排产方案一'))
    pid=p['id'];assert p['state']=='computing'
# worker 消费
item=queue.blpop('planning:queue',timeout=2)
assert item and int(item[1])==pid
plan_service.compute_plan(pid)
with Session() as db:
    p=db.get(Plan,pid);assert p.state=='ready',p.error
    st=p.result['stats']
    print('4. worker 计算完成 OK：',st['action_counts'],'总损失',st['expected_total_loss'],
          '占用',st['used_minutes'],'剩余',st['remaining_minutes'])
    # 后验可追查
    assert p.result['selections'][0]['posteriors']
    assert p.result['run_checksum']==result['checksum']
    # 初始目录剩余：A 480-120=360（18 slots），B 480-60=420（9 slots）
    assert st['used_minutes']['A']<=360 and st['used_minutes']['B']<=420

# ---------- 5. 确认锁定、并发不超订、重试幂等 ----------
with Session() as db:
    user=db.get(User,uid)
    view=plan_service.confirm_plan(db,user,pid)
    assert view['state']=='confirmed'
    locks=db.scalars(select(PlanLock).where(PlanLock.plan_id==pid)).all()
    n_locks=len(locks)
    # 重复确认 409
    try:plan_service.confirm_plan(db,user,pid);raise AssertionError('应拒绝重复确认')
    except Exception as e:assert getattr(e,'status_code',None)==409
    # 重试不重复扣工时
    again=db.scalars(select(PlanLock).where(PlanLock.plan_id==pid)).all()
    assert len(again)==n_locks
    # 工位视图反映锁定
    cat=plan_service.catalog.list_stations(db)
    for sd in cat['stations']:
        assert sd['remaining_minutes']==sd['capacity_minutes']-sd['manual_minutes']-sd['locked_minutes']
    print('5. 确认锁定与幂等 OK，锁定行数',n_locks)

# ---------- 6. 计算期口径变化过期拒绝；已锁定容量在计算阶段即扣减 ----------
with Session() as db:
    user=db.get(User,uid)
    p2=plan_service.create_plan(db,user,Data(run_id=run_id,name='排产方案二'));pid2=p2['id']
item=queue.blpop('planning:queue',timeout=2);plan_service.compute_plan(pid2)
with Session() as db:
    # 6a 计算期间人工占用变化 -> 方案过期，确认被拒绝（仅微调 A，保持净容量非负）
    sta=db.scalar(select(Station).where(Station.code=='A'))
    old_manual=sta.manual_minutes
    # A 总480、方案一锁定360，人工占用最多120；从120下调到100，口径变化且仍可行
    sta.manual_minutes=100;sta.updated_at=now();db.commit()
    assert plan_service.is_stale(db,db.get(Plan,pid2))
    try:
        plan_service.confirm_plan(db,db.get(User,uid),pid2);raise AssertionError('过期方案应拒绝确认')
    except Exception as e:assert getattr(e,'status_code',None)==409
    # 6b 方案一仍锁定且口径已变；重算后指纹刷新，计算容量自动扣除方案一锁定（剩余为0）
    plan_service.recompute(db,db.get(User,uid),pid2)
item=queue.blpop('planning:queue',timeout=2);plan_service.compute_plan(pid2)
with Session() as db:
    p2obj=db.get(Plan,pid2)
    assert not plan_service.is_stale(db,p2obj)
    caps=p2obj.result['capacity_snapshot'];used=p2obj.result['stats']['used_minutes']
    # 计算容量已扣除方案一锁定：A 净20（至多1件快检），B 净15（装不下任何检修动作）
    assert caps=={'A':20,'B':15},caps
    assert used['A']<=caps['A'] and used['B']<=caps['B']
    assert used['B']==0 and used['A']<=20
    assert all(x['action']!='deep' for x in p2obj.result['selections'])
    view=plan_service.confirm_plan(db,db.get(User,uid),pid2)
    assert view['state']=='confirmed'
    # 确认后 A 总锁定 = 方案一360 + 方案二占用，绝不超过总工时480-人工100=380
    assert catalog.locked_minutes(db,sta.id)==360+used['A']<=380
    print('6. 过期拒绝、计算阶段扣减已锁定容量、并发不超订 OK')
    # 还原占用
    sta.manual_minutes=old_manual;sta.updated_at=now();db.commit()

# ---------- 7. 撤销释放、重算不扣工时 ----------
with Session() as db:
    before={s.code:catalog.locked_minutes(db,s.id) for s in db.scalars(select(Station))}
    plan_service.cancel_plan(db,db.get(User,uid),pid2)  # 未确认方案撤销
    plan_service.cancel_plan(db,db.get(User,uid),pid)   # 已确认方案撤销 -> 释放
    after={s.code:catalog.locked_minutes(db,s.id) for s in db.scalars(select(Station))}
    assert all(after[k]==0 for k in after),after
    released=db.scalars(select(PlanLock).where(PlanLock.plan_id==pid)).all()
    assert all(x.released_at for x in released)
    # 撤销幂等
    plan_service.cancel_plan(db,db.get(User,uid),pid)
    print('7. 撤销释放 OK：',before,'->',after)

# ---------- 8. 执行门禁与幂等 ----------
with Session() as db:
    p3=plan_service.create_plan(db,db.get(User,uid),Data(run_id=run_id,name='排产方案三'));pid3=p3['id']
item=queue.blpop('planning:queue',timeout=2);plan_service.compute_plan(pid3)
with Session() as db:
    try:
        plan_service.execute_plan(db,db.get(User,uid),pid3);raise AssertionError('未确认不能执行')
    except Exception as e:assert getattr(e,'status_code',None)==409
    plan_service.confirm_plan(db,db.get(User,uid),pid3)
    v1=plan_service.execute_plan(db,db.get(User,uid),pid3)
    v2=plan_service.execute_plan(db,db.get(User,uid),pid3)
    assert v1['state']==v2['state']=='executed'
    locks=db.scalars(select(PlanLock).where(PlanLock.plan_id==pid3,PlanLock.released_at=='')).all()
    assert len(locks)>=1
    try:
        plan_service.cancel_plan(db,db.get(User,uid),pid3);raise AssertionError('已执行不能撤销')
    except Exception as e:assert getattr(e,'status_code',None)==409
    print('8. 执行门禁与幂等 OK')

# ---------- 9. 中断恢复：computing 孤儿重入队，无重复锁定 ----------
with Session() as db:
    p4=plan_service.create_plan(db,db.get(User,uid),Data(run_id=run_id,name='排产方案四'));pid4=p4['id']
with Session() as db:
    ids=plan_service.recover_orphans(db)
    assert pid4 in ids
item=queue.blpop('planning:queue',timeout=2)
assert item and int(item[1])==pid4
plan_service.compute_plan(pid4)
with Session() as db:
    assert db.get(Plan,pid4).state=='ready'
    assert db.scalar(select(PlanLock).where(PlanLock.plan_id==pid4)) is None
    print('9. 中断恢复 OK，重算未产生任何工时锁定')

print('\n全部后端测试通过 ✔')
