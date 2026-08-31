import {useEffect,useState} from 'react';
import {ArrowLeft,Box,Check,Clock3,Cpu,FileImage,Layers3,LoaderCircle,Play,ShieldCheck,Sparkles} from 'lucide-react';
import {useLocation,useNavigate,useParams} from 'react-router-dom';
import {PageHeader} from '../App';
import {api} from '../api';
import frontUrl from '../../views/正面图.png';
import sideUrl from '../../views/左侧面图.png';
import backUrl from '../../views/背面图.png';
import './parts-generate.css';

const names:Record<string,string>={head:'头部核心',hair:'后脑主发体','braid-left':'左侧辫子','braid-right':'右侧辫子',torso:'躯干与裙装',arms:'双臂',feet:'双脚'};
const clips:Record<string,string[]>={head:['inset(4% 13% 38% 13% round 35%)','inset(6% 17% 33% 17% round 36%)','inset(4% 8% 38% 8% round 35%)'],hair:['inset(3% 7% 34% 7% round 38%)','inset(5% 14% 28% 16% round 38%)','inset(3% 5% 32% 5% round 38%)'],'braid-left':['inset(48% 70% 6% 4% round 40%)','inset(46% 8% 5% 58% round 42%)','inset(43% 70% 7% 4% round 40%)'],'braid-right':['inset(48% 4% 6% 70% round 40%)','inset(44% 58% 5% 8% round 42%)','inset(43% 4% 7% 70% round 40%)'],torso:['inset(52% 22% 5% 22% round 18%)','inset(55% 28% 8% 26% round 18%)','inset(51% 18% 4% 18% round 18%)'],arms:['inset(55% 12% 13% 12% round 25%)','inset(56% 22% 16% 20% round 25%)','inset(54% 10% 14% 10% round 25%)'],feet:['inset(88% 35% 2% 35% round 30%)','inset(88% 38% 3% 32% round 30%)','inset(88% 34% 2% 34% round 30%)']};
const partJobRequests=new Map<string,ReturnType<typeof api.createPartJob>>();
export default function PartsGeneratePage(){
 const {partId='braid-left'}=useParams(),location=useLocation(),navigate=useNavigate();
 const state=(location.state||{}) as {partName?:string;color?:string;confidence?:number;overlap?:number};
 const name=state.partName||names[partId]||'自定义部件',color=state.color||'#45c9ee';
 const [job,setJob]=useState<{id:string;status:string;progress:number;message:string;candidateUrl?:string;logs:string[];error?:string}|null>(null),[error,setError]=useState('');
 const running=!job||!['completed','failed'].includes(job.status),progress=job?.progress||2;
 useEffect(()=>{let disposed=false,timer=0;const key=partId+':'+(state.overlap||11);let request=partJobRequests.get(key);if(!request){request=api.createPartJob({partId,overlap:state.overlap||11,quality:'standard'});partJobRequests.set(key,request)}request.then(created=>{if(disposed)return;setJob(created);timer=window.setInterval(()=>api.partJob(created.id).then(next=>{if(disposed)return;setJob(next);if(['completed','failed'].includes(next.status))window.clearInterval(timer)}).catch(e=>{setError(e.message);window.clearInterval(timer)}),2000)}).catch(e=>setError(e.message));return()=>{disposed=true;window.clearInterval(timer)}},[partId]);
 return <div className="parts-generate">
  <PageHeader eyebrow="PARTS LAB · CONDITION GENERATION" title={'条件生成 · '+name} description="使用三视图部件条件图生成独立候选；完整模型只提供尺度、深度和装配锚点约束。" action={<button className="pg-back" onClick={()=>navigate('/parts-lab')}><ArrowLeft/>返回调整蒙版</button>}/>
  <div className="pg-stepper">{['三视图对齐','部件切分','条件生成','基线装配','A/B 验收'].map((label,i)=><div className={i<2?'done':i===2?'active':''} key={label}><span>{i<2?<Check/>:'0'+(i+1)}</span><b>{label}</b></div>)}</div>
  <div className="pg-grid">
   <section className="pg-main">
    <div className="pg-job-head"><div className="pg-icon" style={{background:color}}><Sparkles/></div><div><small>REAL GPU JOB · {job?.id||partId.toUpperCase()}</small><h2>{job?.status==='completed'?'候选部件生成完成':job?.status==='failed'?'候选生成失败':'正在生成真实部件候选'}</h2><p>{error||job?.error||job?.message||'正在向本地 Hunyuan3D-2mv 提交任务…'}</p></div><span className={job?.status==='completed'?'ready':'running'}>{job?.status==='completed'?<><Check/>已完成</>:<><LoaderCircle/>运行中</>}</span></div>
    <div className="pg-progress"><header><span>真实生成进度</span><b>{progress}%</b></header><div><i style={{width:progress+'%'}}/></div><footer><span>当前：{job?.message||'创建本地 GPU 任务'}</span><span>预计 3–8 分钟</span></footer></div>
    <h3>拆分后的三视图条件图</h3><div className="pg-views">{[[frontUrl,'正面'],[sideUrl,'左侧'],[backUrl,'背面']].map(([src,label],i)=><figure key={label}><img className="pg-isolated" style={{clipPath:(clips[partId]||clips['braid-left'])[i]}} src={src}/><figcaption><span><FileImage/>{label}部件</span><b><Check/>已提取</b></figcaption></figure>)}</div>
    <div className="pg-log"><header><b>真实任务日志</b><span>{job?.status||'connecting'}</span></header><p><time>输入</time><Check/>已应用 {state.overlap||11}% 隐藏重叠区</p>{job?.logs?.slice(-8).map((line,i)=><p key={i}><time>{String(i+1).padStart(2,'0')}</time><Check/>{line}</p>)}{running&&<p className="current"><time>GPU</time><LoaderCircle/>{job?.message||'连接任务…'}</p>}</div>
   </section>
   <aside className="pg-side">
    <section><small>GENERATION CONTRACT</small><h3>生成约束</h3><p><Layers3/><span>生成范围<b>{name}</b></span></p><p><Box/><span>装配参照<b>完整模型基线</b></span></p><p><ShieldCheck/><span>视图置信度<b>{state.confidence||94}%</b></span></p><p><Cpu/><span>候选数量<b>2 个</b></span></p></section>
    <section><small>A/B DESIGN</small><h3>实验对照</h3><article><em>A</em><div><b>完整模型后拆分</b><span>当前 Hunyuan 基线方法</span></div></article><article className="candidate"><em>B</em><div><b>三视图先切分</b><span>当前部件条件生成</span></div></article><p className="pg-metrics">统一机位比较轮廓、厚度、接缝与多角度稳定性。</p></section>
    <button className="pg-start" disabled={job?.status!=='completed'||!job.candidateUrl} onClick={()=>navigate('/parts-lab/assembly/'+partId+'?jobId='+job?.id,{state:{...state,partName:name,color,candidateUrl:job?.candidateUrl}})}><Play/>{job?.status==='completed'?'打开真实候选模型':'等待真实 GLB'} </button>
    <span className="pg-note"><Clock3/>关闭页面不会终止本地推理；刷新页面后需重新进入任务。</span>
   </aside>
  </div>
 </div>
}
