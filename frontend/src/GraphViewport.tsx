import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type WheelEvent } from 'react'
import { Maximize2, Minus, Plus } from 'lucide-react'
import { graphNodeId, graphNodeLabel, graphNodeType, graphScorePercent, type GraphEdge, type GraphLevel, type GraphNode } from './graphTypes'

type ViewBox = { x: number; y: number; width: number; height: number }
type PointNode = GraphNode & { _id: string; _x: number; _y: number }

type Props = {
  nodes: GraphNode[]
  edges: GraphEdge[]
  level?: GraphLevel
  selectedId?: string
  onSelect: (node: GraphNode) => void
  ariaLabel?: string
}

const INITIAL_VIEW: ViewBox = { x: 0, y: 0, width: 100, height: 100 }
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

function positionedNodes(nodes: GraphNode[], level:GraphLevel): PointNode[] {
  const centerIndex = nodes.findIndex(node => node.is_center)
  return nodes.map((node, index) => {
    const id = graphNodeId(node) || `node-${index}`
    if (nodes.length > 24 && centerIndex < 0) {
      const angle = index * 2.399963229728653 - Math.PI / 2
      const radius = 7 + Math.sqrt((index + 1) / nodes.length) * 38
      return { ...node, _id:id, _x:50 + Math.cos(angle) * radius, _y:50 + Math.sin(angle) * radius }
    }
    if (Number.isFinite(Number(node.x)) && Number.isFinite(Number(node.y))) {
      return { ...node, _id: id, _x: clamp(Number(node.x), 5, 95), _y: clamp(Number(node.y), 7, 93) }
    }
    if (node.is_center) {
      return { ...node, _id: id, _x: 50, _y: 50 }
    }
    if (centerIndex < 0 || level === 'community') {
      const angle = index * 2.399963229728653
      const radius = 8 + Math.sqrt((index + 1) / Math.max(1, nodes.length)) * 36
      return { ...node, _id: id, _x: 50 + Math.cos(angle) * radius, _y: 50 + Math.sin(angle) * radius }
    }
    const offset = index > centerIndex ? index - 1 : index
    const count = Math.max(1, nodes.length - 1)
    const ring = count > 24 && offset >= Math.ceil(count / 2) ? 34 : 25
    const ringOffset = ring === 34 ? Math.ceil(count / 2) : 0
    const ringCount = ring === 34 ? count - ringOffset : Math.min(count, Math.ceil(count / 2))
    const angle = ((offset - ringOffset) / Math.max(1, ringCount)) * Math.PI * 2 - Math.PI / 2
    return { ...node, _id: id, _x: 50 + Math.cos(angle) * ring, _y: 50 + Math.sin(angle) * ring }
  })
}

