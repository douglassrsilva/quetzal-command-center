import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowRight, Globe2, Network, RefreshCw, ShieldCheck, UsersRound } from 'lucide-react'
import { api, money, number } from './api'
import GraphViewport from './GraphViewport'
import { graphNodeId, graphNodeLabel, graphNodeType, graphScorePercent, type GraphNode, type GraphPayload } from './graphTypes'

type Props = {
  customerId: string
  onOpenCustomer: (customerId:string) => void
  onOpenExplorer: () => void
}

export default function CustomerGraphPanel({customerId,onOpenCustomer,onOpenExplorer}:Props) {
  const [affinity,setAffinity]=useState('ALL')
  const [maxNeighbors,setMaxNeighbors]=useState(30)
  const [selected,setSelected]=useState<GraphNode|null>(null)
  const [data,setData]=useState<GraphPayload|null>(null)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  const [nonce,setNonce]=useState(0)

  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError('');setSelected(null)
    api<GraphPayload>(`/api/customers/${encodeURIComponent(customerId)}/graph?max_neighbors=${maxNeighbors}&affinity=${affinity}`,{signal:controller.signal})
      .then(setData).catch(error=>{if(error.name!=='AbortError')setError(error.message)}).finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return()=>controller.abort()
  },[customerId,affinity,maxNeighbors,nonce])

  const center=useMemo(()=>data?.center||data?.nodes?.find(node=>node.is_center)||data?.nodes?.find(node=>graphNodeId(node)===customerId),[data,customerId])
  const graphNodes=useMemo(()=>{const centerId=center?graphNodeId(center):customerId;return (data?.nodes||[]).map(node=>graphNodeId(node)===centerId?{...node,is_center:true}:node)},[data,center,customerId])
  const summary=data?.summary||{}
  const definition=data?.relationship_definition
  const qualified=definition?.status==='ACTIVE'
  const selectedId=selected?graphNodeId(selected):''
  return <section className="panel customer-graph-panel">
    <header className="graph-panel-head"><div><span>GRAPH INTELLIGENCE</span><h3>Alcance y exposición relacional</h3><p>Separa la propensión individual de churn de las señales de alcance y proximidad en contactos calificados.</p></div><button className="secondary" onClick={onOpenExplorer}><Network/>Explorar red completa</button></header>
    <div className="graph-filterbar">
      <label><span>Afinidad</span><select value={affinity} onChange={event=>setAffinity(event.target.value)}><option value="ALL">Todas</option>{qualified?<option value="FREQUENT">Contacto frecuente</option>:<><option value="HOUSEHOLD">Hogar · sintético</option><option value="SOCIAL">Social · sintético</option><option value="WORK">Trabajo · sintético</option></>}<option value="CROSS_BORDER">Transfronteriza</option><option value="OTHER">Otras</option></select></label>
      <label><span>Contactos</span><select value={maxNeighbors} onChange={event=>setMaxNeighbors(Number(event.target.value))}><option value={15}>15 más relevantes</option><option value={30}>30 más relevantes</option><option value={60}>60 más relevantes</option></select></label>
      <span className="graph-freshness"><i/>{data?.run?.computed_at||data?.computed_at?`Calculado ${new Date(String(data?.run?.computed_at||data?.computed_at)).toLocaleDateString('es-419')}`:'Snapshot gobernado'}</span>
    </div>
    {definition&&<div className={`graph-definition ${qualified?'active':'pending'}`}><ShieldCheck/><span><b>{definition.label}</b><small>{definition.criteria.join(' · ')}. {definition.affinity_semantics}</small></span>{!qualified&&<em>Pendiente de actualización manual</em>}</div>}
    {loading&&<div className="graph-state"><RefreshCw className="spin"/>Conectando relaciones del cliente…</div>}
    {error&&<div className="graph-state error"><AlertTriangle/><span><b>No fue posible cargar el grafo.</b><small>{error}</small></span><button onClick={()=>setNonce(value=>value+1)}>Reintentar</button></div>}
    {!loading&&!error&&data?.available===false&&<div className="graph-state"><Network/><span><b>Graph Intelligence aún no tiene un snapshot.</b><small>{data.message||'Ejecuta el procesamiento manual desde el explorador de red.'}</small></span><button onClick={onOpenExplorer}>Abrir explorador</button></div>}
    {!loading&&!error&&data&&data.available!==false&&<>
      <div className="graph-kpis">
        <span><UsersRound/><small>Relaciones visibles</small><b>{number(summary.total_nodes??summary.nodes??Math.max(0,data.nodes.length-1))}</b></span>
        <span><Network/><small>Alcance</small><b>{number(graphScorePercent(center?.reach_score??center?.influence_score))}%</b></span>
        <span><AlertTriangle/><small>Exposición relacional</small><b>{number(graphScorePercent(center?.network_exposure_score??center?.contagion_score))}%</b></span>
        <span><Globe2/><small>Valor en relaciones</small><b>{money(summary.influenced_revenue_usd??summary.influenced_revenue??center?.influenced_revenue_usd??center?.monthly_revenue??0)}</b></span>
      </div>
      <div className="customer-graph-layout">
        <GraphViewport nodes={graphNodes} edges={data.edges||[]} selectedId={selectedId} onSelect={setSelected} ariaLabel={`Red de alcance del cliente ${customerId}`}/>
        <aside className="graph-node-detail">
          {!selected&&<div className="graph-detail-empty"><Network/><b>Selecciona un nodo</b><p>Consulta churn individual, alcance, exposición y afinidad de cada relación.</p></div>}
          {selected&&<><span>{graphNodeType(selected)==='community'?'GRUPO':'RELACIÓN SELECCIONADA'}</span><h4>{graphNodeLabel(selected)}</h4><dl><div><dt>Mercado</dt><dd>{selected.country||'—'}</dd></div><div><dt>Churn individual</dt><dd>{number(Number(selected.baseline_churn_probability??selected.churn_probability??0)*100)}%</dd></div><div><dt>Alcance</dt><dd>{number(graphScorePercent(selected.reach_score??selected.influence_score))}%</dd></div><div><dt>Exposición</dt><dd>{number(graphScorePercent(selected.network_exposure_score??selected.contagion_score))}%</dd></div><div><dt>Grupo</dt><dd>{selected.community_id||'—'}</dd></div><div><dt>Países</dt><dd>{number(selected.countries_reached||0)} país(es)</dd></div></dl>{graphNodeType(selected)==='customer'&&graphNodeId(selected)!==customerId&&<button onClick={()=>onOpenCustomer(graphNodeId(selected))}>Abrir Cliente 360 <ArrowRight/></button>}</>}
        </aside>
      </div>
    </>}
  </section>
}
