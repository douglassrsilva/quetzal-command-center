import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Activity, AlertTriangle, ArrowRight, BarChart3, BellRing, BrainCircuit, Check, ChevronDown,
  CircleGauge, ClipboardCheck, Clock3, Command, Database, ExternalLink, FileCheck2,
  Gauge, Globe2, Headphones, LayoutDashboard, MapPin, Menu, MessageSquareText,
  Moon, Network, RadioTower, RefreshCw, Route, Search, Send, Settings2, ShieldCheck,
  Sparkles, Sun, Table2, Target, Telescope, TrendingUp, UserRound, UsersRound, WandSparkles, X, Zap,
} from 'lucide-react'
import { api, dateTime, money, number, patch, post, postIdempotent } from './api'
import { inferGenieChart, numericValue, type GenieChartSpec } from './genieCharts'
import CustomerGraphPanel from './CustomerGraphPanel'
import GraphExplorerPage from './GraphExplorerPage'
import DemoJourneyPage from './DemoJourneyPage'
import AiPreflight from './AiPreflight'
import { CustomerRiskExplanation, CustomerTimeline } from './CustomerIntelligencePanels'
import RetentionWorkflowPanel from './RetentionWorkflowPanel'
import { CampaignOptimizerPage, VoiceOfCustomerPage, type CampaignSeed } from './CommercialIntelligencePages'

type Page = 'command' | 'journey' | 'analytics' | 'incidents' | 'network' | 'customers' | 'voice' | 'customer360' | 'graph' | 'campaigns' | 'actions' | 'scenarios' | 'intelligence' | 'governance'

const COUNTRIES = ['ALL', 'PA', 'MX', 'CO', 'BR', 'AR', 'CL', 'PE', 'EC', 'CR', 'GT', 'DO', 'UY']
const FLAGS: Record<string, string> = { PA:'🇵🇦',MX:'🇲🇽',CO:'🇨🇴',BR:'🇧🇷',AR:'🇦🇷',CL:'🇨🇱',PE:'🇵🇪',EC:'🇪🇨',CR:'🇨🇷',GT:'🇬🇹',DO:'🇩🇴',UY:'🇺🇾' }

const NAV: {id: Page; label: string; icon: typeof Command; group: string}[] = [
  { id:'command', label:'Centro de mando', icon:Command, group:'OPERACIÓN' },
  { id:'journey', label:'Demo certificada', icon:Route, group:'DEMO' },
  { id:'analytics', label:'Analítica AI/BI', icon:LayoutDashboard, group:'OPERACIÓN' },
  { id:'incidents', label:'Incidentes', icon:AlertTriangle, group:'OPERACIÓN' },
  { id:'network', label:'Red y alcance', icon:RadioTower, group:'OPERACIÓN' },
  { id:'customers', label:'Impacto cliente', icon:UsersRound, group:'DECISIÓN' },
  { id:'voice', label:'Voz del cliente', icon:MessageSquareText, group:'DECISIÓN' },
  { id:'customer360', label:'Cliente 360', icon:UserRound, group:'DECISIÓN' },
  { id:'graph', label:'Graph Intelligence', icon:Network, group:'DECISIÓN' },
  { id:'campaigns', label:'Optimizador campañas', icon:Target, group:'DECISIÓN' },
  { id:'actions', label:'Centro de acciones', icon:ClipboardCheck, group:'DECISIÓN' },
  { id:'scenarios', label:'Escenarios', icon:TrendingUp, group:'DECISIÓN' },
  { id:'intelligence', label:'Inteligencia', icon:Sparkles, group:'INTELIGENCIA' },
  { id:'governance', label:'Confianza y alertas', icon:ShieldCheck, group:'INTELIGENCIA' },
]

const PAGE_META: Record<Page, {eyebrow:string; title:string; subtitle:string}> = {
  command: { eyebrow:'OPERACIÓN LATAM', title:'Decidir antes de que la señal se pierda.', subtitle:'Una vista priorizada de red, clientes, riesgo y acciones en los 12 mercados.' },
  journey: { eyebrow:'MODO DEMO CERTIFICADA', title:'Una historia verificable, sin sorpresas.', subtitle:'Ocho etapas determinísticas, evidencia versionada y un cierre económico sobre la audiencia exacta.' },
  analytics: { eyebrow:'AI/BI GOBERNADO', title:'Analítica que conecta cada mercado.', subtitle:'Explora el desempeño comercial y operativo en el dashboard interactivo de Databricks.' },
  incidents: { eyebrow:'CONTROL OPERATIVO', title:'Incidentes que importan.', subtitle:'Priorizados por severidad técnica, clientes afectados, churn y valor en riesgo.' },
  network: { eyebrow:'ALCANCE SIN FRONTERAS', title:'La red, de continente a torre.', subtitle:'Navega por país y ciudad con una semántica clara de salud, capacidad y calidad.' },
  customers: { eyebrow:'EXPERIENCIA PROACTIVA', title:'El impacto detrás de cada señal.', subtitle:'Identifica clientes en riesgo y la siguiente mejor intervención antes del reclamo.' },
  voice: { eyebrow:'ESCUCHA ACTIVA', title:'La voz que orienta cada decisión.', subtitle:'Convierte tickets, NPS y SLA en temas explicables, clientes afectados y prioridades accionables.' },
  customer360: { eyebrow:'INTELIGENCIA INDIVIDUAL', title:'Cada cliente, sin puntos ciegos.', subtitle:'Productos, experiencia, NPS, SLA, valor, riesgo y próximas mejores acciones en una vista gobernada.' },
  graph: { eyebrow:'CONEXIONES SIN FRONTERAS', title:'El alcance revela dónde actuar.', subtitle:'Explora contactos calificados, exposición relacional y prioridades de retención sin confundir asociación con causalidad.' },
  campaigns: { eyebrow:'DECISIÓN COMERCIAL', title:'Cada contacto debe tener una razón.', subtitle:'Optimiza audiencias bajo presupuesto, consentimiento, capacidad y servicio antes de venta.' },
  actions: { eyebrow:'HUMANO EN EL CIRCUITO', title:'De recomendación a acción controlada.', subtitle:'Aprueba, rechaza y audita cada intervención propuesta por la operación.' },
  scenarios: { eyebrow:'PLANIFICACIÓN', title:'Anticipa dónde termina la capacidad.', subtitle:'Simula crecimiento, redistribución de tráfico e inversión por mercado.' },
  intelligence: { eyebrow:'GENIE + QUETZAL IQ', title:'Investiga con evidencia.', subtitle:'Pregunta, profundiza y conserva la distinción entre datos internos e inferencias.' },
  governance: { eyebrow:'CONFIANZA OPERATIVA', title:'Toda métrica debe poder explicarse.', subtitle:'Frescura, definición, linaje, auditoría y reglas personales en un solo lugar.' },
}

function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)
  useEffect(() => {
    let live = true
    setLoading(true); setError('')
    loader().then(value => { if (live) setData(value) }).catch(err => { if (live) setError(err.message) }).finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [...deps, nonce]) // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error, loading, refresh: () => setNonce(n => n + 1) }
}

function QuetzalMark({ compact=false }: {compact?:boolean}) {
  return <div className={`brand ${compact ? 'compact' : ''}`} aria-label="Quetzal">
    <svg viewBox="-20 -20 230 340" className="brand-mark" role="img" aria-label="Ave Quetzal">
      <path d="M95 140C95 180 85 240 80 290C78 310 90 310 92 290C97 240 100 180 100 140Z" fill="#009B6D" opacity=".92"/>
      <path d="M80 135C65 175 40 235 25 280C20 295 32 298 37 283C52 238 72 178 85 138Z" fill="#007A5A" opacity=".68"/>
      <path d="M110 135C125 175 150 235 165 280C170 295 158 298 153 283C138 238 118 178 105 138Z" fill="#007A5A" opacity=".68"/>
      <ellipse cx="95" cy="95" rx="42" ry="55" fill="#008C65"/>
      <ellipse cx="95" cy="110" rx="25" ry="30" fill="#E85D5D"/>
      <path d="M70 70C20 40-10 60 5 95C15 115 40 120 60 108Z" fill="#005342"/>
      <path d="M120 70C170 40 200 60 185 95C175 115 150 120 130 108Z" fill="#005342"/>
      <circle cx="95" cy="42" r="28" fill="#00634D"/>
      <path d="M85 18C82 5 78-5 80-12M95 15C95 2 95-8 97-15M105 18C108 5 112-5 110-12" stroke="#18D49A" strokeWidth="3" strokeLinecap="round"/>
      <circle cx="104" cy="38" r="7" fill="#FFF"/><circle cx="105.5" cy="37" r="3.5" fill="#12201D"/><circle cx="107" cy="35.5" r="1.2" fill="#FFF"/>
      <path d="M120 42L142 48L120 54Z" fill="#F4C430"/>
    </svg>
    {!compact && <span><strong>QUETZAL</strong><small>CONEXIÓN SIN FRONTERAS</small></span>}
  </div>
}

