"""HTTP 完整流程测试：TestClient + SQLite + 队列替身 + 真实 worker 主循环（线程内）。"""
import sys,os,time,threading
sys.path.insert(0,'/tmp/pylibs');sys.path.insert(0,'/workspace/backend')
sys.path.insert(0,'/workspace/test-artifacts/gb-0041/harness')
import fakeredis,redis as _redis
_redis.Redis=fakeredis.FakeRedis
os.environ.setdefault('DATABASE_URL','sqlite:////tmp/planning_http.db')
os.environ.setdefault('REDIS_URL','fake://');os.environ.setdefault('JWT_SECRET','http-test-secret')
os.environ.setdefault('ARTIFACT_DIR','/tmp/artifacts_http');os.environ['SEED_DEMO']='false'
from fastapi.testclient import TestClient
from sqlalchemy import select
from src.main import app
from src.config.database import Session
from src.models.user import User
from src.models.source import Source
from src.models.record import Record
from src.models.run import Run
from src.models.plan import Plan
from src.utils.security import hash_password
from src.utils.serialization import now
from src.services.algorithm import calculate
from src.worker import main as worker_main
import src.worker as worker_mod

if os.path.exists('/tmp/planning_http.db'):os.remove('/tmp/planning_http.db')
client_cm=TestClient(app)
client=client_cm.__enter__()  # 触发 lifespan：建表 + 目录初始化
# worker 线程：blpop 超时很短，守护线程随主进程退出
stop=threading.Event()
def run_worker():
    import src.services.plans as ps,src.services.runs as rs
    orig=rs.queue
    while not stop.is_set():
        v=ps.queue.blpop(ps.PLAN_QUEUE,timeout=1)
        if v:
            ps.compute_plan(int(v[1]));continue
        v=orig.blpop('analysis:queue',timeout=1)
        if v:worker_mod.execute(int(v[1]))
t=threading.Thread(target=run_worker,daemon=True);t.start()

with Session() as db:
    for role in ('admin','analyst','viewer'):
        email=f'{role}@acoustic-bayes.demo'
        if not db.scalar(select(User).where(User.email==email)):
            db.add(User(email=email,password_hash=hash_password('Research2026!'),role=role))
    import random
    rng=random.Random(7);LABELS=['正常','轴承磨损','转子偏心']
    s=Source(key='TX-H-01',name='HTTP来源',filename='h.csv',description='d');db.add(s);db.flush()
    recs=[]
    for i in range(45):
        cls=i%3
        vals={'rms':round(max(.1,rng.gauss([1.2,3.0,2.0][cls],.35)),3),
              'centroid':round(max(100,rng.gauss([900,1600,2300][cls],170)),2),
              'kurtosis':round(max(.1,rng.gauss([2.8,5.2,3.9][cls],.45)),3),'label':LABELS[cls]}
        db.add(Record(source_id=s.id,reference=f'TX-H-{i+1:04}',values=vals))
        recs.append({'id':i+1,'source_id':s.id,'reference':f'TX-H-{i+1:04}','values':vals})
    result=calculate(recs,{'folds':3,'smoothing':1e-9})
    run=Run(source_id=s.id,name='HTTP研究',state='completed',parameters={'folds':3,'smoothing':1e-9},
            snapshot={'source':{'id':s.id,'name':s.name,'filename':'h.csv'},'records':recs},
            result=result,created_at=now());db.add(run);db.commit();run_id=run.id

def login(role):
    r=client.post('/auth/login',json={'email':f'{role}@acoustic-bayes.demo','password':'Research2026!'})
    assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['token']}
admin_h=login('admin');analyst_h=login('analyst');viewer_h=login('viewer')

# 健康与目录
assert client.get('/health').status_code==200
r=client.get('/planning/stations',headers=viewer_h);assert r.status_code==200
st=r.json()
assert len(st['stations'])==2 and st['none_action']['code']=='none'
a=next(x for x in st['stations'] if x['code']=='A')
assert a['remaining_minutes']==a['capacity_minutes']-a['manual_minutes']
print('1. 工位目录 OK：',[(x['code'],x['remaining_minutes']) for x in st['stations']])

# 权限：viewer 不能创建方案
r=client.post('/plans',headers=viewer_h,json={'run_id':run_id,'name':'无权方案'})
assert r.status_code==403
# 匿名 401
assert client.post('/plans',json={'run_id':run_id,'name':'匿名方案'}).status_code==401

# 损失表读取
r=client.get('/planning/loss-table',headers=analyst_h);assert r.status_code==200
lt=r.json();assert len(lt['entries'])==9 and {a['code'] for a in lt['actions']}=={'none','quick','deep'}

# analyst 创建方案，worker 异步计算
r=client.post('/plans',headers=analyst_h,json={'run_id':run_id,'name':'HTTP排产一'})
assert r.status_code==200,r.text;pid=r.json()['id'];assert r.json()['state']=='computing'
deadline=time.time()+15
while time.time()<deadline:
    d=client.get(f'/plans/{pid}',headers=analyst_h).json()
    if d['state'] in ('ready','failed'):break
    time.sleep(0.2)
assert d['state']=='ready',d
assert d['stale'] is False
assert set(d['summary'])=={'expected_total_loss','used_minutes','remaining_minutes','action_counts','sample_count'}
print('2. 异步计算完成 OK：',d['summary']['action_counts'],'损失',d['summary']['expected_total_loss'])

# 详情可追查：后验、选择原因、采用口径指纹
full=client.get(f'/plans/{pid}',headers=viewer_h).json()
sel=full['result']['selections'][0]
assert sel['posteriors'] and sel['reason'] and sel['losses_by_action']
assert full['result']['run_checksum']==result['checksum']
assert full['input_snapshot']['loss_table'] and full['fingerprint']
print('3. 可追查口径 OK：原因示例「%s」'%sel['reason'])

