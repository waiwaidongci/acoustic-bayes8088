from sqlalchemy import Column,Integer,String
from ..config.database import Base
class Station(Base):
    __tablename__='maintenance_stations'
    id=Column(Integer,primary_key=True)
    code=Column(String(40),unique=True,nullable=False)
    name=Column(String(120),nullable=False)
    capacity_minutes=Column(Integer,nullable=False)
    manual_minutes=Column(Integer,nullable=False,default=0)
    updated_at=Column(String(40),nullable=False)