function App() {
  const [page, setPage] = useState<Page>('command')
  const [customerFocus, setCustomerFocus] = useState('')
  const [incidentFocus, setIncidentFocus] = useState('')
  const [graphFocus, setGraphFocus] = useState('')
  const [campaignSeed, setCampaignSeed] = useState<CampaignSeed|null>(null)
  const [campaignDraft, setCampaignDraft] = useState<any>(null)
  const [dark, setDark] = useState(() => localStorage.getItem('quetzal-theme') !== 'light')
  const [mobileOpen, setMobileOpen] = useState(false)
  const operator = useAsync<any>(() => api('/api/me'), [])
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('quetzal-theme', dark ? 'dark' : 'light')
  }, [dark])
  useEffect(() => { window.scrollTo({top:0, behavior:'auto'}) }, [page])
  function openNewCampaign(seed:CampaignSeed){setCampaignSeed(seed);setCampaignDraft(null);setPage('campaigns')}
  if (operator.loading) return <div className="app-shell"><main className="main"><div className="state-box"><RefreshCw className="spin"/>Validando identidad y alcance…</div></main></div>
  if (operator.error || !operator.data?.roles?.length) return <div className="app-shell"><main className="main"><div className="state-box error"><ShieldCheck/><span><b>Acceso operativo no autorizado.</b><small>{operator.error || 'Tu identidad no tiene un rol activo en Quetzal.'}</small></span></div></main></div>
  const effectiveCountries:string[]=operator.data.country_scope||[]
  const scopeLabel=effectiveCountries.includes('ALL')?'12 mercados · una red':`${effectiveCountries.join(' · ')} · alcance autorizado`
  const meta = PAGE_META[page]
  let lastGroup = ''
  return <div className="app-shell">
    <aside className={`sidebar ${mobileOpen ? 'open' : ''}`}>
      <div className="sidebar-top"><QuetzalMark/><button className="icon-button close-menu" aria-label="Cerrar menú principal" onClick={() => setMobileOpen(false)}><X/></button></div>
      <nav aria-label="Navegación principal">
        {NAV.map(item => {
          const group = item.group !== lastGroup ? item.group : ''
          lastGroup = item.group
          const Icon = item.icon
          return <div key={item.id}>
            {group && <div className="nav-group">{group}</div>}
            <button className={`nav-link ${page === item.id ? 'active' : ''}`} onClick={() => {setPage(item.id);setMobileOpen(false)}}>
              <Icon/><span>{item.label}</span>{page === item.id && <ArrowRight className="nav-arrow"/>}
            </button>
          </div>
        })}
      </nav>
      <div className="sidebar-foot">
        <div className="freedom-note"><Route/><span><b>Vuela sin límites</b><small>Una red. Todo un continente.</small></span></div>
        <button className="theme-button" onClick={() => setDark(x => !x)}>{dark ? <Sun/> : <Moon/>}<span>{dark ? 'Modo claro' : 'Modo oscuro'}</span></button>
      </div>
    </aside>
    {mobileOpen && <button className="backdrop" onClick={() => setMobileOpen(false)} aria-label="Cerrar menú"/>}
    <main className="main">
      <header className="topbar">
        <button className="icon-button menu-button" aria-label="Abrir menú principal" onClick={() => setMobileOpen(true)}><Menu/></button>
        <div className="scope"><Globe2/><span><small>ALCANCE AUTORIZADO</small><b>{scopeLabel}</b></span></div>
        <div className="topbar-actions">
          <span className="connected"><i/>Datos conectados</span>
          <div className="operator"><span>{operator.data?.display_name || 'Operador Quetzal'}</span><div>{(operator.data?.display_name || 'Q').slice(0,2).toUpperCase()}</div></div>
        </div>
      </header>
      <section className="page-shell">
        <div className="page-heading"><div><span className="eyebrow">{meta.eyebrow}</span><h1>{meta.title}</h1><p>{meta.subtitle}</p></div><div className="heading-mark"><Network/><span>LIVE OPERATIONS</span></div></div>
        {page === 'command' && <CommandPage navigate={setPage}/>} 
        {page === 'journey' && <DemoJourneyPage campaignDraft={campaignDraft} navigate={setPage} openIncident={incidentId=>{setIncidentFocus(incidentId);setPage('incidents')}} openCustomer={customerId=>{setCustomerFocus(customerId);setPage('customer360')}} openGraph={communityId=>{setGraphFocus(communityId);setPage('graph')}} openCampaign={openNewCampaign} onReset={()=>{setCustomerFocus('');setIncidentFocus('');setGraphFocus('');setCampaignSeed(null);setCampaignDraft(null)}}/>}
        {page === 'analytics' && <AnalyticsPage/>}
        {page === 'incidents' && <IncidentsPage initialIncident={incidentFocus}/>}
        {page === 'network' && <NetworkPage/>}
        {page === 'customers' && <CustomersPage navigate={setPage} openCustomer={customerId=>{setCustomerFocus(customerId);setPage('customer360')}}/>} 
        {page === 'voice' && <VoiceOfCustomerPage openCustomer={customerId=>{setCustomerFocus(customerId);setPage('customer360')}} openCampaign={openNewCampaign}/>}
        {page === 'customer360' && <Customer360Page initialCustomer={customerFocus} openGraph={()=>setPage('graph')}/>} 
        {page === 'graph' && <GraphExplorerPage initialCommunity={graphFocus} canRun={operator.data?.roles?.includes('ADMIN') === true} openCustomer={customerId=>{setCustomerFocus(customerId);setPage('customer360')}} openCampaign={openNewCampaign}/>}
        {page === 'campaigns' && <CampaignOptimizerPage seed={campaignSeed} initialDraft={campaignDraft} onDraft={setCampaignDraft} actor={operator.data?.actor || operator.data?.email || ''} roles={operator.data?.roles || []} openCustomer={customerId=>{setCustomerFocus(customerId);setPage('customer360')}}/>}
        {page === 'actions' && <ActionsPage/>}
        {page === 'scenarios' && <ScenariosPage/>}
        {page === 'intelligence' && <IntelligencePage/>}
        {page === 'governance' && <GovernancePage/>}
      </section>
    </main>
  </div>
}

function State({loading,error,children}: {loading:boolean;error:string;children:ReactNode}) {
  if (loading) return <div className="state-box"><RefreshCw className="spin"/>Conectando señales…</div>
  if (error) return <div className="state-box error"><AlertTriangle/><span><b>No fue posible cargar esta señal.</b><small>{error}</small></span></div>
  return <>{children}</>
}

function Metric({label,value,detail,tone='green',icon}: {label:string;value:string;detail:string;tone?:string;icon?:ReactNode}) {
  return <article className={`metric tone-${tone}`}><div className="metric-label">{icon}<span>{label}</span></div><strong>{value}</strong><small>{detail}</small><div className="metric-line"/></article>
}

function Severity({value}: {value:string}) { return <span className={`severity ${value?.toLowerCase()}`}>{value}</span> }

function CommandPage({navigate}: {navigate:(page:Page)=>void}) {
  const state = useAsync<any>(async () => {
    const [command,kpis,freshness,revenue] = await Promise.all([
      api('/api/command/summary'), api('/api/kpis'), api('/api/operations/freshness'), api('/api/charts/revenue-by-country'),
    ])
    return {command,kpis,freshness,revenue}
  }, [])
  return <State loading={state.loading} error={state.error}><div className="stack-xl">
    <section className="hero-grid">
      <div className="hero panel-dark">
        <div className="hero-copy"><span className="overline"><Zap/>SEÑAL PRIORITARIA</span><h2>El horizonte<br/><em>no tiene fronteras.</em></h2><p>Quetzal conecta red, clientes y decisiones para actuar antes del impacto.</p><div className="hero-actions"><button className="primary light" onClick={()=>navigate('journey')}>Iniciar ruta de decisión <ArrowRight/></button><button className="ghost" onClick={()=>navigate('intelligence')}>Investigar con IQ</button></div></div>
        <ReachGraphic/>
      </div>
      <div className="priority-card panel">
        <span className="overline danger"><AlertTriangle/>PRIORIDAD AHORA</span>
        <strong>{state.data?.command.totals.critical_incidents || 0} incidentes críticos</strong>
        <p>{number(state.data?.command.totals.affected_customers, true)} clientes conectados a infraestructura con anomalía.</p>
        <div className="impact-value"><span>Valor mensual en riesgo</span><b>{money(state.data?.command.totals.revenue_at_risk)}</b></div>
        <button className="text-button" onClick={()=>navigate('incidents')}>Abrir centro de incidentes <ArrowRight/></button>
      </div>
    </section>
    <section className="metrics-row">
      <Metric label="Ingresos 12M" value={money(state.data?.kpis.revenue.total_revenue)} detail={`Cierre ${state.data?.kpis.revenue.revenue_period_end || '—'}`} icon={<TrendingUp/>}/>
      <Metric label="Clientes activos" value={number(state.data?.kpis.subscribers.active_subscribers,true)} detail={`Churn ${number(state.data?.kpis.subscribers.churn_rate)}%`} icon={<UsersRound/>}/>
      <Metric label="Salud de red" value={`${number(state.data?.kpis.network.health_score)}%`} detail="Mediciones sin alerta · no es uptime" tone="blue" icon={<Activity/>}/>
      <Metric label="Acciones pendientes" value={number(state.data?.command.totals.pending_actions)} detail="Requieren aprobación humana" tone="amber" icon={<ClipboardCheck/>}/>
    </section>
    <section className="two-one-grid">
      <div className="panel"><PanelHead kicker="DECISIÓN" title="Incidentes prioritarios" action={<button className="text-button" onClick={()=>navigate('incidents')}>Ver todos <ArrowRight/></button>}/><div className="incident-list">
        {(state.data?.command.incidents || []).map((item:any) => <button className="incident-row" key={item.incident_id} onClick={()=>navigate('incidents')}><Severity value={item.severity}/><span className="incident-main"><b>{item.title}</b><small>{FLAGS[item.country]} {item.country} · {number(item.affected_customers)} clientes · {item.probable_cause}</small></span><strong>{money(item.revenue_at_risk)}</strong><ArrowRight/></button>)}
      </div></div>
      <div className="panel"><PanelHead kicker="ALCANCE" title="Valor por mercado"/><BarList rows={state.data?.revenue || []} label="pais_codigo" value="ingresos" format={money}/></div>
    </section>
    <FreshnessStrip rows={state.data?.freshness.sources || []}/>
  </div></State>
}

function AnalyticsPage() {
  const config = useAsync<any>(() => api('/api/config'), [])
  const [loaded, setLoaded] = useState(false)
  return <State loading={config.loading} error={config.error}>
    <section className="dashboard-panel panel">
      <div className="dashboard-toolbar">
        <div><span className="overline"><LayoutDashboard/>DATAVIZ INTERACTIVA</span><strong>Quetzal · desempeño regional</strong><small>Filtros, drill-down y métricas certificados por Databricks AI/BI.</small></div>
        {config.data?.dashboard_url && <a className="secondary dashboard-open" href={config.data.dashboard_url} target="_blank" rel="noreferrer">Abrir en AI/BI <ExternalLink/></a>}
      </div>
      {config.data?.dashboard_url
        ? <div className="dashboard-embed-wrap">{!loaded&&<div className="dashboard-loading"><RefreshCw className="spin"/><span><b>Conectando con Databricks AI/BI</b><small>Cargando visualizaciones y filtros gobernados…</small></span></div>}<iframe className="dashboard-frame" src={config.data.dashboard_url} title="Dashboard Quetzal AI/BI" onLoad={()=>setLoaded(true)} allowFullScreen/></div>
        : <Empty icon={<LayoutDashboard/>} title={config.data?.scope?.territorial_upstreams_enabled===false?'Dashboard restringido por alcance':'Dashboard no configurado'} text={config.data?.scope?.territorial_upstreams_enabled===false?'La analítica global usa la identidad del App y permanece bloqueada hasta contar con filtros territoriales verificables.':'Define QUETZAL_DASHBOARD_ID para habilitar la analítica embebida.'}/>}
    </section>
  </State>
}

function ReachGraphic() { return <div className="reach-graphic" aria-hidden="true"><div className="reach-orbit o1"/><div className="reach-orbit o2"/><div className="reach-orbit o3"/><div className="bird-path"><span/><span/><span/><span/><span/></div><svg viewBox="0 0 420 240"><path d="M18 210 C95 190 112 120 185 132 S285 62 403 28"/><path d="M18 228 C120 205 205 168 403 116"/><path d="M18 186 C86 156 164 199 237 100 S334 58 403 52"/></svg><div className="reach-stat"><b>12</b><span>MERCADOS<br/>CONECTADOS</span></div></div> }

function PanelHead({kicker,title,action}: {kicker:string;title:string;action?:ReactNode}) { return <div className="panel-head"><div><span>{kicker}</span><h3>{title}</h3></div>{action}</div> }

function BarList({rows,label,value,format}: {rows:any[];label:string;value:string;format:(v:any)=>string}) {
  const max = Math.max(...rows.map(r=>Number(r[value]||0)),1)
  return <div className="bar-list">{rows.slice(0,8).map((row,i)=><div className="bar-row" key={`${row[label]}-${i}`}><span>{FLAGS[row[label]]} {row[label]}</span><div><i style={{width:`${Math.max(4,Number(row[value])/max*100)}%`}}/></div><b>{format(row[value])}</b></div>)}</div>
}

function FreshnessStrip({rows}: {rows:any[]}) { return <div className="freshness-strip"><div><Database/><span><b>Confianza de datos</b><small>Estado por dominio</small></span></div>{rows.map(row=><span className={`freshness ${String(row.status).toLowerCase()}`} key={row.domain}><i/>{row.domain}<small>{number(row.lag_hours)}h</small></span>)}</div> }

