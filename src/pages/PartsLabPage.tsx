import {useMemo,useState} from 'react';
import {Box,Check,CircleAlert,Eye,Layers3,Link2,LockKeyhole,Play,RotateCcw,Scissors,ShieldCheck,Sparkles,Unlink} from 'lucide-react';
import {PageHeader} from '../App';
import {useNavigate} from 'react-router-dom';
import frontUrl from '../../views/正面图.png';
import sideUrl from '../../views/左侧面图.png';
import backUrl from '../../views/背面图.png';
import './parts-lab.css';

type Part={id:string;name:string;short:string;color:string;confidence:number;views:number;overlap:number;note:string};
const parts:Part[]=[
 {id:'head',name:'头部核心',short:'头',color:'#ffb84d',confidence:96,views:3,overlap:9,note:'包含颈根隐藏插入段'},
 {id:'hair',name:'后脑主发体',short:'发',color:'#b075ff',confidence:92,views:3,overlap:7,note:'与头颅保持局部相交'},
 {id:'braid-left',name:'左侧辫子',short:'左辫',color:'#45c9ee',confidence:94,views:3,overlap:11,note:'首轮推荐 A/B 测试部件'},
 {id:'braid-right',name:'右侧辫子',short:'右辫',color:'#48dfae',confidence:94,views:3,overlap:11,note:'与左辫共享镜像约束'},
 {id:'torso',name:'躯干与裙装',short:'身',color:'#6c84ff',confidence:89,views:3,overlap:8,note:'保留完整基线锁定体积'},
 {id:'arms',name:'双臂',short:'臂',color:'#ff708f',confidence:72,views:2,overlap:12,note:'侧视图存在遮挡，需推断'},
 {id:'feet',name:'双脚',short:'脚',color:'#f2d55c',confidence:68,views:2,overlap:10,note:'裙底遮挡，作为低优先级'},
];
const views=[{id:'front',label:'正面',src:frontUrl},{id:'side',label:'左侧',src:sideUrl},{id:'back',label:'背面',src:backUrl}];
const masks:Record<string,Record<string,string>>={
 head:{front:'inset(4% 13% 38% 13% round 35%)',side:'inset(6% 17% 33% 17% round 36%)',back:'inset(4% 8% 38% 8% round 35%)'},
 hair:{front:'inset(3% 7% 34% 7% round 38%)',side:'inset(5% 14% 28% 16% round 38%)',back:'inset(3% 5% 32% 5% round 38%)'},
 'braid-left':{front:'inset(48% 70% 6% 4% round 40%)',side:'inset(46% 8% 5% 58% round 42%)',back:'inset(43% 70% 7% 4% round 40%)'},
 'braid-right':{front:'inset(48% 4% 6% 70% round 40%)',side:'inset(44% 58% 5% 8% round 42%)',back:'inset(43% 4% 7% 70% round 40%)'},
 torso:{front:'inset(52% 22% 5% 22% round 18%)',side:'inset(55% 28% 8% 26% round 18%)',back:'inset(51% 18% 4% 18% round 18%)'},
 arms:{front:'inset(55% 12% 13% 12% round 25%)',side:'inset(56% 22% 16% 20% round 25%)',back:'inset(54% 10% 14% 10% round 25%)'},
 feet:{front:'inset(88% 35% 2% 35% round 30%)',side:'inset(88% 38% 3% 32% round 30%)',back:'inset(88% 34% 2% 34% round 30%)'},
};

