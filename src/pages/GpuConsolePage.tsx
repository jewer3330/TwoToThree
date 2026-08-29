import {useCallback, useEffect, useState} from 'react';
import {Activity, Cpu, Gauge, HardDrive, Pause, Play, Plus, RefreshCw, Server, Trash2, X} from 'lucide-react';
import {api} from '../api';
import type {GpuHost,GpuQueueView,GpuOverview} from '../types';
import {PageHeader} from '../App';

const CAP_LABELS: Record<string,string> = {
  hunyuan3d:'Hunyuan 3D', hunyuan3dMultiview:'多视图', sf3d:'SF3D', triposr:'TripoSR',
  blender:'Blender', blenderRefinement:'精修', blenderStlExport:'STL 导出',
};
const Q_STATUS: Record<string,string> = {queued:'排队中',dispatched:'已派发',running:'运行中',awaiting_geometry_confirmation:'等待几何确认',completed:'完成',failed:'失败',cancelled:'已取消'};

function MemBar({used,total}:{used?:number;total?:number}){
  if(!used||!total)return <div className="gpu-bar"><span className="gpu-bar-fill none"/></div>;
  const pct=Math.min(100,Math.round(used/total*100));
  return <div className="gpu-bar"><span className="gpu-bar-fill" style={{width:`${pct}%`}}/></div>;
}

function HostCard({host,onAction}:{host:GpuHost;onAction:(t:'probe'|'toggle'|'delete',h:GpuHost)=>void}){
  const s=host.status||{};
  const online=!!s.online;
  const memUsedPct=s.memTotal&&s.memUsed?Math.round(s.memUsed/s.memTotal*100):0;
  return <div className={`gpu-host ${online?'online':'offline'} ${host.enabled?'':'disabled'}`}>
    <div className="gpu-host-head">
      <span className={`status-light ${online?'ok':''}`}/>
      <b>{host.name}</b>
      <span className="gpu-host-ip">{host.host}</span>
      <div className="gpu-host-actions">
        <button title="重新探测" onClick={()=>onAction('probe',host)}><RefreshCw size={14}/></button>
        <button title={host.enabled?'禁用':'启用'} onClick={()=>onAction('toggle',host)}>{host.enabled?<Pause size={14}/>:<Play size={14}/>}</button>
        <button title="删除" className="danger" onClick={()=>onAction('delete',host)}><Trash2 size={14}/></button>
      </div>
    </div>
    <div className="gpu-host-meta">
      {online?<><Cpu size={14}/> <b>{s.gpu||'未知 GPU'}</b></>:<span className="muted">离线</span>}
    </div>
    {online&&s.memTotal&&<>
      <div className="gpu-host-stat"><Gauge size={14}/> 显存 <span>{s.memUsed} / {s.memTotal} MB</span> <b>{memUsedPct}%</b></div>
      <MemBar used={s.memUsed} total={s.memTotal}/>
    </>}
    {online&&s.diskFree!=null&&<div className="gpu-host-stat"><HardDrive size={14}/> 磁盘剩余 <span>{s.diskFree} GB</span></div>}
    <div className="gpu-host-caps">{(Object.entries(s.caps||{})).filter(([,v])=>v).map(([k])=><span key={k} className="cap-badge">{CAP_LABELS[k]||k}</span>)}
      {!Object.values(s.caps||{}).some(Boolean)&&online&&<span className="muted">无能力</span>}</div>
    <div className="gpu-host-foot">
      <span>运行 <b>{s.runningJobs||0}</b> · 并发 {host.maxConcurrentJobs}</span>
      <span className="muted">{s.lastProbeAt?new Date(s.lastProbeAt).toLocaleTimeString():'未探测'}</span>
    </div>
    {s.lastError&&<div className="gpu-host-err">{s.lastError}</div>}
  </div>;
}

const EMPTY_HOST={name:'',host:'',user:'d0993',key:'',root:'D:\\print3d\\TwoToThree',ext:'D:\\print3d',work:'D:\\print3d\\work',maxConcurrentJobs:1,enabled:true,labels:''};

