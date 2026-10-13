import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle, ArrowRight, CheckCircle2, DollarSign, Network, RefreshCw,
  Route, ShieldCheck, UserRound, RotateCcw, Database, Target,
} from 'lucide-react'
import { api, money, number } from './api'
import { CampaignEconomicJourney, type CampaignSeed } from './CommercialIntelligencePages'

const COUNTRIES = ['ALL','PA','MX','CO','BR','AR','CL','PE','EC','CR','GT','DO','UY']
const FLAGS:Record<string,string>={PA:'🇵🇦',MX:'🇲🇽',CO:'🇨🇴',BR:'🇧🇷',AR:'🇦🇷',CL:'🇨🇱',PE:'🇵🇪',EC:'🇪🇨',CR:'🇨🇷',GT:'🇬🇹',DO:'🇩🇴',UY:'🇺🇾'}
const STEP_DETAILS:Record<string,string>={PREFLIGHT:'Comprueba servicios, permisos y snapshots sin ejecutar jobs ni inferencia.',INCIDENT:'Revisa señal, severidad, SLA y valor expuesto.',GRAPH:'Explora alcance y exposición del grupo sin afirmar causalidad.',CUSTOMER_360:'Conecta productos, experiencia, SLA, valor y riesgo.',QUETZAL_IQ:'Investiga el contexto con una pregunta preparada y evidencia visible.',VOICE_OF_CUSTOMER:'Escucha el tema prioritario del mismo mercado.',CAMPAIGN_OPTIMIZER:'Prepara una audiencia gobernada; nunca envía la campaña.',ECONOMIC_JOURNEY:'Reconcilia beneficio, costo, impacto, sensibilidad y equilibrio sobre esa misma audiencia.'}

type Props={
  openIncident:(incidentId:string)=>void
  openCustomer:(customerId:string)=>void
  openGraph:(communityId:string)=>void
  openCampaign:(seed:CampaignSeed)=>void
  campaignDraft:any
  navigate:(page:'intelligence'|'voice')=>void
  onReset:()=>void
}

function severity(value:string){return <span className={`severity ${String(value||'MEDIUM').toLowerCase()}`}>{value||'MEDIUM'}</span>}