function IncidentsPage({initialIncident=''}:{initialIncident?:string}) {
  const [severity,setSeverity]=useState('ALL'); const [country,setCountry]=useState('ALL'); const [selected,setSelected]=useState<string|null>(null)
  useEffect(()=>{if(initialIncident)setSelected(initialIncident)},[initialIncident])
  const query = new URLSearchParams(); if(severity!=='ALL')query.set('severity',severity);if(country!=='ALL')query.set('country',country)
  const state=useAsync<any[]>(()=>api(`/api/incidents?${query}`),[severity,country])
  return <><div className="toolbar"><div className="filter"><Search/><span>Filtrar</span></div><Select value={severity} onChange={setSeverity} options={['ALL','CRITICAL','HIGH','MEDIUM']}/><Select value={country} onChange={setCountry} options={COUNTRIES}/><button className="icon-button" onClick={state.refresh}><RefreshCw/></button></div>
    <State loading={state.loading} error={state.error}><div className="incident-board">
      <div className="board-head"><span>INCIDENTE</span><span>IMPACTO</span><span>CAUSA PROBABLE</span><span>RESPUESTA</span></div>
      {(state.data||[]).map(item=><button className="board-row" key={item.incident_id} onClick={()=>setSelected(item.incident_id)}><div><Severity value={item.severity}/><span><b>{item.title}</b><small>{item.incident_id} · {dateTime(item.detected_at)}</small></span></div><div><strong>{number(item.affected_customers)} clientes</strong><small>{money(item.revenue_at_risk)} en riesgo</small></div><div><strong>{item.probable_cause}</strong><small>{number(Number(item.cause_confidence)*100)}% confianza</small></div><div><span className="status-pill">{item.status}</span><small className={`sla-state ${String(item.sla_status).toLowerCase()}`}>SLA {item.sla_status} · {number(item.sla_remaining_hours)}h</small></div><ArrowRight/></button>)}
    </div></State>{selected&&<IncidentDrawer id={selected} close={()=>setSelected(null)} changed={state.refresh}/>}</>
}

function IncidentDrawer({id,close,changed}: {id:string;close:()=>void;changed:()=>void}) {
  const state=useAsync<any>(()=>api(`/api/incidents/${id}`),[id]); const [busy,setBusy]=useState(false); const [message,setMessage]=useState('')
  async function updateStatus(status:string){setBusy(true);try{await patch(`/api/incidents/${id}`,{status});setMessage(`Estado actualizado a ${status}`);state.refresh();changed()}catch(e:any){setMessage(e.message)}finally{setBusy(false)}}
  async function createAction(type:string){setBusy(true);try{await post(`/api/incidents/${id}/actions`,{action_type:type,rationale:`Respuesta recomendada para ${state.data?.title}`});setMessage('Acción enviada para aprobación.');state.refresh()}catch(e:any){setMessage(e.message)}finally{setBusy(false)}}
  const item=state.data
  return <div className="drawer-wrap"><button className="backdrop" onClick={close}/><aside className="drawer"><div className="drawer-head"><div><span>{id}</span><h2>{item?.title||'Cargando incidente'}</h2></div><button className="icon-button" onClick={close}><X/></button></div><State loading={state.loading} error={state.error}>{item&&<div className="drawer-content">
    <div className="drawer-summary"><Severity value={item.severity}/><span className="status-pill">{item.status}</span><span>{FLAGS[item.country]} {item.city}</span><span>{item.tower_id}</span></div>
    <div className="drawer-metrics"><Metric label="Clientes afectados" value={number(item.affected_customers)} detail="Conectados a la torre"/><Metric label="Valor en riesgo" value={money(item.revenue_at_risk)} detail="Estimación mensual" tone="amber"/><Metric label="Confianza RCA" value={`${number(Number(item.root_cause.confidence)*100)}%`} detail={item.root_cause.label} tone="blue"/></div>
    <div className={`sla-clock ${String(item.sla_status).toLowerCase()}`}><Clock3/><span><b>SLA operacional · {item.sla_status}</b><small>Objetivo {item.sla_target_hours}h · vence {dateTime(item.sla_deadline_at)} · {number(item.sla_remaining_hours)}h restantes</small></span></div>
    <section><h3>Causa raíz probable</h3><div className="cause-card"><BrainCircuit/><div><b>{item.root_cause.label}</b><p>Hipótesis generada por correlación de telemetría, anomalías y presión de tickets.</p></div></div><div className="evidence-grid">{item.root_cause.evidence.map((e:any)=><div key={e.metric}><span>{e.metric}</span><b>{number(e.value)}</b></div>)}</div></section>
    <section><h3>Flujo de respuesta</h3><div className="status-actions">{['ACKNOWLEDGED','IN_PROGRESS','MONITORING','RESOLVED'].map(s=><button disabled={busy||item.status===s} onClick={()=>updateStatus(s)} key={s}>{s}</button>)}</div></section>
    <section><h3>Acciones recomendadas</h3><div className="recommendations">{item.recommended_actions.map((a:any)=><button disabled={busy} key={a.type} onClick={()=>createAction(a.type)}><span><b>{a.label}</b><small><ShieldCheck/> Requiere aprobación</small></span><ArrowRight/></button>)}</div></section>
    <section><h3>Línea de tiempo</h3><div className="timeline">{item.timeline.map((event:any,i:number)=><div key={i}><i/><span><b>{event.label}</b><small>{dateTime(event.at)}</small></span></div>)}</div></section>
    {message&&<div className="toast-inline">{message}</div>}
  </div>}</State></aside></div>
}

function Select({value,onChange,options}: {value:string;onChange:(v:string)=>void;options:string[]}) { return <label className="select"><select value={value} onChange={e=>onChange(e.target.value)}>{options.map(x=><option value={x} key={x}>{x==='ALL'?'Todos':`${FLAGS[x]||''} ${x}`}</option>)}</select><ChevronDown/></label> }

function NetworkPage() {
  const [country,setCountry]=useState(''); const [city,setCity]=useState('');const[selectedTower,setSelectedTower]=useState<any>(null)
  const path=new URLSearchParams();if(country)path.set('country',country);if(city)path.set('city',city)
  const state=useAsync<any>(()=>api(`/api/network/topology?${path}`),[country,city])
  const cities=(state.data?.cities||[]).filter((x:any)=>!country||x.country===country);const cityOptions=['',...new Set(cities.map((x:any)=>x.city))] as string[]
  const towers=state.data?.towers||[]
  const healthy=(tower:any)=>['sin alerta','normal','ok','false','0'].includes(String(tower.alert).toLowerCase())
  const summary=useMemo(()=>{
    const total=towers.length||1
    return{towers:towers.length,alerts:towers.filter((tower:any)=>!healthy(tower)).length,customers:towers.reduce((sum:number,tower:any)=>sum+Number(tower.connected_customers||0),0),capacity:towers.reduce((sum:number,tower:any)=>sum+Number(tower.capacity_pct||0),0)/total,latency:towers.reduce((sum:number,tower:any)=>sum+Number(tower.latency_ms||0),0)/total,asOf:towers[0]?.as_of}
  },[towers])
  useEffect(()=>setSelectedTower(null),[country,city])
  const selectCity=(value:string)=>{setCity(value);setSelectedTower(null)}
  return <><div className="topology-path"><button className={!country?'active':''} onClick={()=>{setCountry('');setCity('')}}><Globe2/>LATAM</button>{country&&<><ArrowRight/><button className={!city?'active':''} onClick={()=>setCity('')}>{FLAGS[country]} {country}</button></>}{city&&<><ArrowRight/><button className="active"><MapPin/>{city}</button></>}</div>
  <State loading={state.loading} error={state.error}><div className="stack-lg">
    {!country&&<div className="country-grid">{(state.data?.countries||[]).map((item:any)=><button className="country-card" key={item.country} onClick={()=>{setCountry(item.country);setCity('')}}><div><span>{FLAGS[item.country]}</span><b>{item.country}</b><Severity value={Number(item.health_score)<39?'HIGH':'MEDIUM'}/></div><strong>{number(item.health_score)}%</strong><small>salud de mediciones</small><div className="country-stats"><span><Activity/>{number(item.latency_ms)} ms</span><span><Gauge/>{number(item.capacity_pct)}%</span><span><AlertTriangle/>{number(item.towers_alert)}</span></div></button>)}</div>}
    {country&&<><section className="network-kpis"><article><RadioTower/><span><small>Infraestructura visible</small><b>{number(summary.towers)} torres</b></span></article><article className={summary.alerts?'attention':''}><AlertTriangle/><span><small>Requieren atención</small><b>{number(summary.alerts)} alertas</b></span></article><article><Gauge/><span><small>Capacidad media</small><b>{number(summary.capacity)}%</b></span></article><article><UsersRound/><span><small>Clientes conectados</small><b>{number(summary.customers,true)}</b></span></article></section><section className="network-layout"><div className="panel signal-map"><PanelHead kicker={city?'NIVEL TORRE':'NIVEL CIUDAD'} title={`${FLAGS[country]} ${country}${city?` · ${city}`:''}`}/><SignalMap towers={towers} city={city} onCitySelect={selectCity} onTowerSelect={setSelectedTower}/>{selectedTower&&<TowerFocus tower={selectedTower} close={()=>setSelectedTower(null)}/>}</div><div className="panel city-pressure"><PanelHead kicker="CIUDADES" title="Presión operacional"/><label className="field compact-field"><span>Enfoque geográfico</span><select value={city} onChange={e=>selectCity(e.target.value)}>{cityOptions.map(x=><option value={x} key={x}>{x||'Todas las ciudades'}</option>)}</select></label><div className="city-list">{cities.slice(0,12).map((item:any)=>{const attention=Number(item.towers_alert),total=Number(item.towers)||1;return <button className={city===item.city?'active':''} onClick={()=>selectCity(item.city)} key={`${item.country}-${item.city}`}><div className="city-name"><span><b>{item.city}</b><small>{item.towers} torres · {number(item.health_score)}% saludables</small></span><strong>{number(item.capacity_pct)}%<small>capacidad</small></strong></div><div className="city-health"><i style={{width:`${Math.max(3,Number(item.health_score))}%`}}/><span className={attention?'attention':''}>{attention}/{total} alertas</span></div></button>})}</div><div className="network-snapshot"><Clock3/><span><small>Último snapshot</small><b>{dateTime(summary.asOf)}</b></span></div></div></section><TowerTable rows={towers}/></>}
    <div className="semantic-note"><ShieldCheck/><span><b>Definición gobernada</b><small>Salud de red = porcentaje de mediciones sin alerta. No representa disponibilidad contractual ni SLA.</small></span></div>
  </div></State></>
}

