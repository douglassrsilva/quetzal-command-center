import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle, ArrowRight, Ban, Check, Clock3, Database, FileClock,
  RefreshCw, RotateCcw, Save, ShieldCheck, UserRound, X,
} from 'lucide-react'
import { api, dateTime, money, number, patchIdempotent, postIdempotent } from './api'

const STATUS_LABELS:Record<string,string>={
  DRAFT:'Borrador',PENDING_APPROVAL:'Pendiente de aprobación',APPROVED:'Aprobada',
  REJECTED:'Rechazada',CANCELLED:'Cancelada',
}

type Props={
  optimizedDraft:any
  campaignRequest:any
  actor:string
  roles:string[]
  autoRestore:boolean
  onRestore:(campaign:any)=>void
}

export default function CampaignWorkflowPanel({optimizedDraft,campaignRequest,actor,roles,autoRestore,onRestore}:Props){
  const[campaigns,setCampaigns]=useState<any[]>([])
  const[active,setActive]=useState<any>(null)
  const[loading,setLoading]=useState(true)
  const[busy,setBusy]=useState('')
  const[error,setError]=useState('')
  const[message,setMessage]=useState('')
  const[title,setTitle]=useState('Campaña gobernada de retención')
  const[assignedTo,setAssignedTo]=useState(actor)
  const initialDraft=useRef(Boolean(optimizedDraft))
  const canCare=roles.includes('CARE_AGENT')||roles.includes('ADMIN')
  const canApprove=roles.includes('ACTION_APPROVER')||roles.includes('ADMIN')
  const owns=active&&[active.requested_by,active.assigned_to].some((value:string)=>String(value||'').toLowerCase()===actor.toLowerCase())

  useEffect(()=>{setAssignedTo(actor)},[actor])
  useEffect(()=>{
    let live=true
    async function load(){
      setLoading(true);setError('')
      try{
        const data:any=await api('/api/campaigns/drafts?limit=12')
        if(!live)return
        const items=data.campaigns||[];setCampaigns(items)
        if(autoRestore&&!initialDraft.current&&items.length){
          const detail:any=await api(`/api/campaigns/drafts/${items[0].campaign_id}`)
          if(live){setActive(detail.campaign);setTitle(detail.campaign.title);setAssignedTo(detail.campaign.assigned_to);onRestore(detail.campaign)}
        }
      }catch(err:any){if(live)setError(err.message)}finally{if(live)setLoading(false)}
    }
    load();return()=>{live=false}
  },[]) // eslint-disable-line react-hooks/exhaustive-deps

  async function refresh(selectId?:string){
    const data:any=await api('/api/campaigns/drafts?limit=12');setCampaigns(data.campaigns||[])
    if(selectId){const detail:any=await api(`/api/campaigns/drafts/${selectId}`);setActive(detail.campaign);return detail.campaign}
    return null
  }
  async function openCampaign(campaignId:string){
    setBusy(`open:${campaignId}`);setError('');setMessage('')
    try{const detail:any=await api(`/api/campaigns/drafts/${campaignId}`);setActive(detail.campaign);setTitle(detail.campaign.title);setAssignedTo(detail.campaign.assigned_to);onRestore(detail.campaign)}
    catch(err:any){setError(err.message)}finally{setBusy('')}
  }
  async function saveNew(){
    if(!optimizedDraft)return
    setBusy('save');setError('');setMessage('')
    try{
      const response:any=await postIdempotent('/api/campaigns/drafts',{title,assigned_to:assignedTo||null,campaign:campaignRequest})
      setActive(response.campaign);onRestore(response.campaign);await refresh()
      setMessage(`Campaña ${response.campaign.campaign_id} guardada en Lakebase.`)
    }catch(err:any){setError(err.message)}finally{setBusy('')}
  }
  async function saveRevision(){
    if(!active||!optimizedDraft)return
    setBusy('revision');setError('');setMessage('')
    try{
      const response:any=await patchIdempotent(`/api/campaigns/drafts/${active.campaign_id}/revision`,{expected_version:active.version,title,assigned_to:assignedTo||null,note:'Nueva audiencia y economía desde el optimizador',campaign:campaignRequest})
      setActive(response.campaign);onRestore(response.campaign);await refresh()
      setMessage(`Versión ${response.campaign.snapshot_version} guardada sin perder el histórico.`)
    }catch(err:any){setError(err.message)}finally{setBusy('')}
  }
  async function transition(to_status:string){
    if(!active)return
    setBusy(`transition:${to_status}`);setError('');setMessage('')
    try{
      const response:any=await patchIdempotent(`/api/campaigns/drafts/${active.campaign_id}`,{to_status,expected_version:active.version,note:`${STATUS_LABELS[to_status]} desde el ciclo gobernado`})
      setActive(response.campaign);onRestore(response.campaign);await refresh()
      setMessage(`Campaña actualizada a ${STATUS_LABELS[to_status]}.`)
    }catch(err:any){setError(err.message)}finally{setBusy('')}
  }
  const canRevise=active?.status==='DRAFT'&&optimizedDraft&&optimizedDraft.draft_id!==active.source_draft_id&&owns&&canCare
  return <section className="campaign-workflow panel">
    <header><div><span><Database/>LAKEBASE OPERACIONAL</span><h3>Ciclo persistente de campañas</h3><p>Borradores, versiones, responsable, aprobación segregada y auditoría que sobreviven al reload.</p></div><div className="campaign-workflow-lock"><ShieldCheck/><span><small>Límite operacional</small><b>NUNCA ENVÍA</b></span></div></header>
    <div className="campaign-workflow-body">
      <aside><div className="saved-campaigns-head"><span>CAMPAÑAS GUARDADAS</span><b>{number(campaigns.length,true)}</b></div>{loading?<p className="workflow-loading"><RefreshCw className="spin"/>Consultando Lakebase…</p>:!campaigns.length?<p className="workflow-loading"><FileClock/>Aún no hay campañas persistidas.</p>:<div className="saved-campaign-list">{campaigns.map(item=><button className={active?.campaign_id===item.campaign_id?'active':''} key={item.campaign_id} onClick={()=>openCampaign(item.campaign_id)}><span><b>{item.title}</b><small>{item.campaign_id} · v{item.snapshot_version}</small></span><em className={`campaign-state ${String(item.status).toLowerCase()}`}>{STATUS_LABELS[item.status]||item.status}</em><dl><div><dt>Audiencia</dt><dd>{number(item.selected_customers,true)}</dd></div><div><dt>Impacto</dt><dd>{money(item.estimated_net_impact_usd)}</dd></div></dl><ArrowRight/></button>)}</div>}</aside>
      <div className="campaign-workflow-detail">
        <section className="campaign-save-box"><div><label><span>Nombre operacional</span><input value={title} maxLength={160} onChange={event=>setTitle(event.target.value)}/></label><label><span>Responsable</span><input value={assignedTo} maxLength={200} onChange={event=>setAssignedTo(event.target.value)}/></label></div><p><Save/>Persistir vuelve a calcular la audiencia en el servidor. No confía en números enviados por el navegador.</p><div>{canRevise&&<button className="secondary" disabled={!!busy} onClick={saveRevision}><RotateCcw/>{busy==='revision'?'Versionando…':'Guardar nueva versión'}</button>}<button className="primary" disabled={!!busy||!optimizedDraft||!canCare||title.trim().length<3} onClick={saveNew}><Save/>{busy==='save'?'Guardando…':'Guardar como nueva'}</button></div></section>
        {!active?<div className="campaign-workflow-empty"><Database/><h4>Selecciona o guarda una campaña</h4><p>El snapshot persistido conserva audiencia, economía, propietario y huella de auditoría.</p></div>:<article className="campaign-record"><div className="campaign-record-head"><span className={`campaign-state ${String(active.status).toLowerCase()}`}>{STATUS_LABELS[active.status]||active.status}</span><span><small>Estado</small><b>v{active.version}</b></span><span><small>Snapshot</small><b>v{active.snapshot_version}</b></span><span><small>ID</small><b>{active.campaign_id}</b></span></div><h4>{active.title}</h4><dl><div><dt><UserRound/>Responsable</dt><dd>{active.assigned_to}</dd></div><div><dt><Clock3/>Actualizada</dt><dd>{dateTime(active.updated_at)}</dd></div><div><dt>Audiencia</dt><dd>{number(active.selected_customers,true)} · {active.audience_fingerprint}</dd></div><div><dt>Impacto neto</dt><dd>{money(active.estimated_net_impact_usd)} · ROI {active.estimated_roi_pct==null?'—':`${number(active.estimated_roi_pct)}%`}</dd></div></dl><div className="campaign-event-list">{(active.events||[]).slice().reverse().map((event:any)=><span key={event.event_id}><i/><b>{STATUS_LABELS[event.to_status]||event.event_type.replaceAll('_',' ')}</b><small>{dateTime(event.created_at)} · {event.actor}</small></span>)}</div><footer>{active.status==='DRAFT'&&owns&&canCare&&<><button disabled={!!busy} onClick={()=>transition('PENDING_APPROVAL')}><Check/>Enviar a aprobación</button><button className="danger-action" disabled={!!busy} onClick={()=>transition('CANCELLED')}><Ban/>Cancelar</button></>}{active.status==='PENDING_APPROVAL'&&canApprove&&actor.toLowerCase()!==String(active.requested_by||'').toLowerCase()&&<><button disabled={!!busy} onClick={()=>transition('APPROVED')}><Check/>Aprobar</button><button className="danger-action" disabled={!!busy} onClick={()=>transition('REJECTED')}><X/>Rechazar</button></>}{active.status==='PENDING_APPROVAL'&&owns&&canCare&&<button className="danger-action" disabled={!!busy} onClick={()=>transition('CANCELLED')}><Ban/>Cancelar solicitud</button>}<span><ShieldCheck/>No existe transición de envío</span></footer></article>}
      </div>
    </div>
    {error&&<div className="workflow-message error"><AlertTriangle/>{error}</div>}{message&&<div className="workflow-message"><Check/>{message}</div>}
  </section>
}
