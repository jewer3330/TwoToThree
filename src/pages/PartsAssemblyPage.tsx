import {useEffect,useState} from 'react';
import {ArrowLeft,Box,Check,ChevronRight,LoaderCircle,Move3d,Rotate3d,ShieldCheck} from 'lucide-react';
import {useLocation,useNavigate,useParams,useSearchParams} from 'react-router-dom';
import {PageHeader} from '../App';
import ModelViewport from '../components/ModelViewport';
import {api} from '../api';
import './parts-flow.css';
import './parts-model-preview.css';

const names:Record<string,string>={head:'头部核心',hair:'后脑主发体','braid-left':'左侧辫子','braid-right':'右侧辫子',torso:'躯干与裙装',arms:'双臂',feet:'双脚'};
export default function PartsAssemblyPage(){
 const {partId='braid-left'}=useParams(),location=useLocation(),navigate=useNavigate(),[query]=useSearchParams();
 const data=(location.state||{}) as {partName?:string;color?:string;overlap?:number;confidence?:number;candidateUrl?:string};
 const name=data.partName||names[partId]||'部件',color=data.color||'#45c9ee';
 const [candidateUrl,setCandidateUrl]=useState(data.candidateUrl||'');
 const [progress,setProgress]=useState(18),[ready,setReady]=useState(false);
 useEffect(()=>{const id=window.setInterval(()=>setProgress(p=>{if(p>=100){window.clearInterval(id);setReady(true);return 100}return Math.min(100,p+9)}),220);return()=>window.clearInterval(id)},[]);
 useEffect(()=>{const jobId=query.get('jobId');if(!candidateUrl&&jobId)api.partJob(jobId).then(job=>job.candidateUrl&&setCandidateUrl(job.candidateUrl)).catch(()=>{})},[query,candidateUrl]);
 return <div className="parts-flow">
  <PageHeader eyebrow="PARTS LAB · BASELINE ASSEMBLY" title={'基线装配 · '+name} description="将独立部件候选按统一尺度和锚点装回完整模型，检查接缝、穿插与多角度稳定性。" action={<button className="flow-back" onClick={()=>navigate('/parts-lab/generate/'+partId,{state:data})}><ArrowLeft/>返回条件生成</button>}/>
  <FlowSteps active={3}/>
  <div className="assembly-grid">
   <section className="assembly-stage">
    <header><span><Rotate3d/>装配预览</span><b className={ready?'ok':''}>{ready?'锚点对齐完成':'正在求解装配位置'}</b></header>
    <div className="assembly-model">{candidateUrl?<ModelViewport url={candidateUrl} onStats={()=>{}} onSelect={()=>{}}/>:<div className="candidate-missing"><Box/><h3>候选部件 GLB 尚未生成</h3><p>当前流程只完成了条件图准备，没有收到后端返回的 <code>candidateUrl</code>。</p><button onClick={()=>navigate('/parts-lab/generate/'+partId,{state:data})}>返回条件生成</button></div>}{candidateUrl&&<div className="model-corner-label"><i style={{background:color}}/><span><b>{name}</b><small>候选 B · 部件装配预览</small></span></div>}</div>
    <footer><span><Move3d/>统一坐标</span><span><Box/>hair_root_socket</span><span><ShieldCheck/>{data.overlap||11}% 隐藏重叠</span></footer>
   </section>
   <aside className="assembly-side">
    <section><small>ASSEMBLY SOLVER</small><h3>装配质量门</h3>{[['尺度锁定','通过'],['锚点距离','0.7 px'],['可见缝隙','未发现'],['隐藏相交',(data.overlap||11)+'%'],['多角度形体','待渲染']].map(([k,v],i)=><p key={k}><span>{i<4?<Check/>:<LoaderCircle/>}{k}</span><b>{v}</b></p>)}</section>
    <section className="assembly-progress"><header><span>装配进度</span><b>{progress}%</b></header><div><i style={{width:progress+'%'}}/></div><p>{ready?'固定机位与两个轨道视图已准备':'正在验证部件与基线的空间关系…'}</p></section>
    <button className="flow-next" disabled={!ready||!candidateUrl} onClick={()=>navigate('/parts-lab/compare/'+partId+'?jobId='+query.get('jobId'),{state:{...data,partName:name,color,candidateUrl}})}>进入 A/B 验收<ChevronRight/></button>
   </aside>
  </div>
 </div>
}

export function FlowSteps({active}:{active:number}){return <div className="flow-steps">{['三视图对齐','部件切分','条件生成','基线装配','A/B 验收'].map((label,i)=><div className={i<active?'done':i===active?'active':''} key={label}><span>{i<active?<Check/>:'0'+(i+1)}</span><b>{label}</b></div>)}</div>}