function SignalMap({towers,city,onCitySelect,onTowerSelect}:{towers:any[];city:string;onCitySelect:(city:string)=>void;onTowerSelect:(tower:any)=>void}){
  const healthy=(tower:any)=>['sin alerta','normal','ok','false','0'].includes(String(tower.alert).toLowerCase())
  const located=towers.filter((tower:any)=>Number.isFinite(Number(tower.latitude))&&Number.isFinite(Number(tower.longitude)))
  const cityGroups=Object.values(located.reduce((groups:Record<string,any>,tower:any)=>{const key=String(tower.city||'Sin ciudad');const group=groups[key]||{kind:'city',id:key,city:key,latitude:0,longitude:0,towers:0,alerts:0,capacity:0,customers:0};group.latitude+=Number(tower.latitude);group.longitude+=Number(tower.longitude);group.capacity+=Number(tower.capacity_pct||0);group.customers+=Number(tower.connected_customers||0);group.towers++;if(!healthy(tower))group.alerts++;groups[key]=group;return groups},{})).map((group:any)=>({...group,latitude:group.latitude/group.towers,longitude:group.longitude/group.towers,capacity:group.capacity/group.towers}))
  const rawNodes:any[]=city?located.slice(0,80):cityGroups
  const lats=rawNodes.map(node=>Number(node.latitude)),lons=rawNodes.map(node=>Number(node.longitude));const minLat=Math.min(...lats),maxLat=Math.max(...lats),minLon=Math.min(...lons),maxLon=Math.max(...lons);const latSpan=Math.max(maxLat-minLat,.01),lonSpan=Math.max(maxLon-minLon,.01)
  const nodes=rawNodes.map((node,index)=>{const jitterX=((index%5)-2)*.15,jitterY=((index%7)-3)*.12;return{...node,x:10+((Number(node.longitude)-minLon)/lonSpan)*80+jitterX,y:88-((Number(node.latitude)-minLat)/latSpan)*76+jitterY}})
  const center=nodes.length?{x:nodes.reduce((sum,node)=>sum+node.x,0)/nodes.length,y:nodes.reduce((sum,node)=>sum+node.y,0)/nodes.length}:{x:50,y:50}
  const [hovered,setHovered]=useState<any>(null)
  return <div className="signal-map-area"><div className="map-grid"/><div className="map-atmosphere a"/><div className="map-atmosphere b"/><div className="map-context"><span>{city?'DISTRIBUCIÓN LOCAL':'BACKBONE REGIONAL'}</span><b>{city?`${nodes.length} torres mapeadas`:`${nodes.length} ciudades conectadas`}</b><small>Coordenadas normalizadas al área seleccionada</small></div><svg className="backbone-lines" viewBox="0 0 100 100" preserveAspectRatio="none">{!city&&nodes.map(node=><line key={node.id} x1={center.x} y1={center.y} x2={node.x} y2={node.y}/>)}<circle cx={center.x} cy={center.y} r="14"/></svg>{nodes.map((node,index)=>{const ok=node.kind==='city'?node.alerts===0:healthy(node);const size=node.kind==='city'?Math.min(44,24+Number(node.towers)*.25):Math.min(17,8+Math.sqrt(Number(node.connected_customers||0))/18);return <button type="button" className={`map-node ${node.kind==='city'?'cluster':'tower'} ${ok?'ok':'alert'}`} style={{left:`${node.x}%`,top:`${node.y}%`,width:size,height:size}} key={node.id||node.torre_id||index} onMouseEnter={()=>setHovered(node)} onMouseLeave={()=>setHovered(null)} onFocus={()=>setHovered(node)} onBlur={()=>setHovered(null)} onClick={()=>node.kind==='city'?onCitySelect(node.city):onTowerSelect(node)} aria-label={node.kind==='city'?`Abrir ${node.city}, ${node.alerts} alertas`:`Inspeccionar ${node.torre_id}`}><i/>{node.kind==='city'&&<span>{node.city}</span>}</button>})}{hovered&&<div className="map-tooltip" style={{left:`${Math.min(82,Math.max(18,hovered.x))}%`,top:`${Math.max(22,hovered.y-4)}%`}}><small>{hovered.kind==='city'?'CLUSTER DE CIUDAD':hovered.technology||'TORRE'}</small><strong>{hovered.kind==='city'?hovered.city:hovered.torre_id}</strong><div><span><b>{hovered.kind==='city'?hovered.towers:number(hovered.connected_customers,true)}</b><small>{hovered.kind==='city'?'torres':'clientes'}</small></span><span><b>{number(hovered.capacity_pct??hovered.capacity)}%</b><small>capacidad</small></span><span><b>{hovered.kind==='city'?hovered.alerts:number(hovered.latency_ms)}</b><small>{hovered.kind==='city'?'alertas':'ms latência'}</small></span></div><em>{hovered.kind==='city'?'Clique para entrar na cidade':'Clique para abrir os detalhes'}</em></div>}<div className="map-compass"><i>N</i><span/></div><div className="map-legend"><span><i className="ok"/>Normal</span><span><i className="alert"/>Atención</span><span className="map-level">{city?'● torre':'● ciudad'}</span></div>{!nodes.length&&<div className="empty-map"><RadioTower/><span>No hay coordenadas disponibles para esta selección.</span></div>}</div>
}

function TowerFocus({tower,close}:{tower:any;close:()=>void}){const ok=['sin alerta','normal','ok','false','0'].includes(String(tower.alert).toLowerCase());return <div className="tower-focus"><div className="tower-focus-head"><span className={`tower-status ${ok?'ok':'alert'}`}><i/>{ok?'Operación normal':'Requiere atención'}</span><button onClick={close} aria-label="Cerrar detalle"><X/></button></div><div className="tower-focus-title"><RadioTower/><span><small>{tower.technology} · {tower.city}</small><b>{tower.torre_id}</b></span></div><div className="tower-focus-metrics"><span><small>Capacidad</small><b>{number(tower.capacity_pct)}%</b></span><span><small>Latencia</small><b>{number(tower.latency_ms)} ms</b></span><span><small>Packet loss</small><b>{number(tower.packet_loss_pct)}%</b></span><span><small>Clientes</small><b>{number(tower.connected_customers,true)}</b></span></div><p>{String(tower.alert).replaceAll('_',' ')}</p></div>}

function TowerTable({rows}: {rows:any[]}) {return <div className="panel table-panel"><PanelHead kicker="INFRAESTRUCTURA" title="Torres y calidad de servicio"/><div className="table-scroll"><table><thead><tr><th>Torre</th><th>Ciudad</th><th>Tecnología</th><th>Clientes</th><th>Capacidad</th><th>Latencia</th><th>Packet loss</th><th>Estado</th></tr></thead><tbody>{rows.map(row=><tr key={row.torre_id}><td><b>{row.torre_id}</b></td><td>{row.city}</td><td>{row.technology}</td><td>{number(row.connected_customers)}</td><td>{number(row.capacity_pct)}%</td><td>{number(row.latency_ms)} ms</td><td>{number(row.packet_loss_pct)}%</td><td><span className={`health-dot ${String(row.alert).toLowerCase().includes('sin')?'ok':'alert'}`}/>{row.alert}</td></tr>)}</tbody></table></div></div>}

const CARE_ACTION_LABELS:Record<string,string>={RETENTION_SPECIALIST:'Especialista de retención',PAYMENT_PLAN:'Plan de pago',SERVICE_RECOVERY:'Recuperación de servicio',PROACTIVE_CONTACT:'Contacto proactivo'}

function CustomersPage({navigate,openCustomer}: {navigate:(p:Page)=>void;openCustomer:(customerId:string)=>void}) {
  const [country,setCountry]=useState('ALL');const qs=country==='ALL'?'':`?country=${country}`
  const state=useAsync<any>(async()=>{const [impact,care]=await Promise.all([api(`/api/customer-impact${qs}`),api(`/api/proactive-care${qs}`)]);return{impact,care}},[country])
  const totals=useMemo(()=>(state.data?.impact.countries||[]).reduce((a:any,x:any)=>({customers:a.customers+Number(x.customers_scored||0),risk:a.risk+Number(x.high_risk_customers||0),value:a.value+Number(x.monthly_revenue_at_risk||0),detractors:a.detractors+Number(x.detractors||0)}),{customers:0,risk:0,value:0,detractors:0}),[state.data])
  return <><div className="toolbar"><Select value={country} onChange={setCountry} options={COUNTRIES}/><button className="secondary" onClick={()=>navigate('actions')}><ClipboardCheck/>Abrir acciones</button></div><State loading={state.loading} error={state.error}><div className="stack-lg"><div className="metrics-row"><Metric label="Clientes evaluados" value={number(totals.customers,true)} detail="Último scoring de churn"/><Metric label="Alto riesgo" value={number(totals.risk,true)} detail="Priorización proactiva" tone="amber"/><Metric label="Valor mensual expuesto" value={money(totals.value)} detail="Clientes de alto riesgo" tone="red"/><Metric label="Detractores" value={number(totals.detractors,true)} detail="NPS entre 0 y 6" tone="blue"/></div><section className="two-one-grid"><div className="panel"><PanelHead kicker="CUIDADO PROACTIVO" title="Próximas mejores intervenciones"/><div className="care-list">{(state.data?.care||[]).map((item:any)=><div key={item.customer_id||item.customer_ref}><span className="customer-avatar"><UserRound/></span><span><b>{item.customer_ref}</b><small>{FLAGS[item.country]} {item.segment} · {item.total_tickets} tickets</small></span><div className="risk-meter"><i style={{width:`${Number(item.churn_probability)*100}%`}}/><small>{number(Number(item.churn_probability)*100)}% churn</small></div><strong>{CARE_ACTION_LABELS[item.recommended_action]||item.recommended_action.replaceAll('_',' ')}</strong><button className="icon-button" title="Abrir Cliente 360" aria-label={`Abrir Cliente 360 de ${item.customer_ref}`} onClick={()=>openCustomer(item.customer_id)}><ArrowRight/></button></div>)}</div></div><div className="panel"><PanelHead kicker="MERCADOS" title="Valor en riesgo"/><BarList rows={state.data?.impact.countries||[]} label="country" value="monthly_revenue_at_risk" format={money}/></div></section></div></State></>
}