export default function GraphViewport({nodes, edges, level='customer', selectedId='', onSelect, ariaLabel='Grafo de relaciones'}: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{x:number;y:number;view:ViewBox}|null>(null)
  const [view, setView] = useState<ViewBox>(INITIAL_VIEW)
  const [tooltip, setTooltip] = useState<{node:PointNode;left:number;top:number}|null>(null)
  const points = useMemo(() => positionedNodes(nodes,level), [nodes,level])
  const byId = useMemo(() => new Map(points.map(node => [node._id, node])), [points])

  useEffect(() => { setView(INITIAL_VIEW); setTooltip(null) }, [nodes])

  function zoom(factor:number, anchorX=50, anchorY=50) {
    setView(current => {
      const width = clamp(current.width * factor, 30, 100)
      const height = clamp(current.height * factor, 30, 100)
      const ax = current.x + current.width * anchorX / 100
      const ay = current.y + current.height * anchorY / 100
      return {
        x: clamp(ax - width * anchorX / 100, 0, 100 - width),
        y: clamp(ay - height * anchorY / 100, 0, 100 - height),
        width, height,
      }
    })
  }

  function wheel(event:WheelEvent<SVGSVGElement>) {
    event.preventDefault()
    const rect = event.currentTarget.getBoundingClientRect()
    zoom(event.deltaY > 0 ? 1.12 : .88, (event.clientX - rect.left) / rect.width * 100, (event.clientY - rect.top) / rect.height * 100)
  }

  function startPan(event:PointerEvent<SVGSVGElement>) {
    if ((event.target as Element).closest('.graph-node-group')) return
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { x:event.clientX, y:event.clientY, view }
  }

  function pan(event:PointerEvent<SVGSVGElement>) {
    const drag = dragRef.current
    if (!drag) return
    const rect = event.currentTarget.getBoundingClientRect()
    const dx = (event.clientX - drag.x) / rect.width * drag.view.width
    const dy = (event.clientY - drag.y) / rect.height * drag.view.height
    setView({...drag.view, x:clamp(drag.view.x-dx,0,100-drag.view.width), y:clamp(drag.view.y-dy,0,100-drag.view.height)})
  }

  function showTooltip(node:PointNode, event:PointerEvent<SVGGElement>) {
    const rect = hostRef.current?.getBoundingClientRect()
    if (!rect) return
    setTooltip({node,left:clamp(event.clientX-rect.left,140,rect.width-140),top:clamp(event.clientY-rect.top,115,rect.height-30)})
  }

  function keySelect(event:KeyboardEvent<SVGGElement>, node:PointNode) {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(node) }
  }

  if (!points.length) return <div className="graph-empty" role="status">No hay relaciones disponibles para esta selección.</div>

  return <div className="graph-viewport" ref={hostRef}>
    <div className="graph-controls" aria-label="Controles del grafo">
      <button onClick={()=>zoom(.82)} aria-label="Acercar"><Plus/></button>
      <button onClick={()=>zoom(1.18)} aria-label="Alejar"><Minus/></button>
      <button onClick={()=>setView(INITIAL_VIEW)} aria-label="Ajustar grafo a la pantalla"><Maximize2/></button>
    </div>
    <svg viewBox={`${view.x} ${view.y} ${view.width} ${view.height}`} role="group" aria-label={ariaLabel}
      onWheel={wheel} onPointerDown={startPan} onPointerMove={pan} onPointerUp={()=>{dragRef.current=null}} onPointerCancel={()=>{dragRef.current=null}}>
      <defs>
        <pattern id="graph-grid" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M 8 0 L 0 0 0 8" className="graph-grid-line"/></pattern>
        <filter id="node-glow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="1.4" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      </defs>
      <rect width="100" height="100" fill="url(#graph-grid)" className="graph-pan-surface"/>
      <g className="graph-edges" aria-hidden="true">
        {edges.map((edge,index)=>{const source=byId.get(String(edge.source));const target=byId.get(String(edge.target));if(!source||!target)return null;const weight=Number(edge.calls??edge.weight??1);return <line key={`${edge.source}-${edge.target}-${index}`} x1={source._x} y1={source._y} x2={target._x} y2={target._y} className={`${edge.international?'international':''} ${edge.reciprocal?'reciprocal':''}`} style={{strokeWidth:clamp(.18+Math.log1p(weight)*.11,.24,1.05)}}/>})}
      </g>
      <g className="graph-nodes">
        {points.map(node=>{const id=node._id;const selected=id===selectedId;const kind=graphNodeType(node);const risk=String(node.risk_tier||'unknown').toLowerCase();const dense=points.length>24;const size=kind==='semantic'?clamp(3.4+Math.log10(Number(node.entity_count||1)+1)*1.25,4.2,8.2):kind==='community'?(dense?clamp(2.35+Math.sqrt(Number(node.customers??node.customer_count??1))*.024,2.7,4.25):clamp(3.8+Math.sqrt(Number(node.customers??node.customer_count??1))*.07,4.5,9)):node.is_center?5.2:dense?clamp(1.35+graphScorePercent(node.influence_score)/105,1.45,2.3):clamp(2.25+graphScorePercent(node.influence_score)/50,2.25,4.3);const label=graphNodeLabel(node);const kindLabel=kind==='semantic'?'Clase semántica':kind==='community'?'Grupo':'Cliente';return <g key={id} transform={`translate(${node._x} ${node._y})`} role="button" tabIndex={0} aria-label={`${kindLabel} ${label}${kind==='semantic'?'.':`. Riesgo ${node.risk_tier||'no disponible'}.`}`} className={`graph-node-group ${kind} risk-${risk} ${selected?'selected':''} ${node.is_center?'center':''} ${dense?'dense':''}`} onClick={()=>onSelect(node)} onKeyDown={event=>keySelect(event,node)} onPointerEnter={event=>showTooltip(node,event)} onPointerMove={event=>showTooltip(node,event)} onPointerLeave={()=>setTooltip(null)} onFocus={()=>setTooltip({node,left:165,top:190})} onBlur={()=>setTooltip(null)}>
          <circle r={size+(dense?.65:1.5)} className="graph-node-ring"/>
          <circle r={size} className="graph-node-core" filter={selected||node.is_center?'url(#node-glow)':undefined}/>
          {(selected||node.is_center||points.length<=18)&&<text y={size+4.8} textAnchor="middle">{label.length>20?`${label.slice(0,18)}…`:label}</text>}
        </g>})}
      </g>
    </svg>
    <div className="graph-legend" aria-label="Leyenda">{level==='semantic'?<><span><i className="semantic"/>Tipo de entidad</span><span><b className="semantic-edge"/>Relación ontológica</span></>:<><span><i className="high"/>Alto riesgo</span><span><i className="medium"/>Riesgo medio</span><span><i className="low"/>Bajo riesgo</span><span><b className="international"/>Internacional</span></>}</div>
    <span className="graph-instruction">Arrastra para mover · rueda o controles para ampliar</span>
    {tooltip&&<div className="graph-tooltip" style={{left:tooltip.left,top:tooltip.top}} role="tooltip">{graphNodeType(tooltip.node)==='semantic'?<><small>CLASE ONTOLÓGICA</small><strong>{graphNodeLabel(tooltip.node)}</strong><div><span><b>{Number(tooltip.node.entity_count||0).toLocaleString('es-419')}</b><small>entidades</small></span><span><b>{String(tooltip.node.class_name||'—')}</b><small>tipo técnico</small></span></div></>:<><small>{graphNodeType(tooltip.node)==='community'?'GRUPO':'CLIENTE'}</small><strong>{graphNodeLabel(tooltip.node)}</strong><div><span><b>{Math.round(Number(tooltip.node.baseline_churn_probability??tooltip.node.churn_probability??0)*100)}%</b><small>{graphNodeType(tooltip.node)==='community'?'churn promedio':'churn individual'}</small></span><span><b>{Math.round(graphScorePercent(tooltip.node.reach_score??tooltip.node.influence_score))}%</b><small>alcance</small></span><span><b>{tooltip.node.country||'—'}</b><small>mercado</small></span></div></>}</div>}
  </div>
}
