import { useState } from 'react'
import { AlertTriangle, CheckCircle2, ChevronDown, RefreshCw, ShieldCheck, Wrench } from 'lucide-react'
import { api } from './api'

const LABELS:Record<string,string>={warehouse:'SQL Warehouse',genie:'Genie Spaces',ai_gateway:'Quetzal IQ',lakebase:'Lakebase',managed_memory:'Agent Memory',dashboard:'AI/BI Dashboard',rbac:'Permisos y alcance',graph_snapshot:'Graph Intelligence'}

export default function AiPreflight(){
  const[data,setData]=useState<any>(null);const[busy,setBusy]=useState(false);const[error,setError]=useState('');const[open,setOpen]=useState(false)
  async function run(){setBusy(true);setError('');setOpen(true);try{setData(await api('/api/demo/preflight'))}catch(err:any){setError(err.message)}finally{setBusy(false)}}
  const ready=(data?.checks||[]).filter((item:any)=>item.status==='READY').length
  const total=data?.checks?.length||0
  return <div className={`ai-preflight ${open?'open':''}`}>
    <button className="preflight-trigger" onClick={run} disabled={busy}>{busy?<RefreshCw className="spin"/>:<ShieldCheck/>}<span><b>{data?`${ready}/${total} verificaciones listas`:'Validar la demo'}</b><small>Preflight sin inferencia ni jobs</small></span><ChevronDown/></button>
    {open&&<div className="preflight-panel">{busy&&<p><RefreshCw className="spin"/>Verificando dependencias en modo lectura…</p>}{error&&<p className="preflight-error"><AlertTriangle/>{error}</p>}{data&&<><header><span className={`preflight-overall ${String(data.status).toLowerCase()}`}>{data.status}</span><small>Inferencia paga: no · jobs: no</small></header><div>{data.checks.map((item:any)=><article key={item.name}><span className={`check-icon ${String(item.status).toLowerCase()}`}>{item.status==='READY'?<CheckCircle2/>:item.status==='DEGRADED'||item.status==='FAILED'?<AlertTriangle/>:<Wrench/>}</span><span><b>{LABELS[item.name]||item.name}</b><small>{item.status} · {item.latency_ms} ms</small></span></article>)}</div><button className="preflight-close" onClick={()=>setOpen(false)}>Ocultar diagnóstico</button></>}</div>}
  </div>
}
