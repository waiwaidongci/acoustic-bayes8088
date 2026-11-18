from ..services import plans,planning_catalog
class PlansController:
    list=staticmethod(plans.list_plans)
    create=staticmethod(plans.create_plan)
    get=staticmethod(lambda db,id:plans.plan_view(db,plans.get_plan(db,id)))
    recompute=staticmethod(plans.recompute)
    confirm=staticmethod(plans.confirm_plan)
    cancel=staticmethod(plans.cancel_plan)
    execute=staticmethod(plans.execute_plan)
    stations=staticmethod(lambda db:planning_catalog.list_stations(db))
    update_station=staticmethod(planning_catalog.update_station)
    loss_table=staticmethod(lambda db:planning_catalog.loss_table(db))
    update_loss=staticmethod(planning_catalog.update_loss)