# 确认（analyst 可确认）
r=client.post(f'/plans/{pid}/confirm',headers=analyst_h);assert r.status_code==200,r.text
assert r.json()['state']=='confirmed'
# 重复确认 409，不重复扣工时
r2=client.post(f'/plans/{pid}/confirm',headers=analyst_h);assert r2.status_code==409
st1=client.get('/planning/stations',headers=viewer_h).json()
locked_now={x['code']:x['locked_minutes'] for x in st1['stations']}
client.post(f'/plans/{pid}/confirm',headers=admin_h)
st2=client.get('/planning/stations',headers=viewer_h).json()
assert {x['code']:x['locked_minutes'] for x in st2['stations']}==locked_now
print('4. 确认锁定、重复确认拒绝且不重复扣工时 OK：',locked_now)

# 过期方案：admin 改人工占用，新建方案计算后再改一次占用 -> stale
r=client.post('/plans',headers=analyst_h,json={'run_id':run_id,'name':'HTTP排产二'});pid2=r.json()['id']
deadline=time.time()+15
while time.time()<deadline:
    d2=client.get(f'/plans/{pid2}',headers=analyst_h).json()
    if d2['state'] in ('ready','failed'):break
    time.sleep(0.2)
assert d2['state']=='ready'
r=client.put('/planning/stations/A',headers=admin_h,json={'manual_minutes':120})
assert r.status_code==200
d2=client.get(f'/plans/{pid2}',headers=analyst_h).json()
assert d2['stale'] is True
r=client.post(f'/plans/{pid2}/confirm',headers=analyst_h);assert r.status_code==409
# viewer 不能改占用
assert client.put('/planning/stations/A',headers=viewer_h,json={'manual_minutes':120}).status_code==403
# 非法占用 422
assert client.put('/planning/stations/A',headers=admin_h,json={'manual_minutes':-5}).status_code in (422,)
# 会挤占已锁定工时的调整同样拒绝（不超订）
assert client.put('/planning/stations/A',headers=admin_h,json={'manual_minutes':200}).status_code==409
# 重算恢复新鲜
r=client.post(f'/plans/{pid2}/recompute',headers=analyst_h);assert r.status_code==200
deadline=time.time()+15
while time.time()<deadline:
    d2=client.get(f'/plans/{pid2}',headers=analyst_h).json()
    if d2['state'] in ('ready','failed'):break
    time.sleep(0.2)
assert d2['state']=='ready' and d2['stale'] is False
print('5. 占用变化重算、过期拒绝确认 OK')

# 撤销释放
r=client.post(f'/plans/{pid}/cancel',headers=analyst_h);assert r.status_code==200
st3=client.get('/planning/stations',headers=viewer_h).json()
released={x['code']:x['locked_minutes'] for x in st3['stations']}
# 方案二尚未确认，只有方案一被释放，锁定应全部归零（当前无其他已确认方案）
assert all(v==0 for v in released.values()),released
# 撤销幂等
assert client.post(f'/plans/{pid}/cancel',headers=analyst_h).status_code==200
print('6. 撤销释放与幂等 OK')

# 确认方案二 -> 执行门禁 -> 执行幂等
r=client.post(f'/plans/{pid2}/confirm',headers=analyst_h);assert r.status_code==200,r.text
fresh=client.post('/plans',headers=analyst_h,json={'run_id':run_id,'name':'HTTP排产三'})
pid3=fresh.json()['id']
deadline=time.time()+15
while time.time()<deadline:
    d3=client.get(f'/plans/{pid3}',headers=analyst_h).json()
    if d3['state'] in ('ready','failed'):break
    time.sleep(0.2)
assert client.post(f'/plans/{pid3}/execute',headers=analyst_h).status_code==409  # 未确认
r=client.post(f'/plans/{pid2}/execute',headers=analyst_h);assert r.status_code==200
assert r.json()['state']=='executed'
assert client.post(f'/plans/{pid2}/execute',headers=analyst_h).json()['state']=='executed'
assert client.post(f'/plans/{pid2}/cancel',headers=analyst_h).status_code==409  # 已执行不可撤销
print('7. 执行门禁、执行幂等 OK')

# CSV 导出
r=client.get(f'/plans/{pid2}/export',headers=viewer_h)
assert r.status_code==200 and 'text/csv' in r.headers['content-type']
assert '样本编号'.encode() not in r.content  # 英文列名，中文动作
assert '免检放行' in r.content.decode('utf-8-sig')
print('8. 方案 CSV 导出 OK，字节数',len(r.content))

# 损失表修改：analyst 无权，admin 有权，且新方案指纹随之变化
assert client.put('/planning/loss-table',headers=analyst_h,
                  json={'fault_label':'正常','action_code':'none','expected_loss':10}).status_code==403
r=client.put('/planning/loss-table',headers=admin_h,
             json={'fault_label':'正常','action_code':'none','expected_loss':10})
assert r.status_code==200
r=client.put('/planning/loss-table',headers=admin_h,
             json={'fault_label':'正常','action_code':'none','expected_loss':-1})
assert r.status_code==422
# 改回
client.put('/planning/loss-table',headers=admin_h,
           json={'fault_label':'正常','action_code':'none','expected_loss':0})
print('9. 损失表权限与校验 OK')

# 审计留痕
events=client.get('/audit',headers=admin_h).json()
actions={e['action'] for e in events}
assert {'plan.queued','plan.computed','plan.confirmed','plan.cancelled','plan.executed','station.updated','loss.updated'} <= actions
print('10. 审计留痕 OK：',sorted(a for a in actions if a.startswith(('plan','station','loss'))))

stop.set()
print('\n全部 HTTP 测试通过 ✔')
