from fastapi import APIRouter,Depends
from ..config.database import db_session
from ..schemas.plan import PlanInput,StationInput,LossInput
from ..services.auth import current_user,writer,admin
from ..services.export import plan_csv
from ..controllers.plans import PlansController as C
router=APIRouter()
@router.get('/planning/stations')
def stations(db=Depends(db_session),u=Depends(current_user)):return C.stations(db)
@router.put('/planning/stations/{code}')
def update_station(code:str,data:StationInput,db=Depends(db_session),u=Depends(admin)):return C.update_station(db,u,code,data)
@router.get('/planning/loss-table')
def loss_table(db=Depends(db_session),u=Depends(current_user)):return C.loss_table(db)
@router.put('/planning/loss-table')
def update_loss(data:LossInput,db=Depends(db_session),u=Depends(admin)):return C.update_loss(db,u,data)
@router.get('/plans')
def plans(db=Depends(db_session),u=Depends(current_user)):return C.list(db)
@router.post('/plans')
def create(data:PlanInput,db=Depends(db_session),u=Depends(writer)):return C.create(db,u,data)
@router.get('/plans/{id}')
def detail(id:int,db=Depends(db_session),u=Depends(current_user)):return C.get(db,id)
@router.get('/plans/{id}/export')
def export(id:int,db=Depends(db_session),u=Depends(current_user)):return plan_csv(db,id)
@router.post('/plans/{id}/recompute')
def recompute(id:int,db=Depends(db_session),u=Depends(writer)):return C.recompute(db,u,id)
@router.post('/plans/{id}/confirm')
def confirm(id:int,db=Depends(db_session),u=Depends(writer)):return C.confirm(db,u,id)
@router.post('/plans/{id}/cancel')
def cancel(id:int,db=Depends(db_session),u=Depends(writer)):return C.cancel(db,u,id)
@router.post('/plans/{id}/execute')
def execute(id:int,db=Depends(db_session),u=Depends(writer)):return C.execute(db,u,id)
