"""浏览器测试用后端启动器：真实 uvicorn + 真实 worker 循环 + SQLite + 队列替身。"""
import sys,os,time,threading,random
sys.path.insert(0,'/tmp/pylibs');sys.path.insert(0,'/workspace/backend')
sys.path.insert(0,'/workspace/test-artifacts/gb-0041/harness')
import fakeredis,redis as _redis
_redis.Redis=fakeredis.FakeRedis
os.environ['DATABASE_URL']='sqlite:////tmp/planning_browser_'+os.environ.get('TEST_RUN_ID','default')+'.db'
os.environ['REDIS_URL']='fake://';os.environ['JWT_SECRET']='browser-test-secret'
os.environ['ARTIFACT_DIR']='/tmp/artifacts_browser';os.environ['SEED_DEMO']='false'
db_path='/tmp/planning_browser_'+os.environ.get('TEST_RUN_ID','default')+'.db'
if os.path.exists(db_path):os.remove(db_path)
import uvicorn
from sqlalchemy import select
from src.config.database import Base,engine,Session
from src.models.user import User
from src.models.source import Source
from src.models.record import Record
from src.models.run import Run
from src.utils.security import hash_password
from src.utils.serialization import now
from src.services.algorithm import calculate
from src.services import plans as ps
from src.services.runs import queue as analysis_queue
import src.worker as worker_mod
from src.main import app

Base.metadata.create_all(engine)
with Session() as db:
    for role in ('admin','analyst','viewer'):
        email=f'{role}@acoustic-bayes.demo'
        if not db.scalar(select(User).where(User.email==email)):
            db.add(User(email=email,password_hash=hash_password('Research2026!'),role=role))
    rng=random.Random(11);LABELS=['正常','轴承磨损','转子偏心']
    s=Source(key='TX-B-01',name='浏览器测试来源',filename='b.csv',description='d');db.add(s);db.flush()
    recs=[]
    for i in range(45):
        cls=i%3
        vals={'rms':round(max(.1,rng.gauss([1.2,3.0,2.0][cls],.35)),3),
              'centroid':round(max(100,rng.gauss([900,1600,2300][cls],170)),2),
              'kurtosis':round(max(.1,rng.gauss([2.8,5.2,3.9][cls],.45)),3),'label':LABELS[cls]}
        db.add(Record(source_id=s.id,reference=f'TX-B-{i+1:04}',values=vals))
        recs.append({'id':i+1,'source_id':s.id,'reference':f'TX-B-{i+1:04}','values':vals})
    result=calculate(recs,{'folds':3,'smoothing':1e-9})
    db.add(Run(source_id=s.id,name='浏览器研究',state='completed',parameters={'folds':3,'smoothing':1e-9},
               snapshot={'source':{'id':s.id,'name':s.name,'filename':'b.csv'},'records':recs},
               result=result,created_at=now()));db.commit()

def worker_loop():
    while True:
        v=ps.queue.blpop(ps.PLAN_QUEUE,timeout=1)
        if v:ps.compute_plan(int(v[1]));continue
        v=analysis_queue.blpop('analysis:queue',timeout=1)
        if v:worker_mod.execute(int(v[1]))
threading.Thread(target=worker_loop,daemon=True).start()
config=uvicorn.Config(app,host='127.0.0.1',port=19317,log_level='warning')
server=uvicorn.Server(config)
threading.Thread(target=server.run,daemon=True).start()
import urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen('http://127.0.0.1:19317/health',timeout=1);print('READY',flush=True);break
    except Exception:time.sleep(0.3)
while True:time.sleep(60)