export default function GpuConsolePage(){
  const [hosts,setHosts]=useState<GpuHost[]>([]);
  const [queue,setQueue]=useState<GpuQueueView|null>(null);
  const [overview,setOverview]=useState<GpuOverview|null>(null);
  const [adding,setAdding]=useState(false);
  const [form,setForm]=useState(EMPTY_HOST);
  const [busy,setBusy]=useState(false);

  const refresh=useCallback(async()=>{
    try{const [h,q,o]=await Promise.all([api.gpuHosts(),api.gpuQueue(),api.gpuOverview()]);setHosts(h);setQueue(q);setOverview(o);}catch(e){console.error(e);}
  },[]);
  useEffect(()=>{refresh();const t=setInterval(refresh,10000);return()=>clearInterval(t);},[refresh]);

  const onAction=async(t:'probe'|'toggle'|'delete',h:GpuHost)=>{
    if(t==='delete'&&!confirm(`删除主机 ${h.name}？`))return;
    setBusy(true);
    try{
      if(t==='probe')await api.gpuProbeHost(h.id);
      if(t==='toggle')await api.gpuToggleHost(h.id);
      if(t==='delete')await api.gpuDeleteHost(h.id);
      await refresh();
    }catch(e){alert(`操作失败：${e}`);}finally{setBusy(false);}
  };
  const addHost=async()=>{
    setBusy(true);
    try{
      const body={...form,labels:form.labels.split(/[,，\s]+/).filter(Boolean),maxConcurrentJobs:Number(form.maxConcurrentJobs)||1};
      await api.gpuAddHost(body);setAdding(false);setForm(EMPTY_HOST);await refresh();
    }catch(e){alert(`添加失败：${e}`);}finally{setBusy(false);}
  };
  const togglePause=async()=>{
    if(!queue)return;
    try{await api.gpuSetPaused(!queue.paused);await refresh();}catch(e){alert(String(e));}
  };

  const F=({k,label,placeholder}:{k:keyof typeof EMPTY_HOST;label:string;placeholder?:string})=>(
    <label className="gpu-field">{label}
      <input value={form[k] as string} placeholder={placeholder||label} onChange={e=>setForm({...form,[k]:e.target.value})}/>
    </label>);

  return <div className="page gpu-console">
    <PageHeader eyebrow="GPU 集群" title="算力控制面板" description="GPU 主机状态、任务队列与调度。新增机器只需在下方注册一条配置。" action={
      <button className="button" onClick={()=>setAdding(!adding)} disabled={busy}>{adding?<X size={16}/>:<Plus size={16}/>}{adding?'取消':'注册主机'}</button>}/>

    <div className="gpu-stats">
      <div className="gpu-stat"><Server size={18}/><b>{overview?.hostCount||0}</b><span>主机</span></div>
      <div className="gpu-stat ok"><Cpu size={18}/><b>{overview?.online||0}</b><span>在线</span></div>
      <div className="gpu-stat"><Activity size={18}/><b>{overview?.gpuMemUsed||0} / {overview?.gpuMemTotal||0}</b><span>显存 MB</span></div>
      <div className="gpu-stat"><Gauge size={18}/><b>{overview?.runningJobs||0}</b><span>运行中</span></div>
      <div className="gpu-stat"><Activity size={18}/><b>{queue?.counts.queued||0}</b><span>排队</span></div>
    </div>

    {adding&&<div className="gpu-add-form">
      <h3>注册新 GPU 主机</h3>
      <div className="gpu-form-grid">
        <F k="name" label="名称" placeholder="GPU-3 4080"/>
        <F k="host" label="IP / 主机" placeholder="100.69.5.47"/>
        <F k="user" label="SSH 用户"/>
        <F k="key" label="SSH 私钥路径" placeholder="/run/secrets/gpu_key"/>
        <F k="root" label="仓库目录"/>
        <F k="ext" label="外部根目录"/>
        <F k="work" label="工作目录"/>
        <F k="labels" label="标签" placeholder="main,备用"/>
      </div>
      <button className="button primary" onClick={addHost} disabled={busy||!form.host}>添加</button>
    </div>}

    <div className="gpu-hosts-grid">{hosts.map(h=><HostCard key={h.id} host={h} onAction={onAction}/>)}
      {!hosts.length&&<div className="empty"><Server/><h3>尚未注册 GPU 主机</h3><p>点击右上角「注册主机」添加第一台算力机器（如 D:\print3d 已装环境的 Windows 机）。</p></div>}
    </div>

    <div className="gpu-queue">
      <div className="gpu-queue-head">
        <h3>任务队列</h3>
        <button className="button secondary" onClick={togglePause} disabled={!queue}>{queue?.paused?<Play size={16}/>:<Pause size={16}/>}{queue?.paused?'恢复调度':'暂停调度'}</button>
      </div>
      <div className="gpu-queue-cols">
        <div className="gpu-queue-col"><h4>排队 {queue?.counts.queued||0}</h4>{(queue?.queued||[]).map(j=><div key={j.id} className="gpu-q-item"><b>{j.id.slice(-8)}</b><span>{Q_STATUS[j.status]||j.status}</span>{j.hostName&&<i>{j.hostName}</i>}</div>)}
          {!(queue?.queued||[]).length&&<p className="muted">暂无排队任务</p>}</div>
        <div className="gpu-queue-col"><h4>运行中 {queue?.counts.running||0}</h4>{(queue?.running||[]).map(j=><div key={j.id} className="gpu-q-item"><b>{j.id.slice(-8)}</b><span>{Q_STATUS[j.status]||j.status}</span>{j.hostName&&<i>{j.hostName}</i>}</div>)}
          {!(queue?.running||[]).length&&<p className="muted">暂无运行任务</p>}</div>
        <div className="gpu-queue-col"><h4>最近任务</h4>{(queue?.recent||[]).map(j=><div key={j.id} className={`gpu-q-item ${j.status}`}><b>{j.id.slice(-8)}</b><span>{Q_STATUS[j.status]||j.status}</span>{j.hostName&&<i>{j.hostName}</i>}{j.error_summary&&<small>{j.error_summary.slice(0,60)}</small>}</div>)}
          {!(queue?.recent||[]).length&&<p className="muted">暂无记录</p>}</div>
      </div>
    </div>
  </div>;
}
