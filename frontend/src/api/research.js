import {api} from './client.js';
export const sourcesApi={list:()=>api('/sources'),create:data=>api('/sources',{method:'POST',body:JSON.stringify(data)}),update:(id,data)=>api('/sources/'+id,{method:'PUT',body:JSON.stringify(data)}),records:id=>api('/sources/'+id+'/records'),add:(id,records)=>api('/sources/'+id+'/records',{method:'POST',body:JSON.stringify({records})})};
export const runsApi={list:()=>api('/runs'),get:id=>api('/runs/'+id),create:data=>api('/runs',{method:'POST',body:JSON.stringify(data)})};
export const notesApi={list:()=>api('/notes'),create:data=>api('/notes',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/notes/'+id+'/approve',{method:'POST'})};
export const planningApi={
  stations:()=>api('/planning/stations'),
  updateStation:(code,data)=>api('/planning/stations/'+code,{method:'PUT',body:JSON.stringify(data)}),
  lossTable:()=>api('/planning/loss-table'),
  updateLoss:data=>api('/planning/loss-table',{method:'PUT',body:JSON.stringify(data)}),
  plans:()=>api('/plans'),
  plan:id=>api('/plans/'+id),
  createPlan:data=>api('/plans',{method:'POST',body:JSON.stringify(data)}),
  recompute:id=>api('/plans/'+id+'/recompute',{method:'POST'}),
  confirm:id=>api('/plans/'+id+'/confirm',{method:'POST'}),
  cancel:id=>api('/plans/'+id+'/cancel',{method:'POST'}),
  execute:id=>api('/plans/'+id+'/execute',{method:'POST'})
};
