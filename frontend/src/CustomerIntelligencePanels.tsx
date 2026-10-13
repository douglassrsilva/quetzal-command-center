import { useMemo, useState } from 'react'
import {
  Activity, AlertTriangle, CalendarDays, CheckCircle2, CircleGauge, ClipboardCheck,
  CreditCard, FileText, Network, RadioTower, ShieldCheck, Star, UserRound,
} from 'lucide-react'
import { dateTime, number } from './api'

function scorePercent(value:any,scale='0_TO_1'){
  const raw=Number(value||0)
  return scale==='0_TO_100'||raw>1?raw:raw*100
}

function directionLabel(value:string){
  if(value==='INCREASES_RISK')return 'Eleva riesgo'
  if(value==='LOWERS_RISK')return 'Reduce riesgo'
  if(value==='INCREASES_PRIORITY')return 'Eleva prioridad'
  return 'Neutro'
}

export function CustomerRiskExplanation({data}:{data:any}){
  if(!data)return null
  const scores=data.scores||{}
  const graphAvailable=scores.retention_priority!==null&&scores.retention_priority!==undefined
  return <section className="risk-explain panel">
    <header className="risk-explain-head"><div><span><CircleGauge/>DECISIÓN EXPLICABLE</span><h3>Por qué este cliente requiere atención</h3><p>La probabilidad individual no cambia. El grafo agrega contexto operacional de exposición y alcance.</p></div><div className="method-badge"><ShieldCheck/><span><small>Método</small><b>{data.is_shap?'SHAP': 'Señales separadas'}</b></span></div></header>
    <div className="risk-score-bridge"><article><small>Churn individual</small><strong>{number(scorePercent(scores.individual_baseline))}%</strong><span>Única probabilidad de churn</span></article><i>→</i><article className={!graphAvailable?'disabled':''}><small>Prioridad de retención</small><strong>{graphAvailable?`${number(scorePercent(scores.retention_priority,'0_TO_100'))}/100`:'—'}</strong><span>{graphAvailable?'Ranking operacional':'Grafo no disponible'}</span></article><i>+</i><article><small>Exposición relacional</small><strong>{scores.network_exposure==null?'—':`${number(scorePercent(scores.network_exposure,'0_TO_100'))}/100`}</strong><span>Asociación, no contagio</span></article></div>
    <div className="evidence-stack">{(data.evidence||[]).map((item:any)=><article key={item.code}><div className={`evidence-direction ${String(item.direction).toLowerCase()}`}>{item.direction==='LOWERS_RISK'?<CheckCircle2/>:<Activity/>}</div><span><b>{item.label}</b><small>{item.source} · {directionLabel(item.direction)}</small></span><div className="evidence-value"><strong>{number(scorePercent(item.value,item.scale))}%</strong>{item.model_weight!=null&&<small>Peso {number(Number(item.model_weight)*100)}%</small>}</div></article>)}</div>
    {data.reason_codes?.length>0&&<div className="reason-codes"><span>SEÑALES ACTIVAS</span>{data.reason_codes.map((item:any)=><b key={item.code}>{item.label}</b>)}</div>}
    <details className="explain-formula"><summary><FileText/>Ver fórmula, versión y límites</summary><p><b>{data.model_version||'baseline-only'}</b> · {data.formula}</p>{(data.limitations||[]).map((item:string)=><p key={item}><AlertTriangle/>{item}</p>)}</details>
  </section>
}

const GROUPS:Record<string,string[]>={
  service:['SUPPORT_TICKET','NETWORK_INCIDENT_CONTEXT'],
  billing:['BILLING'],
  experience:['NPS','CHURN_SCORE'],
  decisions:['RECOMMENDATION','RETENTION_CASE','SUBSCRIPTION_STARTED','SUBSCRIPTION_ENDED'],
}

function eventIcon(type:string){
  if(type==='SUPPORT_TICKET')return <ClipboardCheck/>
  if(type==='NETWORK_INCIDENT_CONTEXT')return <RadioTower/>
  if(type==='BILLING')return <CreditCard/>
  if(type==='NPS')return <Star/>
  if(type==='CHURN_SCORE')return <CircleGauge/>
  if(type==='RETENTION_CASE')return <ShieldCheck/>
  if(type.startsWith('SUBSCRIPTION'))return <UserRound/>
  return <CheckCircle2/>
}

function detailText(detail:any){
  const labels:Record<string,string>={category:'Categoría',reason:'Motivo',status:'Estado',priority:'Prioridad',sla_status:'SLA',amount_usd:'Monto USD',payment_status:'Pago',days_overdue:'Atraso',score:'Score',channel:'Canal',baseline_probability:'Churn individual',retention_priority:'Prioridad de retención',network_exposure:'Exposición relacional',decision:'Decisión',outcome:'Resultado',severity:'Severidad',case_id:'Caso',from_status:'Estado anterior',actor:'Responsable',note:'Nota'}
  return Object.entries(detail||{}).filter(([,value])=>value!==null&&value!==undefined&&value!==false).slice(0,4).map(([key,value])=>{
    const numericProbability=['baseline_probability'].includes(key)
    return `${labels[key]||key.replaceAll('_',' ')}: ${numericProbability?`${number(Number(value)*100)}%`:String(value)}`
  }).join(' · ')
}

export function CustomerTimeline({events,networkContext}:{events:any[];networkContext?:any}){
  const[filter,setFilter]=useState('all')
  const visible=useMemo(()=>filter==='all'?events:(events||[]).filter(event=>GROUPS[filter]?.includes(event.event_type)),[events,filter])
  if(!events?.length)return null
  return <section className="customer-timeline panel">
    <header><div><span><CalendarDays/>HISTORIA UNIFICADA</span><h3>Señales que construyen la decisión</h3><p>Servicio, experiencia, facturación, scoring y acciones en una secuencia auditable.</p></div><div className="timeline-filters">{[['all','Todo'],['service','Servicio'],['billing','Cobranza'],['experience','Experiencia'],['decisions','Decisiones']].map(([id,label])=><button className={filter===id?'active':''} onClick={()=>setFilter(id)} key={id}>{label}</button>)}</div></header>
    {networkContext?.association_type&&<div className="timeline-context"><Network/><span><b>Contexto de red: {networkContext.association_type}</b><small>{networkContext.direct_customer_attribution===false?'Asociación geográfica; no atribución directa al cliente.':'Asociación directa disponible.'}</small></span></div>}
    <div className="unified-timeline">{visible.map((event,index)=><article key={`${event.event_type}-${event.occurred_at}-${index}`}><div className={`timeline-icon type-${String(event.event_type).toLowerCase()}`}>{eventIcon(event.event_type)}</div><i/><div><span><b>{event.title}</b>{event.association_type==='GEOGRAPHIC_CONTEXT'&&<em>CONTEXTO GEOGRÁFICO</em>}</span><p>{detailText(event.detail)}</p><small>{dateTime(event.occurred_at)} · {event.source}</small></div></article>)}</div>
  </section>
}
