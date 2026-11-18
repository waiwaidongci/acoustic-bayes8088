"""仅用于本地无 Redis 环境的队列替身：实现 rpush/blpop/from_url/ping 语义，进程内 deque。"""
import collections,time,threading
_LOCK=threading.Lock()
_QUEUES=collections.defaultdict(collections.deque)
class FakeRedis:
    def __init__(self,*a,**k):pass
    @classmethod
    def from_url(cls,*a,**k):return cls()
    def rpush(self,k,v):
        with _LOCK:_QUEUES[str(k)].append(v)
        return len(_QUEUES[str(k)])
    def blpop(self,k,timeout=0):
        key=k if isinstance(k,str) else k
        deadline=time.time()+max(timeout or 0,0)
        while True:
            with _LOCK:
                if _QUEUES[key]:return (key,_QUEUES[key].popleft())
            if time.time()>=deadline:return None
            time.sleep(0.01)
    def ping(self):return True
