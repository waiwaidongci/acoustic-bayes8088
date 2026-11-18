from sqlalchemy import Column,Integer,String,ForeignKey,UniqueConstraint
from ..config.database import Base
class PlanLock(Base):
    """确认后锁定的工位工时；每条方案每个工位至多一行，重试不重复扣减。"""
    __tablename__='maintenance_plan_locks'
    __table_args__=(UniqueConstraint('plan_id','station_id',name='uq_plan_station_lock'),)
    id=Column(Integer,primary_key=True)
    plan_id=Column(Integer,ForeignKey('maintenance_plans.id'),nullable=False)
    station_id=Column(Integer,ForeignKey('maintenance_stations.id'),nullable=False)
    locked_minutes=Column(Integer,nullable=False)
    created_at=Column(String(40),nullable=False)
    released_at=Column(String(40),default='')
