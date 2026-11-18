from sqlalchemy import Column,Integer,String,Float,UniqueConstraint
from ..config.database import Base
class LossEntry(Base):
    __tablename__='maintenance_loss_table'
    __table_args__=(UniqueConstraint('fault_label','action_code',name='uq_loss_fault_action'),)
    id=Column(Integer,primary_key=True)
    fault_label=Column(String(120),nullable=False)
    action_code=Column(String(40),nullable=False)
    expected_loss=Column(Float,nullable=False)
