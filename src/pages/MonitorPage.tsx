import {useCallback,useEffect,useRef,useState} from 'react';
import {AlertCircle,Box,CheckCircle2,Clock,File,PauseCircle,RefreshCw,Terminal} from 'lucide-react';
import {useNavigate,useParams} from 'react-router-dom';
import {api} from '../api';
import type {Job} from '../types';
import {Button,PageHeader} from '../App';
import ModelViewport from '../components/ModelViewport';

const eventNames=['stage.log','stage.output','stage.started','stage.completed','job.status','job.completed','job.failed'];

export default function MonitorPage(){
 const {jobId=''}=useParams(),nav=useNavigate();
 const [job,setJob]=useState<Job>(),[connected,setConnected]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const logRef=useRef<HTMLDivElement>(null),loading=useRef(false);
 const load=useCallback(async()=>{if(loading.current)return;loading.current=true;try{setJob(await api.job(jobId))}finally{loading.current=false}},[jobId]);
 useEffect(()=>{void load();const es=new EventSource(`/api/jobs/${jobId}/events`);const refresh=()=>void load();es.onopen=()=>setConnected(true);es.onerror=()=>setConnected(false);eventNames.forEach(name=>es.addEventListener(name,refresh));const fallback=window.setInterval(refresh,3000);return()=>{eventNames.forEach(name=>es.removeEventListener(name,refresh));window.clearInterval(fallback);es.close()}},[jobId,load]);
 useEffect(()=>{if(logRef.current)logRef.current.scrollTop=logRef.current.scrollHeight},[job?.logs]);
 const confirm=async()=>{if(!job)return;setBusy(true);setError('');try{setJob(await api.confirmGeometry(job.id))}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 if(!job)return <div className="loading"><span/>正在连接任务…</div>;
 const passed=job.stages.filter(s=>s.status==='passed'||s.status==='skipped').length;
 const awaiting=job.status==='awaiting_geometry_confirmation';
 const baseline=job.artifacts.filter(a=>a.type==='glb'&&a.label==='baseline.glb').at(-1);
 const renders=job.artifacts.filter(a=>a.type==='render').slice(-4);
 return <><PageHeader eyebrow={`Attempt ${job.attempt} · ${connected?'实时连接':'轮询同步'}`} title={awaiting?'几何粗模确认':'任务执行监控'} description={`实际后端：${job.actualBackend||'等待分配'} · 已通过 ${passed}/${job.stages.length} 个阶段`}/>
 {awaiting&&<div className="notice success">几何生成和厚度门禁已通过。请旋转检查体积、侧面与背面；确认后才会生成评审视图并进入 Comment 评审。</div>}
 {error&&<div className="notice danger">{error}</div>}
 <div className="monitor-layout"><aside className="panel timeline"><h2>任务阶段</h2>{job.stages.map(s=><div className={`timeline-step ${s.status}`} key={s.id}>{s.status==='passed'?<CheckCircle2/>:s.status==='running'?<RefreshCw/>:s.status==='failed'?<AlertCircle/>:<Clock/>}<div><b>{s.label}</b><span>{s.status}</span></div><time>{s.duration||'--:--'}</time></div>)}<div className="passed-count">已通过 <b>{passed}</b> / {job.stages.length} 阶段</div></aside>
 <section className="monitor-center">{renders.length?<div className="render-grid">{renders.map(a=><figure key={a.id}><img src={a.url} alt={a.label}/><figcaption>{a.label}</figcaption></figure>)}</div>:awaiting&&baseline?<ModelViewport url={baseline.url} onStats={()=>{}} onSelect={()=>{}}/>:<div className="render-grid"><div className="render-wait"><Box/><b>{job.currentStage?.replaceAll('_',' ')}</b><p>阶段产物通过后会显示；关闭页面不会终止任务。</p></div></div>}</section>
 <aside className="monitor-right"><div className="panel stage-card"><small>当前阶段</small><h2>{job.currentStage?.replaceAll('_',' ')||job.status}</h2><div className="pulse-line"><i/></div><span>资源队列：单 GPU 串行</span></div><div className="panel log-panel"><h2><Terminal/> 实时日志</h2><div ref={logRef}>{job.logs.map((l,i)=><p key={i}>{l}</p>)}</div></div><div className="panel artifacts"><h2>输出产物</h2>{job.artifacts.map(a=><a href={a.url} key={a.id} download><File/><span>{a.label}<small>{(a.byteSize/1048576).toFixed(2)} MB</small></span></a>)}</div></aside></div>
 <div className="sticky-actions"><Button kind="secondary" onClick={()=>void load()}><RefreshCw/>刷新快照</Button><span>{awaiting?'等待你的几何确认':connected?'SSE 实时事件已连接':'SSE 断开，每 3 秒自动同步'}</span>{awaiting&&<><Button kind="danger" onClick={()=>api.cancel(job.id).then(setJob)}><PauseCircle/>拒绝并停止</Button><Button disabled={busy} onClick={confirm}><CheckCircle2/>{busy?'正在继续…':'确认并生成评审视图'}</Button></>}{!awaiting&&!['completed','failed','cancelled'].includes(job.status)&&<Button kind="danger" onClick={()=>api.cancel(job.id).then(setJob)}><PauseCircle/>取消任务</Button>}{job.status==='cancelled'&&<Button kind="primary" onClick={()=>{if(window.confirm('该任务已取消，是否使用相同素材与配置重新开始（新 Attempt）？'))api.retry(job.id).then(j=>nav(`/jobs/${j.id}`))}}><RefreshCw/>重新开始</Button>}{job.status==='failed'&&<Button onClick={()=>api.retry(job.id).then(j=>nav(`/jobs/${j.id}`))}>重试（新 Attempt）</Button>}{job.status==='completed'&&<Button onClick={()=>nav(`/review/${job.projectId}`)}>进入模型预览与 Comment 评审</Button>}</div></>;
}
