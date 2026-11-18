from sqlalchemy import Column,Integer,String,Text,JSON,ForeignKey
from ..config.database import Base
class Plan(Base):
    __tablename__='maintenance_plans'
    id=Column(Integer,primary_key=True)
    run_id=Column(Integer,ForeignKey('classifier_runs.id'),nullable=False)
    name=Column(String(160),nullable=False)
    state=Column(String(20),default='computing')
    created_by=Column(String(120),nullable=False)
    created_at=Column(String(40),nullable=False)
    updated_at=Column(String(40),nullable=False)
    confirmed_by=Column(String(120),default='')
    confirmed_at=Column(String(40),default='')
    cancelled_by=Column(String(120),default='')
    cancelled_at=Column(String(40),default='')
    executed_by=Column(String(120),default='')
    executed_at=Column(String(40),default='')
    error=Column(Text,default='')
    # 计算时冻结的输入：损失表、工位口径、后验摘要，保证页面可追查采用口径
    input_snapshot=Column(JSON,nullable=False)
    fingerprint=Column(String(80),default='')
    # 优化结果：逐样本选择、原因、期望损失、工时占用与剩余工时
    result=Column(JSON,nullable=True)