function Customer360Page({initialCustomer='',openGraph}:{initialCustomer?:string;openGraph:()=>void}){
  const initialQuery=initialCustomer||'CLI-0000'
  const [query,setQuery]=useState(initialQuery)
  const [submitted,setSubmitted]=useState(initialQuery)
  const [country,setCountry]=useState('ALL')
  const [selected,setSelected]=useState(initialCustomer)
  const [decisionBusy,setDecisionBusy]=useState('');const [decisionMessage,setDecisionMessage]=useState('');const [caseBusy,setCaseBusy]=useState('')
  const search=useAsync<any[]>(()=>api(`/api/customers/search?q=${encodeURIComponent(submitted)}${country==='ALL'?'':`&country=${country}`}`),[submitted,country])
  useEffect(()=>{if(search.data?.length&&!selected)setSelected(search.data[0].cliente_id)},[search.data,selected])
  const detail=useAsync<any>(()=>selected?api(`/api/customers/${selected}/360`):Promise.resolve(null),[selected])
  useEffect(()=>{if(initialCustomer){setQuery(initialCustomer);setSubmitted(initialCustomer);setSelected(initialCustomer)}},[initialCustomer])
  function submit(e:FormEvent){e.preventDefault();if(query.trim().length>=2){setSelected('');setSubmitted(query.trim())}}
  async function decideRecommendation(item:any,decision:'ACCEPTED'|'REJECTED'){
    const key=`${item.type||item.recommendation_type}-${item.product?.plan_id||item.plan_id||''}`;setDecisionBusy(key);setDecisionMessage('')
    try{await post(`/api/customers/${selected}/recommendations`,{recommendation_type:item.type||item.recommendation_type,title:item.title||item.product_name,reason:item.reason,decision,product_id:item.product?.plan_id||item.plan_id||null,score:item.recommendation_score??null,note:'Decisión desde Cliente 360'});setDecisionMessage(`Recomendación ${decision==='ACCEPTED'?'aceptada':'rechazada'} y registrada.`);detail.refresh()}catch(e:any){setDecisionMessage(e.message)}finally{setDecisionBusy('')}
  }
  async function recordOutcome(id:string,outcome:'EXECUTED'|'CONVERTED'|'NO_OUTCOME'){setDecisionBusy(id);try{await post(`/api/recommendations/${id}/outcome`,{outcome,note:'Resultado registrado desde Cliente 360'});detail.refresh()}catch(e:any){setDecisionMessage(e.message)}finally{setDecisionBusy('')}}
  async function createRetentionCase(item:any){
    const key=`${item.type||item.recommendation_type}-${item.title||item.product_name}`;setCaseBusy(key);setDecisionMessage('')
    try{
      await postIdempotent(`/api/customers/${selected}/retention-cases`,{
        recommendation_type:item.type||item.recommendation_type||'RETENTION',title:item.title||item.product_name,
        rationale:item.reason||'Intervención recomendada desde Cliente 360',priority:item.priority||'MEDIUM',
        source_recommendation_id:item.recommendation_id||null,note:'Caso creado desde Cliente 360',
      })
      setDecisionMessage('Caso de retención creado y enviado a aprobación.');detail.refresh()
    }catch(e:any){setDecisionMessage(e.message)}finally{setCaseBusy('')}
  }
  const data=detail.data
  const profile=data?.profile
  return <div className="customer360-shell">
    <aside className="customer-finder panel">
      <form onSubmit={submit}><label><Search/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="ID, nombre, email o teléfono"/></label><button className="primary" disabled={query.trim().length<2}>Buscar</button></form>
      <Select value={country} onChange={value=>{setSelected('');setCountry(value)}} options={COUNTRIES}/>
      <div className="customer-results">
        {search.loading&&<div className="mini-loading"><RefreshCw className="spin"/>Buscando clientes</div>}
        {search.error&&<p className="form-error">{search.error}</p>}
        {search.data?.map(item=><button className={selected===item.cliente_id?'active':''} onClick={()=>setSelected(item.cliente_id)} key={item.cliente_id}><span className="customer-avatar"><UserRound/></span><span><b>{item.nombre_completo}</b><small>{item.cliente_id} · {FLAGS[item.pais_codigo]} {item.marca_comercial}</small><i>{item.active_subscriptions} producto(s) · NPS {item.nps_ultimo??'—'}</i></span><strong>{number(Number(item.churn_probability||0)*100)}%<small>churn</small></strong></button>)}
        {!search.loading&&!search.data?.length&&<p className="finder-empty">No encontramos clientes con este criterio.</p>}
      </div>
    </aside>
    <main className="customer-profile">
      {!selected&&<Empty icon={<UserRound/>} title="Selecciona un cliente" text="Busca por identificador, nombre, email o teléfono para abrir la vista 360."/>}
      {selected&&<State loading={detail.loading} error={detail.error}>{profile&&<div className="stack-lg">
        <section className="customer-identity panel"><div className="customer-identity-main"><span className="profile-avatar"><UserRound/></span><div><span className="eyebrow">{profile.cliente_id}</span><h2>{profile.nombre_completo}</h2><p>{FLAGS[profile.pais_codigo]} {profile.pais_codigo} · {profile.marca_comercial} · Cliente desde {profile.fecha_alta}</p></div></div><div className="customer-contact"><span>{profile.email}</span><span>{profile.telefono}</span><span className={`status-pill ${String(profile.estado).toLowerCase()}`}>{profile.estado}</span></div></section>
        <section className="metrics-row customer-kpis"><Metric label="Valor mensual" value={money(profile.monthly_revenue,false)} detail={`${profile.active_subscriptions} suscripciones activas`}/><Metric label="NPS individual" value={profile.nps_ultimo??'—'} detail={Number(profile.nps_ultimo)<=6?'Detractor · requiere cierre de ciclo':'Última respuesta registrada'} tone={Number(profile.nps_ultimo)<=6?'red':'blue'}/><Metric label="Propensión de churn" value={`${number(Number(profile.churn_probability||0)*100)}%`} detail={`${profile.risk_tier||'Sin tier'} · scoring ${profile.churn_scored_at||'—'}`} tone={Number(profile.churn_probability)>=.65?'red':'amber'}/><Metric label="CLV estimado" value={money(profile.revenue_lifetime_est)} detail={profile.clv_segment||'Segmentación de valor'}/></section>
        <CustomerRiskExplanation data={data.explainability}/>
        <CustomerGraphPanel customerId={selected} onOpenExplorer={openGraph} onOpenCustomer={customerId=>{setQuery(customerId);setSubmitted(customerId);setSelected(customerId)}}/>
        <CustomerTimeline events={data.timeline||[]} networkContext={data.network_context}/>
        <RetentionWorkflowPanel workflow={data.retention_workflow} onChanged={detail.refresh}/>
        <section className="customer-two-col">
          <div className="panel"><PanelHead kicker="NEXT BEST ACTION" title="Qué hacer ahora"/><div className="nba-list">{data.recommendations.map((item:any)=><article key={`${item.type}-${item.title}`}><Severity value={item.priority}/><div><b>{item.title}</b><p>{item.reason}</p><small>{item.action}</small><div className="recommendation-controls"><button disabled={!!decisionBusy||!!caseBusy} onClick={()=>decideRecommendation(item,'ACCEPTED')}><Check/>Aceptar</button><button disabled={!!decisionBusy||!!caseBusy} onClick={()=>decideRecommendation(item,'REJECTED')}><X/>Descartar</button><button className="create-case" disabled={!!decisionBusy||!!caseBusy||data.retention_workflow?.status!=='READY'} onClick={()=>createRetentionCase(item)}><ClipboardCheck/>{caseBusy===`${item.type||item.recommendation_type}-${item.title||item.product_name}`?'Creando…':'Crear caso'}</button></div></div>{item.product&&<span>{money(item.product.precio_usd,false)}/mes</span>}</article>)}</div></div>
          <div className="panel customer-health"><PanelHead kicker="EXPERIENCIA + SLA" title="Compromiso de servicio"/><div className="sla-highlight"><div><small>Cumplimiento de tickets</small><strong>{data.sla.ticket_compliance_pct==null?'—':`${number(data.sla.ticket_compliance_pct)}%`}</strong><span>{data.sla.tickets_breached} de {data.sla.tickets_assessed} fuera del objetivo</span></div><ShieldCheck/></div><dl><div><dt>Política</dt><dd>{data.sla.policy_name}</dd></div><div><dt>Resolución objetivo</dt><dd>{data.sla.resolution_target_hours}h</dd></div><div><dt>Objetivo de servicio</dt><dd>{data.sla.service_target_pct}%</dd></div><div><dt>Señal media 30d</dt><dd>{profile.avg_signal_dbm_30d??'—'} dBm</dd></div><div><dt>Llamadas caídas 30d</dt><dd>{profile.dropped_call_pct_30d??'—'}%</dd></div><div><dt>Datos 30d</dt><dd>{profile.data_gb_30d??'—'} GB</dd></div></dl><p className="sla-disclaimer"><AlertTriangle/>{data.sla.disclaimer}</p></div>
        </section>
        <section className="panel"><PanelHead kicker="PORTAFOLIO" title="Productos contratados"/><div className="product-grid">{data.subscriptions.map((product:any)=><article key={product.suscripcion_id}><div><span>{product.vertical||'Servicio'}</span><span className={`status-pill ${String(product.estado).toLowerCase()}`}>{product.estado}</span></div><h3>{product.product_name||product.plan_id}</h3><p>{product.plan_id} · {product.tier}{product.es_bundle?' · Bundle':''}</p><strong>{money(product.precio_mensual_usd,false)}<small>/mes</small></strong><div>{product.data_gb&&<span>{product.data_gb} GB</span>}{product.internet_mbps&&<span>{product.internet_mbps} Mbps</span>}{product.tv_canales&&<span>{product.tv_canales} canales</span>}{product.minutos&&<span>{product.minutos} min</span>}</div></article>)}</div></section>
        {decisionMessage&&<div className="toast-inline">{decisionMessage}</div>}
        <section className="panel"><PanelHead kicker="PRODUCTOS RECOMENDADOS" title="Oportunidades explicables"/><div className="offer-grid">{data.product_offers.map((offer:any)=><article key={offer.plan_id}><div><span>{offer.recommendation_type.replaceAll('_',' ')}</span><b>{offer.recommendation_score} pts</b></div><h3>{offer.product_name}</h3><p>{offer.reason}</p><footer><span>{offer.vertical} · {offer.tier}</span><strong>{money(offer.precio_usd,false)}/mes</strong></footer>{!offer.marketing_eligible?<small className="consent-warning"><AlertTriangle/>Sin consentimiento comercial</small>:<button className="offer-accept" disabled={!!decisionBusy} onClick={()=>decideRecommendation(offer,'ACCEPTED')}><Check/>Activar oportunidad</button>}</article>)}</div></section>
        {data.recommendation_history?.length>0&&<section className="panel"><PanelHead kicker="CICLO CERRADO" title="Decisiones y resultados"/><div className="recommendation-history">{data.recommendation_history.map((entry:any)=><div key={entry.recommendation_id}><span><b>{entry.title}</b><small>{entry.recommendation_id} · {dateTime(entry.proposed_at)} · {entry.proposed_by}</small></span><span className={`status-pill ${String(entry.status).toLowerCase()}`}>{entry.status}</span>{entry.status==='ACCEPTED'&&<div><button disabled={!!decisionBusy} onClick={()=>recordOutcome(entry.recommendation_id,'CONVERTED')}><Check/>Convertida</button><button disabled={!!decisionBusy} onClick={()=>recordOutcome(entry.recommendation_id,'NO_OUTCOME')}><X/>Sin resultado</button></div>}</div>)}</div></section>}
        <section className="customer-history-grid">
          <div className="panel"><PanelHead kicker="ATENCIÓN" title="Tickets recientes"/><div className="compact-events">{data.tickets.slice(0,8).map((ticket:any)=><div key={ticket.ticket_id}><span className={`event-dot ${ticket.sla_status==='BREACHED'?'bad':'good'}`}/><span><b>{ticket.categoria} · {ticket.motivo}</b><small>{ticket.ticket_id} · {dateTime(ticket.fecha_creacion)}</small></span><strong>{ticket.estado}<small>{ticket.sla_status==='BREACHED'?'Fuera de objetivo':'En objetivo'}</small></strong></div>)}</div></div>
          <div className="panel"><PanelHead kicker="VOZ DEL CLIENTE" title="Historial NPS"/><div className="nps-history">{data.nps_history.map((entry:any)=><div key={entry.fecha_encuesta}><strong>{entry.score}</strong><span><b>{entry.categoria_nps}</b><small>{entry.fecha_encuesta} · {entry.canal_encuesta}</small></span></div>)}{!data.nps_history.length&&<p>Sin respuestas NPS registradas.</p>}</div></div>
          <div className="panel"><PanelHead kicker="COBRANZA" title="Facturas recientes"/><div className="compact-events">{data.billing.slice(0,8).map((invoice:any)=><div key={invoice.factura_id}><span className={`event-dot ${Number(invoice.dias_atraso)>0?'bad':'good'}`}/><span><b>{money(invoice.monto_total_usd,false)}</b><small>{invoice.factura_id} · vence {invoice.fecha_vencimiento}</small></span><strong>{invoice.estado_pago}<small>{invoice.dias_atraso||0} días atraso</small></strong></div>)}</div></div>
        </section>
      </div>}</State>}
    </main>
  </div>
}

