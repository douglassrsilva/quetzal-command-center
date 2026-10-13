import { useState } from 'react'
import { AlertTriangle, ArrowRight, Check, Clock3, Database, ShieldCheck, X } from 'lucide-react'
import { dateTime, patchIdempotent } from './api'

const STATUS_LABELS:Record<string,string>={
  PENDING_APPROVAL:'Pendiente de aprobación',APPROVED:'Aprobado',REJECTED:'Rechazado',
  IN_PROGRESS:'En curso',RESOLVED:'Resuelto',CLOSED:'Cerrado',
}
const NEXT:Record<string,string[]>={
  PENDING_APPROVAL:['APPROVED','REJECTED'],APPROVED:['IN_PROGRESS'],IN_PROGRESS:['RESOLVED'],RESOLVED:['CLOSED'],
}
const ACTION_LABELS:Record<string,string>={APPROVED:'Aprobar',REJECTED:'Rechazar',IN_PROGRESS:'Iniciar',RESOLVED:'Resolver',CLOSED:'Cerrar'}

export default function RetentionWorkflowPanel({workflow,onChanged}:{workflow:any;onChanged:()=>void}){
  const[busy,setBusy]=useState('')
  const[message,setMessage]=useState('')
  if(!workflow)return null
  if(workflow.status!=='READY')return <section className="retention-workflow panel degraded-workflow">
    <AlertTriangle/><div><span>WORKFLOW OPERACIONAL DEGRADADO</span><h3>Casos de retención temporalmente bloqueados</h3><p>{workflow.message||'Lakebase no está disponible. Ninguna mutación será simulada.'}</p></div>
  </section>
  const cases=workflow.cases||[]
  async function transition(item:any,to_status:string){
    setBusy(`${item.case_id}:${to_status}`);setMessage('')
    try{
      await patchIdempotent(`/api/retention-cases/${item.case_id}`,{
        to_status,expected_version:item.version,note:`${ACTION_LABELS[to_status]} desde Cliente 360`,
      })
      setMessage(`Caso ${item.case_id} actualizado a ${STATUS_LABELS[to_status]}.`);onChanged()
    }catch(error:any){setMessage(error.message)}finally{setBusy('')}
  }
  return <section className="retention-workflow panel">
    <header><div><span><Database/>LAKEBASE OPERACIONAL</span><h3>Casos de retención y SLA</h3><p>Estado transaccional, aprobación humana, versión y auditoría persistente.</p></div><div className="workflow-source"><ShieldCheck/><span><small>Fuente de verdad</small><b>quetzal_app.retention_cases</b></span></div></header>
    {!cases.length?<div className="workflow-empty"><Clock3/><span><b>Aún no hay casos para este cliente</b><small>Crea uno desde una próxima mejor acción; comenzará pendiente de aprobación.</small></span></div>:<div className="retention-case-list">{cases.map((item:any)=>{
      const overdue=!['RESOLVED','CLOSED','REJECTED'].includes(item.status)&&new Date(item.sla_due_at).getTime()<Date.now()
      return <article key={item.case_id}>
        <div className="case-head"><span className={`status-pill ${String(item.status).toLowerCase()}`}>{STATUS_LABELS[item.status]||item.status}</span><span className={`case-priority ${String(item.priority).toLowerCase()}`}>{item.priority}</span><small>v{item.version}</small></div>
        <h4>{item.title}</h4><p>{item.rationale}</p>
        <dl><div><dt>Caso</dt><dd>{item.case_id}</dd></div><div><dt>Responsable</dt><dd>{item.assigned_to}</dd></div><div><dt>SLA</dt><dd className={overdue?'overdue':''}>{dateTime(item.sla_due_at)}{overdue?' · vencido':''}</dd></div><div><dt>Modelo / run</dt><dd>v{item.churn_model_version} · {String(item.churn_model_run_id).slice(0,12)}</dd></div></dl>
        <div className="case-events">{(item.events||[]).slice(-4).reverse().map((event:any)=><span key={event.event_id}><i/><b>{STATUS_LABELS[event.to_status]||event.to_status}</b><small>{dateTime(event.created_at)} · {event.actor}</small></span>)}</div>
        {!!NEXT[item.status]?.length&&<footer>{NEXT[item.status].map(status=><button className={status==='REJECTED'?'danger-action':''} disabled={!!busy} onClick={()=>transition(item,status)} key={status}>{status==='REJECTED'?<X/>:<Check/>}{ACTION_LABELS[status]}<ArrowRight/></button>)}</footer>}
      </article>
    })}</div>}
    {message&&<div className="workflow-message">{message}</div>}
  </section>
}
