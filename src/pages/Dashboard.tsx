import {useEffect,useMemo,useState} from 'react';
import {Grid2X2,List,Plus,RefreshCw,Trash2} from 'lucide-react';
import {useNavigate} from 'react-router-dom';
import {api} from '../api';
import type {Project} from '../types';
import {Button,PageHeader,StageBar,StatusBadge} from '../App';
import './dashboard.css';

const next=(p:Project)=>p.status==='draft'||p.status==='needs_input'?`/create?id=${p.id}`:p.status==='awaiting_confirmation'?`/plan/${p.id}`:p.status==='ready_for_review'||p.status.startsWith('completed')?`/review/${p.id}`:p.currentJobId?`/jobs/${p.currentJobId}`:`/validation/${p.id}`;

export default function Dashboard(){
 const [items,setItems]=useState<Project[]>([]),[filter,setFilter]=useState('all'),[error,setError]=useState(''),[deleting,setDeleting]=useState('');
 const nav=useNavigate();
 const load=()=>api.projects().then(setItems).catch(e=>setError(e.message));
 useEffect(()=>{void load()},[]);
 const remove=async(p:Project)=>{if(!window.confirm(`确定删除任务“${p.name}”吗？此操作不可撤销。`))return;setDeleting(p.id);setError('');try{await api.deleteProject(p.id);setItems(current=>current.filter(item=>item.id!==p.id))}catch(e){setError((e as Error).message)}finally{setDeleting('')}};
 const visible=useMemo(()=>items.filter(p=>filter==='all'||(filter==='active'?['queued','generating_geometry','rendering_review'].includes(p.status):filter==='waiting'?['draft','needs_input','awaiting_confirmation','awaiting_geometry_confirmation','ready_for_review'].includes(p.status):filter==='done'?p.status.startsWith('completed'):p.status==='failed')),[items,filter]);
 return <>
  <PageHeader eyebrow="生产总览" title="欢迎回来，三维工匠" description="追踪每个 2D→3D 项目，并从当前阶段继续。" action={<Button onClick={()=>nav('/create')}><Plus/> 新建项目</Button>}/>
  <div className="toolbar"><div className="tabs">{[['all','全部项目'],['active','处理中'],['waiting','等待中'],['done','已完成'],['failed','异常']].map(([k,l])=><button className={filter===k?'active':''} onClick={()=>setFilter(k)} key={k}>{l}<em>{k==='all'?items.length:''}</em></button>)}</div><div className="toolbar-actions"><Grid2X2/><List/><RefreshCw onClick={load}/></div></div>
  {error&&<div className="notice danger">API 未连接：{error}。请运行 <code>npm run api</code>。</div>}
  <div className="project-grid">{visible.map(p=><article className="project-card" key={p.id} onClick={()=>nav(next(p))}>
   <button className="project-delete" type="button" title="删除任务" aria-label={`删除任务 ${p.name}`} disabled={deleting===p.id} onClick={e=>{e.stopPropagation();void remove(p)}}><Trash2/>{deleting===p.id?'删除中':'删除'}</button>
   <div className="thumb">{p.thumbnailUrl?<img src={p.thumbnailUrl}/>:<div className="thumb-fallback"><span>{p.name.slice(0,2)}</span></div>}<StatusBadge status={p.status}/></div>
   <div className="project-body"><h3>{p.name}</h3><span className="backend">✦ {p.actualBackend||'Hunyuan3D 2.1'}</span><small>当前阶段</small><strong>{p.currentStage?.replaceAll('_',' ')||'等待开始'}</strong><div className="progress-label">已通过 <b>{p.passedStages}</b> / {p.totalStages} 个阶段</div><StageBar passed={p.passedStages} total={p.totalStages}/><footer><time>{new Date(p.updatedAt).toLocaleString('zh-CN')}</time><span>继续处理 →</span></footer></div>
  </article>)}</div>
  {!visible.length&&!error&&<div className="empty"><Plus/><h2>还没有匹配的项目</h2><p>创建第一个项目，上传正面参考图开始。</p><Button onClick={()=>nav('/create')}>新建项目</Button></div>}
 </>
}
