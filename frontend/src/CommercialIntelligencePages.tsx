import { useEffect, useMemo, useState, type FormEvent } from 'react'
import {
  AlertTriangle, ArrowRight, Ban, CheckCircle2, Database, DollarSign, Eye,
  Filter, Megaphone, MessageCircle, Radio, RefreshCw, ShieldCheck, Target,
  TrendingUp, UserRound, UsersRound,
} from 'lucide-react'
import { api, money, number, post } from './api'
import CampaignWorkflowPanel from './CampaignWorkflowPanel'

const COUNTRIES = ['ALL','PA','MX','CO','BR','AR','CL','PE','EC','CR','GT','DO','UY']
const FLAGS:Record<string,string>={PA:'🇵🇦',MX:'🇲🇽',CO:'🇨🇴',BR:'🇧🇷',AR:'🇦🇷',CL:'🇨🇱',PE:'🇵🇪',EC:'🇪🇨',CR:'🇨🇷',GT:'🇬🇹',DO:'🇩🇴',UY:'🇺🇾'}

export type CampaignSeed={themeId:string;themeLabel:string;country:string;objective:'RETENTION'|'CROSS_SELL'}
type VoiceProps={openCustomer:(customerId:string)=>void;openCampaign:(seed:CampaignSeed)=>void}
type CampaignProps={
  seed:CampaignSeed|null
  initialDraft:any
  onDraft:(draft:any)=>void
  openCustomer:(customerId:string)=>void
  actor:string
  roles:string[]
}

const themeObjective=(themeId:string):'RETENTION'|'CROSS_SELL'=>
  ['PLAN_VALUE','OTHER'].includes(themeId)?'CROSS_SELL':'RETENTION'

function Loading({label}:{label:string}){
  return <div className="state-box"><RefreshCw className="spin"/>{label}</div>
}

function ErrorState({message,retry}:{message:string;retry:()=>void}){
  return <div className="state-box error"><AlertTriangle/><span><b>No fue posible completar la consulta.</b><small>{message}</small></span><button className="secondary" onClick={retry}>Reintentar</button></div>
}