function ActionsPage() {
  const [status,setStatus]=useState('ALL')
  const state=useAsync<any[]>(()=>api(`/api/actions${status==='ALL'?'':`?status=${status}`}`),[status])
  const [busy,setBusy]=useState('');const [message,setMessage]=useState('')
  async function decide(id:string,decision:string){setBusy(id);setMessage('');try{await post(`/api/actions/${id}/decision`,{decision,note:'Decisión registrada desde el centro de acciones'});state.refresh()}catch(e:any){setMessage(e.message)}finally{setBusy('')}}
  async function execute(id:string){setBusy(id);setMessage('');try{await post(`/api/actions/${id}/execute`,{connector:'AUTO',note:'Ejecución iniciada desde Quetzal'});setMessage('Acción enviada y ejecutada por el conector.');state.refresh()}catch(e:any){setMessage(e.message);state.refresh()}finally{setBusy('')}}
  return <><div className="toolbar"><Select value={status} onChange={setStatus} options={['ALL','PENDING_APPROVAL','APPROVED','EXECUTING','EXECUTED','FAILED','REJECTED']}/><button className="icon-button" onClick={state.refresh}><RefreshCw/></button></div>
    {message&&<div className="toast-inline action-toast">{message}</div>}
    <State loading={state.loading} error={state.error}><div className="action-grid">{(state.data||[]).map(item=><article className="action-card" key={item.action_id}><div className="action-top"><span className="action-icon"><WandSparkles/></span><span><small>{item.action_id}</small><b>{item.action_type.replaceAll('_',' ')}</b></span><span className={`status-pill ${item.status.toLowerCase()}`}>{item.status}</span></div><p>{item.rationale}</p><div className="action-context"><span>{FLAGS[item.country]} {item.incident_title||item.incident_id}</span><Severity value={item.severity||'MEDIUM'}/></div><div className="action-meta"><span><UserRound/>{item.requested_by}</span><span><Clock3/>{dateTime(item.requested_at)}</span></div>
      {item.execution_ref&&<div className="execution-proof"><Zap/><span><b>{item.connector} · {item.execution_ref}</b><small>{item.execution_detail}</small></span></div>}
      {item.status==='PENDING_APPROVAL'&&<div className="decision-buttons"><button disabled={busy===item.action_id} className="approve" onClick={()=>decide(item.action_id,'APPROVED')}><Check/>Aprobar</button><button disabled={busy===item.action_id} onClick={()=>decide(item.action_id,'REJECTED')}><X/>Rechazar</button></div>}
      {(item.status==='APPROVED'||item.status==='FAILED')&&<button className="execute-button" disabled={busy===item.action_id} onClick={()=>execute(item.action_id)}>{busy===item.action_id?<RefreshCw className="spin"/>:<Zap/>}{item.status==='FAILED'?'Reintentar ejecución':'Ejecutar con conector'}</button>}
    </article>)}</div>{!state.data?.length&&<Empty icon={<ClipboardCheck/>} title="No hay acciones en esta vista" text="Solicita una acción desde el detalle de un incidente."/>}</State></>
}

function ScenariosPage() {
  const [country,setCountry]=useState('ALL');const[growth,setGrowth]=useState(20);const[shift,setShift]=useState(0);const[horizon,setHorizon]=useState(90);const[result,setResult]=useState<any>(null);const[loading,setLoading]=useState(false);const[error,setError]=useState('')
  async function simulate(e:FormEvent){e.preventDefault();setLoading(true);setError('');try{setResult(await post('/api/scenarios/capacity',{country,growth_pct:growth,traffic_shift_pct:shift,horizon_days:horizon}))}catch(err:any){setError(err.message)}finally{setLoading(false)}}
  return <div className="scenario-layout"><form className="panel scenario-form" onSubmit={simulate}><PanelHead kicker="VARIABLES" title="Estrés de capacidad"/><label className="field"><span>Mercado</span><select value={country} onChange={e=>setCountry(e.target.value)}>{COUNTRIES.map(x=><option key={x} value={x}>{x==='ALL'?'Toda LATAM':`${FLAGS[x]} ${x}`}</option>)}</select></label><Range label="Crecimiento de tráfico" value={growth} set={setGrowth} min={-10} max={100} suffix="%"/><Range label="Redistribución de carga" value={shift} set={setShift} min={-30} max={30} suffix="%"/><label className="field"><span>Horizonte</span><select value={horizon} onChange={e=>setHorizon(Number(e.target.value))}><option value={30}>30 días</option><option value={90}>90 días</option><option value={180}>180 días</option><option value={365}>1 año</option></select></label><button className="primary" disabled={loading}>{loading?<RefreshCw className="spin"/>:<Target/>}Simular escenario</button>{error&&<p className="form-error">{error}</p>}</form><section className="scenario-results">{!result?<Empty icon={<CircleGauge/>} title="Modela el futuro de la red" text="Ajusta crecimiento y redistribución para identificar mercados en riesgo."/>:<><div className="metrics-row"><Metric label="Torres en riesgo" value={number(result.totals.towers_at_risk)} detail={`${result.inputs.horizon_days} días`}/><Metric label="Inversión estimada" value={money(result.totals.estimated_investment_usd)} detail="Expansión incremental" tone="amber"/></div><div className="scenario-cards">{result.results.map((item:any)=><article key={item.country}><span>{FLAGS[item.country]} {item.country}</span><Severity value={item.risk}/><div className="capacity-compare"><div><small>Actual</small><b>{number(item.current_capacity_pct)}%</b></div><ArrowRight/><div><small>Proyectada</small><b>{number(item.projected_capacity_pct)}%</b></div></div><div className="capacity-track"><i style={{width:`${Math.min(item.projected_capacity_pct,100)}%`}}/></div><p>{item.recommended_action==='EXPAND_CAPACITY'?'Expandir capacidad y revisar backhaul.':'Mantener observación con alertas preventivas.'}</p></article>)}</div></>}</section></div>
}

function Range({label,value,set,min,max,suffix}: {label:string;value:number;set:(x:number)=>void;min:number;max:number;suffix:string}) {return <label className="range"><span>{label}<b>{value}{suffix}</b></span><input type="range" value={value} min={min} max={max} onChange={e=>set(Number(e.target.value))}/><small><i>{min}{suffix}</i><i>{max}{suffix}</i></small></label>}

