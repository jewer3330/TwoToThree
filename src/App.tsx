import {Activity, Boxes, ChevronRight, Cpu, FolderKanban, Gauge, HardDrive, Home, Layers3, Menu, Plus, Search, Settings, Sparkles} from 'lucide-react';
import {NavLink, Navigate, Route, Routes, useLocation} from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import CreateProject from './pages/CreateProject';
import ValidationPage from './pages/ValidationPage';
import PlanPage from './pages/PlanPage';
import MonitorPage from './pages/MonitorPage';
import ReviewPage from './pages/ReviewPage';
import RefinementConfigPage from './pages/RefinementConfigPage';
import RefinementMonitorPage from './pages/RefinementMonitorPage';
import RevisionPlanPage from './pages/RevisionPlanPage';
import RevisionMonitorPage from './pages/RevisionMonitorPage';

const nav=[['/',Home,'工作台'],['/projects',FolderKanban,'项目管理'],['/assets',Layers3,'素材管理'],['/queue',Activity,'任务队列'],['/library',Boxes,'模型 / 资产库'],['/settings',Settings,'系统设置']] as const;
function Placeholder({title}:{title:string}){return <div className="empty"><Boxes/><h2>{title}</h2><p>该入口将在后续版本开放，当前 MVP 聚焦完整转换与验收流程。</p></div>}
function Shell(){const loc=useLocation(); const focused=/\/(create|validation|plan|jobs|review|refinement)\//.test(loc.pathname);return <div className={`shell ${focused?'focused':''}`}>
  {!focused&&<aside className="sidebar"><div className="brand"><span className="brandmark"><Sparkles/></span><div><b>2D→3D Studio</b><small>本地生产工作台</small></div></div><nav>{nav.map(([to,I,label])=><NavLink key={to} to={to} end={to==='/' }><I/>{label}</NavLink>)}</nav><div className="sidebar-foot"><span className="health-dot"/> 本地环境 · 管理员</div></aside>}
  <section className="workspace"><header className="topbar"><div className="mobile-brand"><Menu/> 2D→3D Studio</div><div className="search"><Search/><span>搜索项目、任务或素材</span><kbd>⌘ K</kbd></div><div className="system-strip"><span><Activity/> 系统 <b>正常</b></span><span><Cpu/> GPU <b>就绪</b></span><span><Gauge/> CPU <b>24%</b></span><span><HardDrive/> 存储 <b>68%</b></span></div></header><main><Routes>
    <Route path="/" element={<Dashboard/>}/><Route path="/create" element={<CreateProject/>}/><Route path="/validation/:projectId" element={<ValidationPage/>}/><Route path="/plan/:projectId" element={<PlanPage/>}/><Route path="/jobs/:jobId" element={<MonitorPage/>}/><Route path="/review/:projectId" element={<ReviewPage/>}/>
    <Route path="/refinement/new/:versionId" element={<RefinementConfigPage/>}/><Route path="/refinement/jobs/:jobId" element={<RefinementMonitorPage/>}/>
    <Route path="/revisions/new/:versionId" element={<RevisionPlanPage/>}/><Route path="/revisions/:revisionId" element={<RevisionMonitorPage/>}/>
    <Route path="/projects" element={<Dashboard/>}/><Route path="/assets" element={<Placeholder title="素材管理"/>}/><Route path="/queue" element={<Placeholder title="任务队列"/>}/><Route path="/library" element={<Placeholder title="模型 / 资产库"/>}/><Route path="/settings" element={<Placeholder title="系统设置"/>}/><Route path="*" element={<Navigate to="/"/>}/>
  </Routes></main></section>
</div>}
export default function App(){return <Shell/>}

export function PageHeader({eyebrow,title,description,action}:{eyebrow?:string;title:string;description?:string;action?:React.ReactNode}){return <div className="page-header"><div>{eyebrow&&<span className="eyebrow">{eyebrow}</span>}<h1>{title}</h1>{description&&<p>{description}</p>}</div>{action}</div>}
export function Button({children,kind='primary',...props}:React.ButtonHTMLAttributes<HTMLButtonElement>&{kind?:'primary'|'secondary'|'danger'|'success'}){return <button className={`button ${kind}`} {...props}>{children}<ChevronRight size={16}/></button>}
export function StatusBadge({status}:{status:string}){const map:Record<string,string>={draft:'草稿',validating:'检查中',needs_input:'等待素材',awaiting_confirmation:'等待方案确认',awaiting_geometry_confirmation:'等待几何确认',queued:'排队中',generating_geometry:'生成中',rendering_review:'渲染中',ready_for_review:'待验收',completed:'已完成',completed_with_notes:'有条件完成',failed:'异常',cancelled:'已取消'};return <span className={`badge status-${status}`}>{map[status]||status}</span>}
export function StageBar({passed,total=9}:{passed:number;total?:number}){return <div className="stagebar">{Array.from({length:total},(_,i)=><span key={i} className={i<passed?'done':i===passed?'current':''}>{i<passed?'✓':i+1}</span>)}</div>}