export function VoiceOfCustomerPage({openCustomer,openCampaign}:VoiceProps){
  const[country,setCountry]=useState(()=>localStorage.getItem('quetzal-voc-country')||'ALL')
  const[windowDays,setWindowDays]=useState(90)
  const[data,setData]=useState<any>(null)
  const[loading,setLoading]=useState(true)
  const[error,setError]=useState('')
  const[nonce,setNonce]=useState(0)
  useEffect(()=>localStorage.setItem('quetzal-voc-country',country),[country])
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError('')
    api(`/api/voc/overview?country=${country}&window_days=${windowDays}&max_themes=8`,{signal:controller.signal})
      .then(setData).catch((err:any)=>{if(err.name!=='AbortError')setError(err.message)})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return()=>controller.abort()
  },[country,windowDays,nonce])
  const summary=data?.summary||{}
  return <div className="voc-page stack-lg">
    <section className="voc-hero panel-dark">
      <div><span className="overline"><MessageCircle/>VOZ DEL CLIENTE</span><h2>Escuchar la señal.<br/><em>Actuar sobre la causa.</em></h2><p>Convierte tickets, NPS y SLA en temas explicables, clientes afectados y focos de acción. Las síntesis son demostrativas; nunca se presentan como transcripciones.</p></div>
      <div className="voc-hero-controls"><label><span>Mercado</span><select value={country} onChange={e=>setCountry(e.target.value)}>{COUNTRIES.map(code=><option value={code} key={code}>{code==='ALL'?'Toda LATAM':`${FLAGS[code]} ${code}`}</option>)}</select></label><label><span>Ventana</span><select value={windowDays} onChange={e=>setWindowDays(Number(e.target.value))}><option value="30">30 días</option><option value="60">60 días</option><option value="90">90 días</option><option value="180">180 días</option></select></label><span className="demo-data-badge"><Database/>DATOS SINTÉTICOS</span></div>
    </section>
    {loading&&<Loading label="Leyendo señales de clientes…"/>}
    {error&&<ErrorState message={error} retry={()=>setNonce(x=>x+1)}/>} 
    {!loading&&!error&&data&&<>
      <section className="voc-kpis">
        <article><MessageCircle/><span><small>Tickets observados</small><strong>{number(summary.tickets,true)}</strong><em>{number(summary.open_tickets,true)} abiertos</em></span></article>
        <article><UsersRound/><span><small>Clientes escuchados</small><strong>{number(summary.customers_observed,true)}</strong><em>{number(summary.nps_responses,true)} respuestas NPS</em></span></article>
        <article><TrendingUp/><span><small>NPS medio</small><strong>{summary.avg_nps==null?'—':number(summary.avg_nps)}</strong><em>{number(summary.detractors,true)} detractores</em></span></article>
        <article><AlertTriangle/><span><small>Incumplimientos SLA</small><strong>{number(summary.sla_breaches,true)}</strong><em>requieren cierre de ciclo</em></span></article>
      </section>
      {!!data.signals?.length&&<section className="voc-signals">{data.signals.map((signal:any)=><article className={`signal-${String(signal.severity).toLowerCase()}`} key={`${signal.type}-${signal.title}`}><span><Radio/><b>{signal.severity}</b></span><h3>{signal.title}</h3><p>{signal.description}</p><strong>{number(signal.value)} <small>{signal.unit}</small></strong></article>)}</section>}
      <section className="panel voc-themes">
        <header><div><span><Filter/>TEMAS PRIORIZADOS</span><h3>De la evidencia a una acción dirigida</h3><p>El score ordena volumen, negatividad, casos abiertos y SLA. No utiliza inferencia generativa.</p></div><span className="method-chip"><ShieldCheck/>{data.methodology?.theme_mapping_version||'voc-rules-v1'}</span></header>
        <div className="voc-theme-grid">{data.themes?.map((theme:any,index:number)=><article key={theme.theme_id}>
          <div className="theme-rank"><i>{index+1}</i><span><small>{theme.theme_id.replaceAll('_',' ')}</small><h4>{theme.label}</h4></span><strong>{number(theme.priority_score)}<small>prioridad</small></strong></div>
          <div className="theme-share"><div><i style={{width:`${Math.min(100,Number(theme.share_pct||0))}%`}}/></div><b>{number(theme.share_pct)}% de señales</b><span className={`trend-${String(theme.trend).toLowerCase()}`}>{theme.trend}</span></div>
          <dl><div><dt>Menciones</dt><dd>{number(theme.mentions,true)}</dd></div><div><dt>Negativas</dt><dd>{number(theme.negative_signals,true)}</dd></div><div><dt>Abiertas</dt><dd>{number(theme.open_cases,true)}</dd></div><div><dt>Fuera de SLA</dt><dd>{number(theme.sla_breaches,true)}</dd></div></dl>
          <p className="theme-evidence">{theme.evidence?.[0]||'Tema derivado de señales operacionales gobernadas.'}</p>
          {!!theme.customer_examples?.length&&<div className="voice-customers"><span>CLIENTES AFECTADOS</span>{theme.customer_examples.map((customer:any)=><button key={customer.customer_id} onClick={()=>openCustomer(customer.customer_id)}><UserRound/><span><b>{customer.customer_ref||customer.customer_id}</b><small>{FLAGS[customer.country]} {customer.country} · NPS {customer.nps??'—'} · {number(Number(customer.churn_probability||0)*100)}% churn</small></span><ArrowRight/></button>)}</div>}
          <footer><span><Target/>{theme.recommended_focus}</span><button onClick={()=>openCampaign({themeId:theme.theme_id,themeLabel:theme.label,country,objective:themeObjective(theme.theme_id)})}>Optimizar campaña <ArrowRight/></button></footer>
        </article>)}</div>
      </section>
      <section className="voc-governance panel"><div><ShieldCheck/><span><b>Síntesis basada en reglas</b><small>{data.methodology?.type} · sin inferencia de IA</small></span></div><div className="source-list">{data.source_coverage?.map((source:any)=><span key={source.source}><Database/><b>{source.source}</b><small>{number(source.rows,true)} filas</small></span>)}</div><details><summary>Fuentes y limitaciones</summary>{data.limitations?.map((item:string)=><p key={item}>{item}</p>)}</details></section>
    </>}
  </div>
}