export default function PartsLabPage(){
 const navigate=useNavigate();
 const [selected,setSelected]=useState('braid-left'),[opacity,setOpacity]=useState(64),[overlap,setOverlap]=useState(11);
 const [linked,setLinked]=useState(true),[mode,setMode]=useState<'isolated'|'mask'|'source'>('isolated'),[running,setRunning]=useState(false),[queued,setQueued]=useState(false);
 const part=useMemo(()=>parts.find(p=>p.id===selected)!,[selected]);
 const choose=(p:Part)=>{setSelected(p.id);setOverlap(p.overlap)};
 const run=()=>{setRunning(true);setQueued(false);window.setTimeout(()=>{setRunning(false);setQueued(true);navigate('/parts-lab/generate/'+selected,{state:{partName:part.name,partShort:part.short,color:part.color,confidence:part.confidence,overlap}})},850)};
 return <div className="parts-lab">
  <PageHeader eyebrow="实验功能 · PARTS LAB" title="三视图部件切分实验" description="生成 3D 前锁定部件边界、连接重叠与跨视图一致性；完整模型只作为比例和装配基线。" action={<div className="lab-header-actions"><button><RotateCcw/>重置实验</button><button className="lab-run" onClick={run}><Play/>{running?'正在检查…':'运行 A/B 测试'}</button></div>}/>
  <div className="lab-stepper">{[['01','三视图对齐'],['02','部件切分'],['03','条件生成'],['04','基线装配'],['05','A/B 验收']].map(([n,label],i)=><div className={i===1?'active':i===0?'done':''} key={n}><span>{i===0?<Check/>:n}</span><b>{label}</b>{i<4&&<i/>}</div>)}</div>
  <div className="lab-grid">
   <aside className="lab-panel part-list"><header><div><small>PART MANIFEST</small><h2>部件清单</h2></div><button>自动建议 <Sparkles/></button></header><div className="manifest-summary"><span><b>{parts.length}</b> 个部件</span><span><b>3</b> 个连接锚点</span></div>
    <div className="parts-scroll">{parts.map(p=><button key={p.id} onClick={()=>choose(p)} className={selected===p.id?'active':''} style={{'--part-color':p.color} as React.CSSProperties}><span className="part-swatch">{p.short}</span><span className="part-copy"><b>{p.name}</b><small>{p.note}</small></span><span className={'part-score '+(p.confidence<75?'warn':'')}>{p.confidence}%</span></button>)}</div>
    <button className="add-part"><Scissors/>添加自定义部件</button>
   </aside>
   <section className="lab-workspace"><div className="canvas-toolbar"><div><button className={mode==='isolated'?'active':''} onClick={()=>setMode('isolated')}><Scissors/>拆分结果</button><button className={mode==='mask'?'active':''} onClick={()=>setMode('mask')}><Layers3/>蒙版叠加</button><button className={mode==='source'?'active':''} onClick={()=>setMode('source')}><Eye/>原始参考</button></div><div className="sync-control"><button onClick={()=>setLinked(!linked)} className={linked?'linked':''}>{linked?<Link2/>:<Unlink/>}{linked?'视图已同步':'独立视图'}</button><span>缩放 78%</span></div></div>
    <div className={'view-grid mode-'+mode}>{views.map(view=><figure key={view.id}><figcaption><b>{view.label}</b><span>{mode==='isolated'?'已提取':view.id==='side'&&part.views<3?'部分推断':'已对齐'}</span></figcaption><div className="reference-stage"><img className={mode==='isolated'?'isolated-part':''} style={mode==='isolated'?{clipPath:masks[selected][view.id]}:undefined} src={view.src} alt={view.label+(mode==='isolated'?'拆分部件':'参考图')}/>{mode==='mask'&&<div className="mask-overlay" style={{clipPath:masks[selected][view.id],background:part.color,opacity:opacity/100}}/>}{mode!=='isolated'&&<><span className="axis-x"/><span className="axis-y"/></>}{mode==='isolated'&&<div className="part-label" style={{borderColor:part.color}}><Scissors/>{part.name}</div>}</div><footer><span>{mode==='isolated'?'透明背景部件图':'统一画布'}</span><span><LockKeyhole/>坐标锁定</span></footer></figure>)}</div>
    <div className="canvas-status"><ShieldCheck/><div><b>跨视图一致性通过</b><span>主体高度偏差 2.4% · 中心线偏差 1.1% · 部件覆盖 {part.views}/3 视图</span></div><strong>{part.confidence}%</strong></div>
   </section>
   <aside className="lab-panel inspector"><header><div><small>PART SETTINGS</small><h2>{part.name}</h2></div><span style={{background:part.color}}>{part.short}</span></header>
    <section><h3>蒙版显示</h3><label><span>不透明度 <b>{opacity}%</b></span><input type="range" min="20" max="90" value={opacity} onChange={e=>setOpacity(+e.target.value)}/></label></section>
    <section><h3>连接与重叠</h3><label><span>隐藏重叠区 <b>{overlap}%</b></span><input type="range" min="3" max="18" value={overlap} onChange={e=>setOverlap(+e.target.value)}/><small>避免开放边界；装配时允许可控相交。</small></label><div className="socket-card"><Box/><div><b>{selected.includes('braid')?'hair_root_socket':selected==='head'?'neck_socket':'assembly_socket'}</b><small>自动锚点 · 等待 3D 校准</small></div></div></section>
    <section><h3>生成策略</h3><div className="strategy"><button className="active"><span/><div><b>部件独立生成</b><small>完整模型约束尺度与深度</small></div></button><button><span/><div><b>从基线局部重建</b><small>保留更多相邻几何上下文</small></div></button></div></section>
    <section className="checks"><h3>提交前检查</h3><p><Check/>三视图使用统一坐标</p><p><Check/>连接处保留 {overlap}% 重叠</p><p><Check/>完整基线已锁定</p>{part.views<3&&<p className="warning"><CircleAlert/>遮挡视图将标记为推断</p>}</section>
    <button className="inspector-run" onClick={run}><Sparkles/>{running?'准备条件图…':'生成该部件候选'}</button>
   </aside>
  </div>
  {queued&&<div className="lab-toast"><Check/><div><b>实验候选已加入队列</b><span>{part.name}将与完整基线做同机位 A/B 对比。</span></div><button onClick={()=>setQueued(false)}>关闭</button></div>}
 </div>
}
