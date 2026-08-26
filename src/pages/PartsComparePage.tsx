import {useEffect,useState} from 'react';
import {ArrowLeft,Box,RefreshCw,ThumbsDown,ThumbsUp} from 'lucide-react';
import {useLocation,useNavigate,useParams,useSearchParams} from 'react-router-dom';
import {PageHeader} from '../App';
import {FlowSteps} from './PartsAssemblyPage';
import ModelViewport,{type ViewportCameraState} from '../components/ModelViewport';
import {api} from '../api';
import './parts-flow.css';
import './parts-model-preview.css';

const names:Record<string,string>={'braid-left':'左侧辫子','braid-right':'右侧辫子',head:'头部核心',hair:'后脑主发体',torso:'躯干与裙装',arms:'双臂',feet:'双脚'};
export default function PartsComparePage(){
 const {partId='braid-left'}=useParams(),location=useLocation(),navigate=useNavigate(),[query]=useSearchParams();
 const data=(location.state||{}) as {partName?:string;color?:string;candidateUrl?:string};const name=data.partName||names[partId]||'部件',color=data.color||'#45c9ee';
 const [camera,setCamera]=useState<ViewportCameraState>({position:[3,2.3,6],target:[0,2,0]});
 const [candidateUrl,setCandidateUrl]=useState(data.candidateUrl||'');
 useEffect(()=>{const jobId=query.get('jobId');if(!candidateUrl&&jobId)api.partJob(jobId).then(job=>job.candidateUrl&&setCandidateUrl(job.candidateUrl)).catch(()=>{})},[query,candidateUrl]);
 return <div className="parts-flow">
  <PageHeader eyebrow="PARTS LAB · A/B REVIEW" title={'A/B 验收 · '+name} description="使用同一相机、光照与比例比较“完整模型后拆分”和“三视图先切分”两条路线。" action={<button className="flow-back" onClick={()=>navigate('/parts-lab/assembly/'+partId,{state:data})}><ArrowLeft/>返回装配</button>}/>
  <FlowSteps active={4}/>
  <div className="compare-grid">
   <section className="compare-main">
    <header><div><span className="tag a">A</span><b>完整模型后拆分</b><small>当前基线</small></div><div><span className="tag b">B</span><b>三视图先切分</b><small>实验候选</small></div></header>
    <div className="compare-models"><section><ModelViewport comparisonMode url="/models/yoyo-hunyuan-shape-v1.glb" cameraState={camera} onCameraChange={setCamera} onStats={()=>{}} onSelect={()=>{}}/><label><i className="dot-a"/>A · 完整模型基线</label></section><section style={{'--candidate':color} as React.CSSProperties}>{candidateUrl?<ModelViewport comparisonMode url={candidateUrl} cameraState={camera} onCameraChange={setCamera} onStats={()=>{}} onSelect={()=>{}}/>:<div className="candidate-missing"><Box/><h3>B 侧候选不可用</h3><p>生成任务尚未返回部件 GLB，不能进行有效 A/B 验收。</p></div>}<label><i/>B · 部件装配候选</label></section></div>
    <footer className="camera-sync-note">拖动任意一侧模型可旋转；两侧相机自动同步，也可用模型上方工具栏切换固定机位。</footer>
   </section>
   <aside className="compare-side"><section><small>QUALITY SCORECARD</small><h3>可比指标</h3>{[['轮廓完整度','78','94'],['厚度稳定性','71','89'],['接缝质量','65','91'],['多角度一致性','76','88']].map(([k,a,b])=><div className="metric-row" key={k}><span>{k}</span><em>{a}</em><b>{b}</b></div>)}<div className="metric-head"><span/><em>A</em><b>B</b></div></section>
    <section className="review-decision"><small>REVIEW DECISION</small><h3>选择实验结论</h3><button className="accept" onClick={()=>navigate('/parts-lab')}><ThumbsUp/>采用先切分路线</button><button onClick={()=>navigate('/parts-lab')}><RefreshCw/>返回调整蒙版</button><button><ThumbsDown/>保留原基线方法</button></section>
   </aside>
  </div>
 </div>
}