export function CampaignOptimizerPage({seed,initialDraft,onDraft,openCustomer,actor,roles}:CampaignProps){
  const[country,setCountry]=useState(seed?.country||localStorage.getItem('quetzal-campaign-country')||'ALL')
  const[objective,setObjective]=useState<'RETENTION'|'CROSS_SELL'>(seed?.objective||'RETENTION')
  const[channel,setChannel]=useState('EMAIL')
  const[budget,setBudget]=useState(5000)
  const[cost,setCost]=useState(2)
  const[maxCustomers,setMaxCustomers]=useState(1000)
  const[capacity,setCapacity]=useState(500)
  const[responseRate,setResponseRate]=useState(8)
  const[sourceTheme,setSourceTheme]=useState<string|null>(seed?.themeId||null)
  const[result,setResult]=useState<any>(initialDraft)
  const[busy,setBusy]=useState(false)
  const[error,setError]=useState('')
  useEffect(()=>{if(seed){
    setCountry(seed.country);setObjective(seed.objective);setSourceTheme(seed.themeId)
    const compatible=initialDraft?.scope?.requested_country===seed.country&&initialDraft?.scope?.source_theme_id===seed.themeId&&initialDraft?.constraints?.objective===seed.objective
    setResult(compatible?initialDraft:null)
  }},[seed,initialDraft])
  useEffect(()=>localStorage.setItem('quetzal-campaign-country',country),[country])
  const campaignRequest=useMemo(()=>({
    country,objective,channel,budget_usd:budget,cost_per_contact_usd:cost,
    max_customers:maxCustomers,contact_capacity:capacity,
    expected_response_rate_pct:responseRate,horizon_months:12,
    source_theme_id:sourceTheme,
  }),[country,objective,channel,budget,cost,maxCustomers,capacity,responseRate,sourceTheme])
  async function optimize(event:FormEvent){
    event.preventDefault();setBusy(true);setError('')
    try{const draft=await post('/api/campaigns/optimize',campaignRequest);setResult(draft);onDraft(draft)}
    catch(err:any){setError(err.message)}finally{setBusy(false)}
  }
  function restoreCampaign(campaign:any){
    const request=campaign?.campaign_request||{}
    const snapshot=campaign?.campaign_snapshot
    setCountry(String(request.country||campaign?.requested_country||'ALL'))
    setObjective((request.objective||campaign?.objective||'RETENTION') as 'RETENTION'|'CROSS_SELL')
    setChannel(String(request.channel||campaign?.channel||'EMAIL'))
    setBudget(Number(request.budget_usd??5000))
    setCost(Number(request.cost_per_contact_usd??2))
    setMaxCustomers(Number(request.max_customers??1000))
    setCapacity(Number(request.contact_capacity??500))
    setResponseRate(Number(request.expected_response_rate_pct??8))
    setSourceTheme(request.source_theme_id||campaign?.source_theme_id||null)
    if(snapshot){setResult(snapshot);onDraft(snapshot)}
  }
  const funnel=result?.funnel||{}
  const impact=result?.impact||{}
  const stages=useMemo(()=>[
    {label:'En alcance',value:funnel.customers_in_scope},
    {label:'Con consentimiento',value:funnel.marketing_consented},
    {label:'Canal disponible',value:funnel.channel_reachable},
    {label:'Servicio elegible',value:funnel.service_eligible},
    {label:'Oferta elegible',value:funnel.offer_eligible},
    {label:'Seleccionados',value:funnel.selected},
  ],[funnel])
  return <div className="campaign-page stack-lg">
    <section className="campaign-header panel-dark"><div><span className="overline"><Megaphone/>OPTIMIZADOR DE CAMPAÑAS</span><h2>Alcance máximo.<br/><em>Presión comercial mínima.</em></h2><p>Construye una audiencia explicable bajo presupuesto, capacidad, consentimiento y servicio antes de venta. El resultado siempre es un borrador.</p></div><div className="draft-lock"><ShieldCheck/><span><b>NUNCA ENVÍA LA CAMPAÑA</b><small>Selección read-only · aprobación humana obligatoria</small></span></div></section>
    {seed&&<section className="campaign-source"><MessageCircle/><span><small>SEÑAL DE ORIGEN · VOZ DEL CLIENTE</small><b>{seed.themeLabel}</b><em>{seed.themeId.replaceAll('_',' ')}</em></span><CheckCircle2/></section>}
    <section className="campaign-workbench">
      <form className="panel optimizer-form" onSubmit={optimize}><header><span><Target/>CONFIGURAR OBJETIVO</span><h3>Restricciones de la campaña</h3></header><div className="optimizer-fields">
        <label><span>Objetivo</span><select value={objective} onChange={e=>setObjective(e.target.value as any)}><option value="RETENTION">Retención</option><option value="CROSS_SELL">Cross-sell</option></select></label>
        <label><span>Mercado</span><select value={country} onChange={e=>setCountry(e.target.value)}>{COUNTRIES.map(code=><option value={code} key={code}>{code==='ALL'?'Toda LATAM':`${FLAGS[code]} ${code}`}</option>)}</select></label>
        <label><span>Canal</span><select value={channel} onChange={e=>setChannel(e.target.value)}><option value="EMAIL">Email</option><option value="SMS">SMS</option><option value="WHATSAPP">WhatsApp</option><option value="CALL">Call center</option></select></label>
        <label><span>Presupuesto</span><input type="number" min="1" max="10000000" value={budget} onChange={e=>setBudget(Number(e.target.value))}/><small>USD</small></label>
        <label><span>Costo por contacto</span><input type="number" min="0.01" max="10000" step="0.01" value={cost} onChange={e=>setCost(Number(e.target.value))}/><small>USD</small></label>
        <label><span>Audiencia máxima</span><input type="number" min="1" max="100000" value={maxCustomers} onChange={e=>setMaxCustomers(Number(e.target.value))}/></label>
        <label><span>Capacidad operacional</span><input type="number" min="1" max="100000" value={capacity} onChange={e=>setCapacity(Number(e.target.value))}/></label>
        <label><span>Respuesta esperada</span><input type="number" min="0" max="100" step="0.1" value={responseRate} onChange={e=>setResponseRate(Number(e.target.value))}/><small>%</small></label>
      </div><button className="primary optimize-button" disabled={busy}>{busy?<RefreshCw className="spin"/>:<Target/>}{busy?'Optimizando audiencia…':'Generar audiencia gobernada'}</button>{error&&<p className="form-error">{error}</p>}<p className="optimizer-note"><ShieldCheck/>Solo lectura: no se crean registros ni se invoca un conector.</p></form>
      <div className="campaign-results">{!result?<div className="panel campaign-empty"><Megaphone/><h3>Una audiencia, no un disparo</h3><p>Configura las restricciones para ver elegibilidad, exclusiones, clientes priorizados e impacto estimado antes de cualquier aprobación.</p></div>:<>
        <section className="draft-status panel"><span><CheckCircle2/><b>{result.status}</b><small>{result.draft_id}</small></span><div><ShieldCheck/>Requiere aprobación humana</div><em>{result.execution?.campaign_sent?'ENVIADA':'NO ENVIADA'}</em></section>
        <section className="campaign-impact"><article><UsersRound/><span><small>Audiencia seleccionada</small><b>{number(funnel.selected,true)}</b><em>de {number(funnel.customers_in_scope,true)} clientes</em></span></article><article><DollarSign/><span><small>Costo estimado</small><b>{money(impact.estimated_contact_cost_usd,false)}</b><em>{money(impact.budget_remaining_usd,false)} disponibles</em></span></article><article><TrendingUp/><span><small>Conversiones estimadas</small><b>{number(impact.estimated_conversions)}</b><em>hipótesis de {number(responseRate)}%</em></span></article><article><Target/><span><small>Impacto neto estimado</small><b>{money(impact.estimated_net_impact_usd)}</b><em>contrafactual, no promesa</em></span></article></section>
        <section className="panel campaign-funnel"><header><span><Filter/>EMBUDO DE ELEGIBILIDAD</span><small>Service-before-sales aplicado antes del ranking</small></header><div>{stages.map((stage,index)=>{const base=Number(funnel.customers_in_scope||1);return <article key={stage.label}><span><i>{index+1}</i><b>{stage.label}</b></span><strong>{number(stage.value,true)}</strong><div><i style={{width:`${Math.max(1,Number(stage.value||0)/base*100)}%`}}/></div></article>})}</div><footer>{Object.entries(funnel.excluded||{}).map(([key,value])=><span key={key}><Ban/>{key.replaceAll('_',' ')} <b>{number(value,true)}</b></span>)}</footer></section>
      </>}</div>
    </section>
    {result&&<CampaignEconomicJourney draft={result}/>} 
    <CampaignWorkflowPanel optimizedDraft={result} campaignRequest={campaignRequest} actor={actor} roles={roles} autoRestore={!seed} onRestore={restoreCampaign}/>
    {result&&<section className="panel audience-preview"><header><div><span><Eye/>VISTA PREVIA GOBERNADA</span><h3>Clientes priorizados</h3><p>Muestra limitada de la audiencia; no se envió ninguna comunicación.</p></div><span>{number(result.audience_preview?.length||0)} de {number(funnel.selected,true)}</span></header><div className="audience-table"><div className="audience-head"><span>Cliente</span><span>Prioridad</span><span>Señales</span><span>Oferta</span><span>Costo</span><span/></div>{result.audience_preview?.map((customer:any)=><article key={customer.customer_id}><span><b>{customer.customer_ref}</b><small>{FLAGS[customer.country]} {customer.country} · {customer.segment}</small></span><span><b>{number(customer.score)}</b><small>{number(Number(customer.churn_probability||0)*100)}% churn · {money(customer.monthly_revenue,false)}/mes</small></span><span>{customer.reason_codes?.slice(0,3).map((code:string)=><em key={code}>{code.replaceAll('_',' ')}</em>)}</span><span><b>{customer.offer?.product_name||'—'}</b><small>{customer.offer?`${money(customer.offer.price_usd,false)}/mes`:'Sin oferta'}</small></span><span><b>{money(customer.estimated_contact_cost_usd,false)}</b><small>{customer.channel}</small></span><button onClick={()=>openCustomer(customer.customer_id)} aria-label={`Abrir Cliente 360 ${customer.customer_ref}`}><UserRound/><ArrowRight/></button></article>)}</div></section>}
    {result&&<section className="campaign-governance panel"><div><ShieldCheck/><span><b>{result.methodology?.type}</b><small>{result.methodology?.selection_version} · sin inferencia de IA</small></span></div><div><Radio/><span><b>Política temática</b><small>{result.methodology?.source_theme_policy||'Audiencia derivada de señales gobernadas.'}</small></span></div><details><summary>Fórmulas y limitaciones</summary>{Object.entries(result.formulas||{}).map(([key,value])=><p key={key}><b>{key.replaceAll('_',' ')}</b>: <code>{String(value)}</code></p>)}{result.limitations?.map((item:string)=><p key={item}>{item}</p>)}</details></section>}
  </div>
}

