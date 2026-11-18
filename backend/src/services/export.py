import csv,io
from fastapi import HTTPException
from fastapi.responses import Response
from ..models.note import Note
from .runs import get_run
from .plans import get_plan
from ..constants.enums import ACTION_NONE,ACTION_QUICK,ACTION_DEEP
ACTION_NAMES={ACTION_NONE:'免检放行',ACTION_QUICK:'快速复检',ACTION_DEEP:'停机检修'}
def csv_response(result,filename,columns=None):
    buf=io.StringIO();fields=columns or result['columns'];w=csv.DictWriter(buf,fieldnames=fields,extrasaction='ignore');w.writeheader()
    rows=result['rows'] if 'rows' in result else result.get('selections',[])
    for r in rows:w.writerow({k:r.get(k,'') for k in fields})
    return Response('﻿'+buf.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="'+filename+'"'})
def run_csv(db,id):
    r=get_run(db,id)
    if r.state!='completed':raise HTTPException(409,'结果尚未完成')
    return csv_response(r.result,'run-'+str(id)+'.csv')
def note_csv(db,id):
    n=db.get(Note,id)
    if not n:raise HTTPException(404,'未找到说明')
    if n.state!='approved':raise HTTPException(403,'仅批准后的业务说明可导出')
    return csv_response(n.frozen_result,'approved-'+str(id)+'.csv')
def plan_csv(db,id):
    p=get_plan(db,id)
    if p.state in ('computing','failed') or not p.result:raise HTTPException(409,'方案尚无可用选择结果')
    rows=[]
    for s in p.result['selections']:
        rows.append({'reference':s['reference'],'action':ACTION_NAMES.get(s['action'],s['action']),
                     'expected_loss':s['expected_loss'],
                     'loss_none':s['losses_by_action'].get(ACTION_NONE,''),
                     'loss_quick':s['losses_by_action'].get(ACTION_QUICK,''),
                     'loss_deep':s['losses_by_action'].get(ACTION_DEEP,''),
                     'use_a':s['use_minutes']['A'],'use_b':s['use_minutes']['B'],
                     'posteriors':';'.join(f'{k}={v:.4f}' for k,v in s['posteriors'].items()),
                     'reason':s['reason']})
    payload={'selections':rows}
    columns=['reference','action','expected_loss','loss_none','loss_quick','loss_deep','use_a','use_b','posteriors','reason']
    return csv_response(payload,'maintenance-plan-'+str(id)+'.csv',columns=columns)