function IntelligencePage() {
  const [mode,setMode]=useState<'iq'|'genie'>('iq')
  const [genieMode,setGenieMode]=useState<'quick'|'agent'>('quick')
  const [space,setSpace]=useState('red')
  const [q,setQ]=useState(()=>localStorage.getItem('quetzal-demo-iq-prompt')||'')
  const [conversationId,setConversationId]=useState(()=>localStorage.getItem('quetzal-iq-active')||`iqc-${crypto.randomUUID().replaceAll('-','')}`)
  const [genieConversationId,setGenieConversationId]=useState<string|null>(null)
  const [iqMessages,setIqMessages]=useState<any[]>(()=>{
    try{return JSON.parse(localStorage.getItem(`quetzal-iq-${localStorage.getItem('quetzal-iq-active')}`)||'[]')}catch{return []}
  })
  const [genieMessages,setGenieMessages]=useState<any[]>([])
  const messages=mode==='iq'?iqMessages:genieMessages
  const [busy,setBusy]=useState(false)
  const config=useAsync<any>(()=>api('/api/config'),[])
  const sessions=useAsync<any>(()=>api('/api/chat/sessions'),[])
  const genieEnabled=Object.keys(config.data?.genie_spaces||{}).length>0
  const messagesPanel=useRef<HTMLDivElement>(null)
  useEffect(()=>{if(config.data&&!genieEnabled&&mode==='genie')setMode('iq')},[config.data,genieEnabled,mode])
  useEffect(()=>{const panel=messagesPanel.current;if(panel)panel.scrollTop=panel.scrollHeight},[messages,busy])
  useEffect(()=>{localStorage.setItem('quetzal-iq-active',conversationId);localStorage.setItem(`quetzal-iq-${conversationId}`,JSON.stringify(iqMessages.slice(-60)))},[conversationId,iqMessages])
  useEffect(()=>{localStorage.removeItem('quetzal-demo-iq-prompt')},[])

  async function openConversation(id:string){
    setConversationId(id);setBusy(true)
    try{
      const restored:any=await api(`/api/chat/sessions/${id}`)
      if(restored.messages?.length)setIqMessages(restored.messages.map((turn:any)=>({role:turn.role,text:turn.text,tools:(turn.tools||[]).map((tool:any)=>typeof tool==='string'?{tool,input:''}:tool),engine:turn.role==='assistant'?'Quetzal IQ':undefined,status:turn.role==='assistant'?'verified':undefined,memory:restored.memory})))
      else{try{setIqMessages(JSON.parse(localStorage.getItem(`quetzal-iq-${id}`)||'[]'))}catch{setIqMessages([])}}
    }finally{setBusy(false)}
  }

  function newConversation(){
    if(mode==='genie'){
      setGenieConversationId(null);setGenieMessages([]);setQ('')
      return
    }
    const id=`iqc-${crypto.randomUUID().replaceAll('-','')}`
    setConversationId(id);setIqMessages([]);setQ('')
  }

  function selectGenieSpace(id:string){
    if(id===space)return
    setSpace(id);setGenieConversationId(null);setGenieMessages([]);setQ('')
  }

  async function ask(e:FormEvent){
    e.preventDefault()
    const question=q.trim()
    if(!question||busy)return
    const selectedMode=mode
    const selectedSpace=space
    const startedAt=Date.now()
    setQ('');setBusy(true)
    const append=selectedMode==='iq'?setIqMessages:setGenieMessages
    append(x=>[...x,{role:'user',text:question,engine:selectedMode}])
    try{
      if(selectedMode==='iq'){
        const history=messages.filter(message=>message.role==='user'||message.role==='assistant').slice(-30).map(message=>({role:message.role,text:message.text,tools:(message.tools||[]).map((tool:any)=>typeof tool==='string'?tool:tool.tool).filter(Boolean)}))
        const r:any=await post('/api/chat',{message:question,conversation_id:conversationId,history,continuation_mode:'auto'})
        const sources:any[]=[]
        if(r.internal_data_used)sources.push({label:'Datos internos gobernados'})
        if((r.tools_used||[]).some((tool:any)=>tool.tool==='ontobricks_semantic_query'))sources.push({label:'OntoBricks MCP · grafo semántico gobernado'})
        for(const citation of r.citations||[])sources.push({label:citation.title||citation.url,url:citation.url})
        setIqMessages(x=>[...x,{
          role:r.answer_status==='error'?'error':'assistant',text:r.response,sources,
          model:r.model,status:r.answer_status,traceId:r.trace_id,tools:r.tools_used||[],
          durationMs:Date.now()-startedAt,engine:'Quetzal IQ',memory:r.memory,managedMemory:r.managed_memory,conversationId:r.conversation_id,
        }])
        sessions.refresh()
      }else{
        const deep=genieMode==='agent'
        const start:any=await post('/api/genie/query',{space:selectedSpace,question,deep,conversation_id:genieConversationId||undefined})
        let result:any=deep?start:{status:'RUNNING'}
        if(!deep)for(let i=0;i<60&&!['COMPLETED','FAILED','CANCELLED'].includes(result.status);i++){
          await new Promise(resolve=>setTimeout(resolve,2000))
          result=await api(`/api/genie/result/${selectedSpace}/${start.conversation_id}/${start.message_id}`)
        }
        if(result.status!=='COMPLETED')throw new Error(result.error||`Genie terminó con estado ${result.status}.`)
        const text=result.attachments?.filter((a:any)=>a.type==='text').map((a:any)=>a.content).join('\n\n')||'Genie completó la consulta sin una síntesis textual.'
        const rawQueries=result.attachments?.filter((a:any)=>a.type==='query')||[]
        const chartData=result.attachments?.filter((a:any)=>a.type==='chart_data')||[]
        const visualizations=result.attachments?.filter((a:any)=>a.type==='viz')||[]
        const queries=await Promise.all(rawQueries.map(async(query:any,index:number)=>{
          const inline=chartData.find((chart:any)=>chart.query_index===index)||chartData[index]
          if(inline)return {...query,data:inline,hasVisualization:true}
          if(!query.attachment_id)return query
          try{
            const data=await api(`/api/genie/query-data/${selectedSpace}/${start.conversation_id}/${start.message_id}/${query.attachment_id}`)
            return {...query,data,hasVisualization:visualizations.some((viz:any)=>viz.query_attachment_id===query.attachment_id)}
          }catch(err:any){return {...query,dataError:err.message}}
        }))
        for(const chart of chartData.slice(rawQueries.length))queries.push({title:chart.title||'Resultado analítico',sql:'',data:chart,hasVisualization:true})
        const suggestions=result.attachments?.find((a:any)=>a.type==='suggested_questions')?.questions||[]
        const activeGenieConversation=result.conversation_id||start.conversation_id
        if(activeGenieConversation)setGenieConversationId(activeGenieConversation)
        setGenieMessages(x=>[...x,{
          role:'assistant',text,status:'verified',engine:deep?'Genie Agent Mode':'Databricks Genie',researchMode:deep,
          sources:[{label:start.space_name}],queries,suggestions,traceId:start.trace_id,
          conversationId:result.conversation_id||start.conversation_id,durationMs:Date.now()-startedAt,
        }])
      }
    }catch(err:any){
      append(x=>[...x,{role:'error',status:'error',engine:selectedMode==='iq'?'Quetzal IQ':'Databricks Genie',text:err.message,durationMs:Date.now()-startedAt}])
    }finally{setBusy(false)}
  }

  const prompts=mode==='iq'
    ?['¿Qué incidentes requieren decisión ahora?','¿Dónde está el mayor valor en riesgo?','¿Cuál es la principal competencia que tenemos en Ecuador?']
    :['Haz un resumen ejecutivo de la salud de red','Compara churn y NPS por mercado','Explica la morosidad del último mes']

  return <div className="intelligence-shell">
    <aside className="intelligence-context">
      <div className="mode-switch"><button className={mode==='iq'?'active':''} onClick={()=>setMode('iq')}><BrainCircuit/>Quetzal IQ</button><button className={mode==='genie'?'active':''} onClick={()=>setMode('genie')} disabled={!genieEnabled} title={!genieEnabled?'Genie requiere un alcance sin restricciones territoriales.':undefined}><Sparkles/>Genie</button></div>
      {mode==='iq'?<div className="context-card"><span className="ai-pulse"><i/></span><h3>Orquestador operativo</h3><p>Correlaciona datos internos e información externa, indicando qué herramientas y fuentes sustentan la respuesta.</p><ul><li><Check/>Datos internos gobernados</li><li><Check/>Fuentes web visibles</li><li><Check/>Estado y rastreo por respuesta</li></ul></div>:<><div className="space-list"><span>ESPACIO SEMÁNTICO</span>{Object.entries(config.data?.genie_spaces||{}).map(([id,item]:any)=><button className={space===id?'active':''} onClick={()=>selectGenieSpace(id)} key={id}><Database/><span><b>{item.name}</b><small>{id}</small></span><ArrowRight/></button>)}</div><div className="genie-mode"><span>MODO DE CONSULTA</span><div><button className={genieMode==='quick'?'active':''} onClick={()=>setGenieMode('quick')}><Sparkles/><b>Rápida</b><small>Respuesta directa</small></button><button className={genieMode==='agent'?'active':''} onClick={()=>setGenieMode('agent')}><Telescope/><b>Deep Research</b><small>Agent Mode · varias etapas</small></button></div>{genieMode==='agent'&&<p>Investiga el espacio semántico con mayor profundidad. Puede tardar algunos minutos.</p>}</div></>}
      <AiPreflight/>
      <div className="conversation-list"><span>{mode==='iq'?'CONVERSACIONES RECIENTES':'CONVERSACIÓN GENIE'}</span><button className="new-conversation" onClick={newConversation}><MessageSquareText/><b>Nueva conversación</b></button>{mode==='iq'&&(sessions.data?.sessions||[]).slice(0,6).map((session:any)=><button className={session.conversation_id===conversationId?'active':''} key={session.conversation_id} onClick={()=>openConversation(session.conversation_id)}><Clock3/><span><b>{session.title}</b><small>{session.message_count} mensajes</small></span></button>)}{mode==='genie'&&genieConversationId&&<div className="genie-conversation-live"><i/><span><b>Contexto activo</b><small>{genieConversationId.slice(0,18)}…</small></span></div>}</div>
      <div className="prompt-ideas"><span>PREGUNTAS SUGERIDAS</span>{prompts.map(text=><button key={text} onClick={()=>setQ(text)}>{text}</button>)}</div>
    </aside>
    <section className="chat-panel">
      <div className="chat-head"><div><span className="ai-pulse"><i/></span><span><b>{mode==='iq'?'Quetzal IQ':config.data?.genie_spaces?.[space]?.name||'Genie'}</b><small>{mode==='iq'?'Orquestación con contexto y evidencia':genieMode==='agent'?'Deep Research con Genie Agent Mode':'Consulta directa al espacio semántico de Databricks'}</small></span></div><div className="chat-head-actions"><button className="secondary" onClick={newConversation}><MessageSquareText/>Nueva conversación</button>{mode==='genie'&&<span className={`research-badge ${genieMode==='agent'?'agent':''}`}>{genieMode==='agent'?<Telescope/>:<Sparkles/>}{genieMode==='agent'?'AGENT MODE':'RÁPIDA'}</span>}<span className="connected"><i/>Disponible</span></div></div>
      <div className="messages" ref={messagesPanel}>
        {!messages.length&&<div className="chat-empty"><QuetzalMark compact/><h3>Alcance para entender.<br/>Libertad para decidir.</h3><p>Quetzal IQ consulta herramientas operativas. Genie consulta el espacio semántico seleccionado. Cada respuesta muestra su origen y rastreo.</p></div>}
        {messages.map((msg,i)=><IntelligenceMessage key={i} message={msg} onSuggestion={setQ}/>)}
        {busy&&<div className="message assistant"><span className="message-avatar"><RefreshCw className="spin"/></span><div className="thinking"><i/><i/><i/>{mode==='iq'?'Consultando fuentes y sintetizando':genieMode==='agent'?'Agent Mode está investigando en varias etapas':'Genie está preparando la consulta y la respuesta'}</div></div>}
      </div>
      <form className="chat-composer" onSubmit={ask}><textarea value={q} onChange={e=>setQ(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();e.currentTarget.form?.requestSubmit()}}} placeholder={mode==='iq'?'Pregunta sobre la operación o el mercado…':genieMode==='agent'?'Solicita una investigación analítica profunda…':'Consulta el espacio semántico seleccionado…'} rows={2}/><button disabled={busy||!q.trim()} aria-label="Enviar pregunta"><Send/></button><span><ShieldCheck/>{mode==='genie'&&genieMode==='agent'?'Agent Mode · ':''}Datos gobernados · Respuestas rastreables</span></form>
    </section>
  </div>
}

function IntelligenceMessage({message:msg,onSuggestion}:{message:any;onSuggestion:(value:string)=>void}){
  if(msg.role==='user')return <div className="message user"><ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown></div>
  const labels:Record<string,string>={verified:'RESPUESTA CON EVIDENCIA',generated:'RESPUESTA DEL MODELO',error:'RESPUESTA INCOMPLETA'}
  return <div className={`message ${msg.role}`}>
    <span className="message-avatar">{msg.role==='error'?<AlertTriangle/>:<Sparkles/>}</span>
    <div className="message-body">
      <span className={`answer-label ${msg.status||''}`}>{labels[msg.status]||'RESPUESTA'}</span>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
      {msg.sources?.length>0&&<div className="sources">{msg.sources.map((source:any,index:number)=>source.url?<a key={`${source.url}-${index}`} href={source.url} target="_blank" rel="noreferrer"><ExternalLink/>{source.label}</a>:<span key={`${source.label}-${index}`}><ShieldCheck/>{source.label}</span>)}</div>}
      {msg.tools?.length>0&&<div className="tool-trace">{msg.tools.map((tool:any,index:number)=><span key={`${tool.tool}-${index}`}><Database/>{tool.tool==='web_search'?'Busca web':tool.tool==='ontobricks_semantic_query'?`OntoBricks MCP · ${tool.input?.intent||'consulta semántica'}`:`Snapshot ${tool.input?.scope||tool.input}`}</span>)}</div>}
      {msg.queries?.map((query:any,index:number)=><GenieEvidence query={query} key={query.attachment_id||index}/>)}
      {msg.suggestions?.length>0&&<div className="answer-suggestions"><b>Continúa investigando</b>{msg.suggestions.map((suggestion:string)=><button key={suggestion} onClick={()=>onSuggestion(suggestion)}>{suggestion}<ArrowRight/></button>)}</div>}
      {(msg.engine||msg.traceId)&&<div className="answer-meta"><span>{msg.engine}</span>{msg.memory&&<span>{msg.memory.persisted||msg.memory.status==='RESTORED'?'Historial Lakebase':'Contexto de sesión'}</span>}{msg.managedMemory?.recalled&&<span>Memoria recuperada · {msg.managedMemory.recalled_count}</span>}{msg.managedMemory?.persisted&&<span>Memoria guardada</span>}{msg.durationMs&&<span>{(msg.durationMs/1000).toFixed(1)} s</span>}{msg.conversationId&&<span title={msg.conversationId}>Conversación {msg.conversationId.slice(0,12)}…</span>}{msg.traceId&&<span>Rastreo {msg.traceId}</span>}</div>}
    </div>
  </div>
}

function GenieEvidence({query}:{query:any}){
  const data=query.data
  const chart=inferGenieChart(data||{})
  const [view,setView]=useState<'chart'|'data'>(()=>chart?'chart':'data')
  return <section className="genie-evidence">
    <div className="evidence-head"><span><Database/><b>{query.title||'Datos consultados'}</b></span><span className="evidence-meta"><small>{data?.row_count??query.row_count??0} filas · {data?.status||'COMPLETADO'}</small>{chart&&<span className="evidence-tabs"><button className={view==='chart'?'active':''} onClick={()=>setView('chart')}><BarChart3/>Gráfico</button><button className={view==='data'?'active':''} onClick={()=>setView('data')}><Table2/>Datos</button></span>}</span></div>
    {query.description&&<p>{query.description}</p>}
    {chart&&view==='chart'&&<GenieChart data={data} spec={chart} title={query.title||'Visualización de los datos'}/>} 
    {data?.rows?.length>0&&view==='data'&&<div className="genie-table-wrap"><table><thead><tr>{data.columns.map((column:any)=><th key={column.name}>{column.name.replaceAll('_',' ')}</th>)}</tr></thead><tbody>{data.rows.slice(0,50).map((row:any[],rowIndex:number)=><tr key={rowIndex}>{row.map((value:any,columnIndex:number)=><td key={columnIndex}>{value??'—'}</td>)}</tr>)}</tbody></table></div>}
    {query.dataError&&<p className="data-warning"><AlertTriangle/>No fue posible cargar las filas: {query.dataError}</p>}
    <details><summary>Ver consulta SQL y trazabilidad</summary>{query.thoughts?.length>0&&<div className="query-thoughts">{query.thoughts.map((thought:any,index:number)=><p key={index}>{thought.content}</p>)}</div>}<pre>{query.sql}</pre></details>
  </section>
}