export function CampaignEconomicJourney({draft,certified=false}:{draft:any;certified?:boolean}){
  const impact=draft?.impact||{}
  const reconciliation=draft?.reconciliation||{}
  const intermediates=draft?.intermediates||{}
  const risk=draft?.methodology?.risk_contract||{}
  const outcome=String(impact.outcome||'BREAK_EVEN')
  const outcomeLabel=outcome==='POSITIVE'?'POSITIVO':outcome==='NEGATIVE'?'NEGATIVO':'EQUILIBRIO'
  const breakEven=impact.break_even_response_rate_pct
  const scenarios=[
    ['Conservador',draft?.sensitivity?.conservative],
    ['Base',draft?.sensitivity?.base],
    ['Optimista',draft?.sensitivity?.optimistic],
  ] as const
  return <section className={`campaign-economic-journey panel outcome-${outcome.toLowerCase()} ${certified?'certified-economic':''}`}>
    <header><div><span><DollarSign/>{certified?'CIERRE ECONÓMICO CERTIFICADO':'JORNADA ECONÓMICA'}</span><h3>Una audiencia. Las mismas premisas. Un resultado reconciliado.</h3><p>Beneficio, costo e impacto se calculan sobre los mismos clientes seleccionados por el optimizador.</p></div><em>{outcomeLabel}</em></header>
    <div className="economic-reconciliation"><span><small>Borrador</small><b>{draft?.draft_id||'—'}</b></span><span><small>Población</small><b>{number(reconciliation.selected_customers,true)} clientes</b></span><span><small>Elegibles antes de límites</small><b>{number(reconciliation.eligible_before_caps,true)}</b></span><span><small>Huella de audiencia</small><code>{reconciliation.audience_fingerprint||'—'}</code></span><span className="reconciled"><CheckCircle2/><b>Misma población</b><small>{reconciliation.same_population_used_for_impact?'Audiencia e impacto reconciliados':'Reconciliación no confirmada'}</small></span></div>
    <div className="economic-kpis"><article><TrendingUp/><span><small>Beneficio bruto estimado</small><b>{money(impact.estimated_gross_benefit_usd)}</b><em>con respuesta de {number(impact.expected_response_rate_pct)}%</em></span></article><article><DollarSign/><span><small>Costo incluido</small><b>{money(impact.estimated_contact_cost_usd)}</b><em>contactos seleccionados</em></span></article><article><Target/><span><small>Impacto neto</small><b>{money(impact.estimated_net_impact_usd)}</b><em>beneficio menos costo</em></span></article><article><ShieldCheck/><span><small>ROI estimado</small><b>{impact.estimated_roi_pct==null?'—':`${number(impact.estimated_roi_pct)}%`}</b><em>contrafactual, no causal</em></span></article></div>
    <div className="economic-analysis"><article className="break-even-card"><span>PUNTO DE EQUILIBRIO</span><strong>{breakEven==null?'No calculable':`${number(breakEven)}%`}</strong><p>{breakEven==null?'No existe beneficio potencial observable para cubrir el costo incluido.':impact.break_even_reachable?`La hipótesis base está ${number(Math.abs(impact.margin_vs_break_even_pct_points))} puntos ${impact.margin_vs_break_even_pct_points>=0?'por encima':'por debajo'} del equilibrio.`:'El costo no se recupera ni con una respuesta de 100%.'}</p><small>Solo incluye costo por contacto; no incorpora los costos excluidos.</small></article><article className="economic-intermediates"><span>INTERMEDIOS AUDITABLES</span><dl><div><dt>Ingreso mensual de la audiencia</dt><dd>{money(intermediates.audience_monthly_revenue_usd)}</dd></div><div><dt>Churn individual medio</dt><dd>{number(Number(intermediates.average_churn_probability||0)*100)}%</dd></div><div><dt>Beneficio potencial al 100%</dt><dd>{money(intermediates.gross_benefit_at_100_pct_response_usd)}</dd></div><div><dt>Horizonte comercial</dt><dd>{number(risk.business_value_horizon_months,true)} meses</dd></div></dl></article></div>
    <div className="economic-sensitivity"><header><span>SENSIBILIDAD</span><small>La tasa cambia; audiencia, horizonte y costo permanecen constantes.</small></header><div>{scenarios.map(([label,item])=><article key={label}><span>{label}</span><b className={Number(item?.estimated_net_impact_usd)<0?'negative':''}>{money(item?.estimated_net_impact_usd||0)}</b><small>{number(item?.expected_response_rate_pct||0)}% respuesta · {item?.estimated_roi_pct==null?'ROI —':`ROI ${number(item.estimated_roi_pct)}%`}</small></article>)}</div></div>
    <div className="economic-contract"><div><ShieldCheck/><span><b>Dos horizontes, dos significados</b><p>Churn: probabilidad de cancelación en los próximos {number(risk.churn_prediction_horizon_days,true)} días; no es una tasa anual. Valor: {number(risk.business_value_horizon_months,true)} meses de ingreso bajo una hipótesis combinada de respuesta y éxito.</p></span></div><details><summary>Costos, fórmulas y limitaciones</summary><section className="economic-costs"><div><b>Incluido</b>{draft?.methodology?.costs_included?.map((item:string)=><p key={item}><CheckCircle2/>{item}</p>)}</div><div><b>No incluidos</b>{draft?.methodology?.costs_excluded?.map((item:string)=><p key={item}><Ban/>{item}</p>)}</div></section><div className="economic-formulas">{Object.entries(draft?.formulas||{}).map(([key,value])=><p key={key}><b>{key.replaceAll('_',' ')}</b><code>{String(value)}</code></p>)}</div>{draft?.limitations?.map((item:string)=><p className="economic-limitation" key={item}>{item}</p>)}</details></div>
    <footer><Database/><span><b>Estimación contrafactual · datos sintéticos</b>No demuestra causalidad, no garantiza resultados y no envía ni persiste una campaña.</span></footer>
  </section>
}
