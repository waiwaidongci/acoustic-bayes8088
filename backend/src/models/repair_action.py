from sqlalchemy import Column,Integer,String,ForeignKey
from ..config.database import Base
class RepairAction(Base):
    __tablename__='maintenance_actions'
    id=Column(Integer,primary_key=True)
    code=Column(String(40),unique=True,nullable=False)
    name=Column(String(120),nullable=False)
    station_id=Column(Integer,ForeignKey('maintenance_stations.id'),nullable=True)
    minutes_per_sample=Column(Integer,nullable=False,default=0)