function GenieChart({data,spec,title}:{data:any;spec:GenieChartSpec;title:string}){
  const [tooltip,setTooltip]=useState<{x:number;y:number;rowIndex:number}|null>(null)
  const width=760,height=310,left=64,right=24,top=24,bottom=62
  const plotWidth=width-left-right,plotHeight=height-top-bottom
  const metrics=spec.metricIndexes
  const values=spec.rows.flatMap(row=>metrics.map(index=>numericValue(row[index])).filter((value):value is number=>value!==null))
  const min=Math.min(0,...values),max=Math.max(0,...values),span=max-min||1
  const y=(value:number)=>top+(max-value)/span*plotHeight
  const zeroY=y(0),palette=['chart-green','chart-blue','chart-amber']
  const labels=spec.rows.map(row=>String(row[spec.dimensionIndex]??'—'))
  const short=(value:string)=>value.length>13?`${value.slice(0,11)}…`:value
  const showTooltip=(event:any,rowIndex:number)=>{
    const container=event.currentTarget.closest('.genie-chart') as HTMLElement|null
    if(!container)return
    const box=container.getBoundingClientRect()
    setTooltip({x:Math.min(Math.max(event.clientX-box.left,100),box.width-100),y:Math.max(event.clientY-box.top-8,82),rowIndex})
  }
  const tooltipRow=tooltip?spec.rows[tooltip.rowIndex]:null
  return <div className="genie-chart" role="img" aria-label={`${title}. ${spec.kind==='line'?'Gráfico de líneas':'Gráfico de barras'}`} onPointerLeave={()=>setTooltip(null)}>
    <div className="chart-legend">{metrics.map((metric,index)=><span key={metric}><i className={palette[index]}/>{data.columns[metric].name.replaceAll('_',' ')}</span>)}</div>
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
      {[0,.25,.5,.75,1].map(tick=>{const value=max-(span*tick),py=top+plotHeight*tick;return <g key={tick}><line className="chart-grid" x1={left} x2={width-right} y1={py} y2={py}/><text className="chart-y-label" x={left-9} y={py+4} textAnchor="end">{Intl.NumberFormat('es-419',{notation:'compact',maximumFractionDigits:1}).format(value)}</text></g>})}
      <line className="chart-axis" x1={left} x2={width-right} y1={zeroY} y2={zeroY}/>
      {spec.kind==='bar'?spec.rows.flatMap((row,rowIndex)=>metrics.map((metric,metricIndex)=>{const value=numericValue(row[metric])??0;const group=plotWidth/spec.rows.length;const barWidth=Math.max(3,Math.min(34,(group-8)/metrics.length));const x=left+rowIndex*group+(group-barWidth*metrics.length)/2+metricIndex*barWidth;return <rect key={`${rowIndex}-${metric}`} className={`${palette[metricIndex]} chart-mark`} x={x} y={Math.min(y(value),zeroY)} width={Math.max(2,barWidth-2)} height={Math.max(1,Math.abs(zeroY-y(value)))} rx="3" onPointerEnter={event=>showTooltip(event,rowIndex)} onPointerMove={event=>showTooltip(event,rowIndex)}/> })):
        metrics.map((metric,metricIndex)=>{const points=spec.rows.map((row,index)=>`${left+(plotWidth/Math.max(1,spec.rows.length-1))*index},${y(numericValue(row[metric])??0)}`).join(' ');return <g key={metric}><polyline className={`chart-line ${palette[metricIndex]}`} points={points}/>{spec.rows.map((row,index)=>{const cx=left+(plotWidth/Math.max(1,spec.rows.length-1))*index,cy=y(numericValue(row[metric])??0);return <circle key={index} className={`${palette[metricIndex]} chart-mark`} cx={cx} cy={cy} r="5" onPointerEnter={event=>showTooltip(event,index)} onPointerMove={event=>showTooltip(event,index)}/>})}</g>})}
      {labels.map((label,index)=>{const every=Math.max(1,Math.ceil(labels.length/10));if(index%every!==0&&index!==labels.length-1)return null;const x=left+(spec.kind==='bar'?(plotWidth/spec.rows.length)*(index+.5):(plotWidth/Math.max(1,labels.length-1))*index);return <text className="chart-x-label" key={index} x={x} y={height-bottom+24} textAnchor="middle">{short(label)}</text>})}
    </svg>
    {tooltip&&tooltipRow&&<div className="chart-tooltip" style={{left:tooltip.x,top:tooltip.y}}><strong>{labels[tooltip.rowIndex]}</strong>{metrics.map((metric,index)=><span key={metric}><i className={palette[index]}/><small>{data.columns[metric].name.replaceAll('_',' ')}</small><b>{String(tooltipRow[metric]??'—')}</b></span>)}</div>}
    {data?.rows?.length>20&&<small className="chart-note">Visualización limitada a las primeras 20 categorías. Todos los datos están en la pestaña Datos.</small>}
  </div>
}

function GovernancePage() {
  const state=useAsync<any>(()=>api('/api/governance/trust'),[])
  const alerts=useAsync<any[]>(()=>api('/api/alerts/subscriptions'),[])
  const events=useAsync<any[]>(()=>api('/api/alerts/events?status=OPEN'),[])
  const sla=useAsync<any>(()=>api('/api/sla/portfolio'),[])
  const[name,setName]=useState('Alerta de capacidad crítica');const[threshold,setThreshold]=useState(85);const[busy,setBusy]=useState(false);const[msg,setMsg]=useState('')
  async function create(e:FormEvent){e.preventDefault();setBusy(true);try{await post('/api/alerts/subscriptions',{name,domain:'NETWORK',country:'ALL',metric:'capacity_pct',operator:'>=',threshold,channel:'IN_APP',enabled:true});setMsg('Regla creada y lista para evaluación.');alerts.refresh()}catch(err:any){setMsg(err.message)}finally{setBusy(false)}}
  async function evaluate(){setBusy(true);try{const result:any=await post('/api/alerts/evaluate',{});setMsg(`${result.rules_evaluated} reglas evaluadas · ${result.signals_triggered} señales activadas.`);events.refresh();state.refresh()}catch(e:any){setMsg(e.message)}finally{setBusy(false)}}
  async function toggle(item:any){setBusy(true);try{await patch(`/api/alerts/subscriptions/${item.subscription_id}`,{enabled:!item.enabled});alerts.refresh()}catch(e:any){setMsg(e.message)}finally{setBusy(false)}}
  async function acknowledge(id:string){setBusy(true);try{await post(`/api/alerts/events/${id}/acknowledge`,{note:'Atendida desde el centro de confianza'});events.refresh()}catch(e:any){setMsg(e.message)}finally{setBusy(false)}}
  const slaTotals=(sla.data?.countries||[]).reduce((a:any,x:any)=>({tickets:a.tickets+Number(x.tickets_assessed||0),breached:a.breached+Number(x.breached||0),credit:a.credit+Number(x.estimated_credit_usd||0)}),{tickets:0,breached:0,credit:0})
  return <State loading={state.loading} error={state.error}><div className="stack-lg">
    <section className="trust-grid">{(state.data?.freshness||[]).map((item:any)=><article key={item.domain}><span className={`freshness ${item.status.toLowerCase()}`}><i/>{item.status}</span><Database/><h3>{item.domain}</h3><strong>{number(item.lag_hours)}h</strong><small>desde {dateTime(item.as_of)}</small></article>)}</section>
    <section className="metrics-row"><Metric label="Alertas abiertas" value={number(events.data?.length||0)} detail="Motor ejecutado bajo demanda" tone="amber" icon={<BellRing/>}/><Metric label="Tickets con SLA" value={number(slaTotals.tickets)} detail="Portafolio evaluado" icon={<ShieldCheck/>}/><Metric label="Incumplimientos" value={number(slaTotals.breached)} detail="Según contrato efectivo" tone="red" icon={<Clock3/>}/><Metric label="Crédito estimado" value={money(slaTotals.credit)} detail="Sujeto a validación" tone="blue" icon={<FileCheck2/>}/></section>
    <section className="two-one-grid"><div className="panel"><PanelHead kicker="EVENTOS" title="Central de alertas" action={<button className="text-button" disabled={busy} onClick={evaluate}><RefreshCw className={busy?'spin':''}/>Evaluar ahora</button>}/><div className="alert-events">{events.data?.map(item=><div key={item.event_id}><Severity value={item.severity}/><span><b>{item.name}</b><small>{FLAGS[item.country]} {item.country} · {item.metric} {number(item.observed_value)} / umbral {number(item.threshold)} · {dateTime(item.detected_at)}</small></span><button onClick={()=>acknowledge(item.event_id)} disabled={busy}><Check/>Acusar</button></div>)}{!events.loading&&!events.data?.length&&<p>Sin alertas abiertas.</p>}</div></div>
      <div className="panel alert-builder"><PanelHead kicker="MOTOR DE ALERTAS" title="Nueva regla personal"/><form onSubmit={create}><label className="field"><span>Nombre</span><input value={name} onChange={e=>setName(e.target.value)}/></label><label className="field"><span>Umbral de capacidad</span><input type="number" value={threshold} onChange={e=>setThreshold(Number(e.target.value))}/></label><button className="primary" disabled={busy}><BellRing/>Crear alerta</button></form>{msg&&<div className="toast-inline">{msg}</div>}<div className="subscription-list">{alerts.data?.map(item=><div key={item.subscription_id}><BellRing/><span><b>{item.name}</b><small>{item.metric} {item.operator} {item.threshold} · {item.channel}</small></span><button className={`status-pill ${item.enabled?'active':''}`} disabled={busy} onClick={()=>toggle(item)}>{item.enabled?'ACTIVA':'PAUSADA'}</button></div>)}</div></div></section>
    <section className="two-one-grid"><div className="panel"><PanelHead kicker="SLA EFECTIVO" title="Cumplimiento y exposición por mercado"/><div className="sla-portfolio">{sla.data?.countries?.map((item:any)=><div key={item.country}><span>{FLAGS[item.country]} <b>{item.country}</b></span><span>{number(item.compliance_pct)}%<small>cumplimiento</small></span><span>{number(item.breached)}<small>fuera de SLA</small></span><strong>{money(item.estimated_credit_usd)}<small>crédito est.</small></strong></div>)}</div></div><div className="panel"><PanelHead kicker="DICCIONARIO" title="Definiciones críticas"/><div className="definition-list">{state.data?.metric_definitions.map((item:any)=><div key={item.name}><FileCheck2/><span><b>{item.name}</b><p>{item.definition}</p><small>Owner · {item.owner}</small></span>{item.contractual_uptime===false&&<span className="warning-tag">NO ES SLA</span>}</div>)}</div></div></section>
    <section className="panel"><PanelHead kicker="AUDITORÍA" title="Decisiones recientes"/><div className="audit-list">{state.data?.audit.map((item:any)=><div key={item.event_id}><span className="audit-icon"><FileCheck2/></span><span><b>{item.event_type.replaceAll('_',' ')}</b><small>{item.resource_type} · {item.resource_id}</small></span><span>{item.actor}<small>{dateTime(item.event_at)}</small></span></div>)}</div></section>
  </div></State>
}

function Empty({icon,title,text}: {icon:ReactNode;title:string;text:string}) {return <div className="empty">{icon}<h3>{title}</h3><p>{text}</p></div>}

export default App