export default function DemoJourneyPage({openIncident,openCustomer,openGraph,openCampaign,campaignDraft,navigate,onReset}:Props){
  const[country,setCountry]=useState(()=>localStorage.getItem('quetzal-demo-country')||'ALL')
  const[data,setData]=useState<any>(null)
  const[loading,setLoading]=useState(true)
  const[error,setError]=useState('')
  const[nonce,setNonce]=useState(0)
  const[completed,setCompleted]=useState<string[]>(()=>{try{return JSON.parse(localStorage.getItem('quetzal-demo-progress')||'[]')}catch{return[]}})
  const[active,setActive]=useState(()=>localStorage.getItem('quetzal-demo-active-step')||'PREFLIGHT')
  useEffect(()=>localStorage.setItem('quetzal-demo-country',country),[country])
  useEffect(()=>localStorage.setItem('quetzal-demo-progress',JSON.stringify(completed)),[completed])
  useEffect(()=>localStorage.setItem('quetzal-demo-active-step',active),[active])
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError('')
    api(`/api/demo/manifest?country=${country}`,{signal:controller.signal}).then(setData).catch(err=>{if(err.name!=='AbortError')setError(err.message)}).finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return()=>controller.abort()
  },[country,nonce])
  const scenario=data?.scenario||{}
  const context=scenario.context||{}
  const incident=scenario.incident||{}
  const customer=scenario.customer||{}
  const steps=data?.steps||[]
  const campaignCompatible=useMemo(()=>Boolean(campaignDraft&&
    campaignDraft.scope?.requested_country===context.country&&
    campaignDraft.scope?.source_theme_id===context.voc_theme_id&&
    campaignDraft.constraints?.objective===context.campaign_objective
  ),[campaignDraft,context.country,context.voc_theme_id,context.campaign_objective])
  const campaignSeed:CampaignSeed={themeId:context.voc_theme_id||'OTHER',themeLabel:context.voc_theme_label||'Otros motivos',country:context.country||country,objective:context.campaign_objective||'RETENTION'}
  function runStep(step:any){
    const target=String(step.id).toUpperCase()
    const canComplete=target!=='ECONOMIC_JOURNEY'||campaignCompatible
    const nextCompleted=!canComplete||completed.includes(target)?completed:[...completed,target]
    localStorage.setItem('quetzal-demo-active-step',target)
    localStorage.setItem('quetzal-demo-progress',JSON.stringify(nextCompleted))
    setActive(target);setCompleted(nextCompleted)
    if(target==='PREFLIGHT')return document.querySelector('.certified-preflight')?.scrollIntoView({behavior:'smooth',block:'center'})
    if(target==='INCIDENT')return openIncident(context.incident_id)
    if(target==='GRAPH')return openGraph(context.community_id)
    if(target==='CUSTOMER_360')return openCustomer(context.customer_id)
    if(target==='QUETZAL_IQ'){localStorage.setItem('quetzal-demo-iq-prompt',context.iq_prompt||'');return navigate('intelligence')}
    if(target==='VOICE_OF_CUSTOMER'){localStorage.setItem('quetzal-voc-country',context.country);return navigate('voice')}
    if(target==='CAMPAIGN_OPTIMIZER'){localStorage.setItem('quetzal-campaign-country',context.country);return openCampaign(campaignSeed)}
    if(target==='ECONOMIC_JOURNEY')return document.querySelector('.campaign-economic-journey')?.scrollIntoView({behavior:'smooth',block:'start'})
  }
  function resetDemo(){
    const exact=['quetzal-voc-country','quetzal-campaign-country','quetzal-demo-iq-prompt']
    Object.keys(localStorage).forEach(key=>{if(key.startsWith('quetzal-demo-')||exact.includes(key))localStorage.removeItem(key)})
    setCountry('ALL');setCompleted([]);setActive('PREFLIGHT');onReset();setNonce(value=>value+1)
  }
  return <div className="demo-journey stack-lg">
    <section className="certified-demo-hero panel-dark">
      <div><span className="certified-badge"><ShieldCheck/>MODO DEMO CERTIFICADA</span><h2>Una historia verificable,<br/><em>de punta a punta.</em></h2><p>Ocho etapas sobre un snapshot publicado, con IDs reales, versiones visibles y cierre económico reconciliado. Esta ruta no ejecuta jobs, modelos ni campañas.</p></div>
      <div className="certified-demo-controls"><label><span>Mercado del escenario</span><select value={country} onChange={e=>{setCountry(e.target.value);setCompleted([]);setActive('PREFLIGHT')}}>{COUNTRIES.map(code=><option value={code} key={code}>{code==='ALL'?'Toda LATAM':`${FLAGS[code]} ${code}`}</option>)}</select></label><button className="demo-reset" onClick={resetDemo}><RotateCcw/>Reiniciar demo</button><small>Solo limpia el estado local del navegador. No elimina memoria de Lakebase ni datos backend.</small></div>
    </section>
    {loading&&<div className="state-box"><RefreshCw className="spin"/>Certificando el escenario…</div>}
    {error&&<div className="state-box error"><AlertTriangle/><span><b>No fue posible certificar el escenario.</b><small>{error}</small></span><button onClick={()=>setNonce(x=>x+1)}>Reintentar</button></div>}
    {!loading&&!error&&data?.available===false&&<div className="state-box"><AlertTriangle/><span><b>No hay un escenario certificado dentro de este alcance.</b><small>{data.reason||'Selecciona otro mercado.'}</small></span></div>}
    {!loading&&!error&&data?.available!==false&&<>
      <section className="demo-progress panel"><div><span>MANIFIESTO {data.manifest_id}</span><b>{completed.length} de {steps.length} etapas recorridas</b></div><div><i style={{width:`${steps.length?completed.length/steps.length*100:0}%`}}/></div><small>Escenario determinístico · datos sintéticos gobernados · solo lectura</small></section>
      <section className="certified-stepper panel"><div className="journey-section-head"><span><Route/>RECORRIDO CERTIFICADO</span><div>{FLAGS[context.country]} {scenario.title}</div></div><div className="journey-step-list">{steps.map((step:any,index:number)=><button className={`${active===step.id?'active':''} ${completed.includes(step.id)?'complete':''}`} key={step.id} onClick={()=>runStep(step)}><i>{completed.includes(step.id)?<CheckCircle2/>:index+1}</i><span><small>PASO {index+1}</small><b>{step.title}</b><p>{STEP_DETAILS[step.id]}</p></span><ArrowRight/></button>)}</div></section>
      <section className={`certified-preflight panel status-${String(data.preflight?.status||'degraded').toLowerCase()}`}><div><ShieldCheck/><span><small>PREFLIGHT DE SOLO LECTURA</small><b>{data.preflight?.status==='READY'?'Listo para presentar':'Presentable con observaciones'}</b><p>{(data.preflight?.checks||[]).filter((item:any)=>item.status==='READY').length} de {(data.preflight?.checks||[]).length} verificaciones listas. Ninguna inferencia paga o job fue iniciado.</p></span></div><div>{(data.preflight?.checks||[]).map((item:any)=><span className={`check-${String(item.status).toLowerCase()}`} key={item.name}><i/>{String(item.name).replaceAll('_',' ')}</span>)}</div></section>
      <section className="journey-anchor-grid">
        <article className="panel journey-anchor incident-anchor"><header><span><AlertTriangle/>SEÑAL OPERACIONAL</span>{severity(incident.severity)}</header><h3>{incident.title||'Incidente prioritario'}</h3><p>{incident.incident_id} · {FLAGS[incident.country]} {incident.country}</p><dl><div><dt>Clientes en alcance</dt><dd>{number(incident.affected_customers,true)}</dd></div><div><dt>Valor mensual expuesto</dt><dd>{money(incident.revenue_at_risk)}</dd></div><div><dt>SLA operacional</dt><dd>{incident.sla_status||'—'}</dd></div></dl><button onClick={()=>openIncident(incident.incident_id)}>Abrir incidente <ArrowRight/></button></article>
        <article className="panel journey-link"><Network/><strong>Contexto conectado,<br/>sin causalidad implícita</strong><p>El cliente y el incidente pertenecen al mismo mercado. Alcance, exposición relacional y churn permanecen como señales separadas.</p><span><ShieldCheck/>EVIDENCIA SEPARADA</span></article>
        <article className="panel journey-anchor customer-anchor"><header><span><UserRound/>CLIENTE PRIORITARIO</span><span className="status-pill">{customer.graph_risk_tier||customer.risk_tier||'ALTO RIESGO'}</span></header><h3>{customer.customer_name||customer.nombre_completo||customer.customer_ref||'Cliente seleccionado'}</h3><p>{customer.customer_id||customer.cliente_id} · {FLAGS[customer.country||customer.pais_codigo]} {customer.country||customer.pais_codigo}</p><dl><div><dt>Churn priorizado</dt><dd>{number(Number(customer.churn_probability||customer.baseline_churn_probability||0)*100)}%</dd></div><div><dt>Valor mensual</dt><dd>{money(customer.monthly_revenue||0,false)}</dd></div><div><dt>Próxima decisión</dt><dd>{String(customer.graph_recommended_action||customer.recommended_action||'Revisar 360').replaceAll('_',' ')}</dd></div></dl><button onClick={()=>openCustomer(customer.customer_id||customer.cliente_id)}>Abrir Cliente 360 <ArrowRight/></button></article>
      </section>
      <section className="certified-evidence panel"><header><span><Database/>EVIDENCIA DEL SNAPSHOT</span><b>Reproducible con DAB</b></header><div><Evidence label="Aplicación" value={`v${data.evidence?.app_version}`}/><Evidence label="Graph Intelligence" value={`${data.evidence?.graph_snapshot?.model_version||'—'} · ${data.evidence?.graph_snapshot?.run_id||'sin ejecución'}`}/><Evidence label="Modelo de churn" value={`${data.evidence?.churn_model?.model_version||'—'} · ${data.evidence?.churn_model?.model_run_id||'sin ejecución'}`}/><Evidence label="OntoBricks" value={`${data.evidence?.ontobricks?.domain||'—'} · ${data.evidence?.ontobricks?.version||'—'}`}/><Evidence label="VoC / campañas" value={`${data.evidence?.voc_version||'—'} · ${data.evidence?.campaign_version||'—'}`}/><Evidence label="Modo de costo" value={data.safety?.cost?.mode||'SOLO LECTURA'}/></div>{data.evidence?.warnings?.length>0&&<div className="evidence-warnings"><AlertTriangle/>{data.evidence.warnings.join(' · ')}</div>}<footer><ShieldCheck/><span><b>Garantías de esta ruta</b>Solo lecturas de Warehouse, App y APIs de metadatos. Sin inferencia, Genie, actualización del grafo, conector ni envío de campaña. Las decisiones siguen requiriendo aprobación humana.</span></footer></section>
      {campaignCompatible?<CampaignEconomicJourney draft={campaignDraft} certified/>:<section className="campaign-economic-journey economic-missing panel"><DollarSign/><div><span>CIERRE ECONÓMICO PENDIENTE</span><h3>Primero genera la audiencia gobernada.</h3><p>El cierre no usa promedios genéricos ni otra población. Debe recibir el borrador de {context.country}, tema {String(context.voc_theme_id||'OTHER').replaceAll('_',' ')} y objetivo {String(context.campaign_objective||'RETENTION').replaceAll('_',' ')}.</p>{campaignDraft&&<small>El borrador {campaignDraft.draft_id} pertenece a otro mercado, tema u objetivo y no será mezclado con este escenario.</small>}</div><button className="primary" onClick={()=>openCampaign(campaignSeed)}><Target/>Generar audiencia gobernada</button></section>}
    </>}
  </div>
}

function Evidence({label,value}:{label:string;value:string}){return <article><small>{label}</small><b>{value}</b></article>}
