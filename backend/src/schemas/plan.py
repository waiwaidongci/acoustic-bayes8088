from pydantic import BaseModel,Field
class PlanInput(BaseModel):
    run_id:int
    name:str=Field(min_length=2,max_length=160)
class StationInput(BaseModel):
    manual_minutes:int|None=Field(default=None,ge=0)
    capacity_minutes:int|None=Field(default=None,gt=0)
class LossInput(BaseModel):
    fault_label:str=Field(min_length=1,max_length=120)
    action_code:str=Field(min_length=1,max_length=40)
    expected_loss:float=Field(ge=0)
