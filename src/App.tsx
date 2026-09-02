import {Activity, ArrowLeft, Boxes, ChevronRight, Cpu, FolderKanban, Gauge, HardDrive, Home, Layers3, LogOut, Menu, Plus, Printer as PrinterIcon, Scissors, Search, Settings, SlidersHorizontal, Sparkles} from 'lucide-react';
import {Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate} from 'react-router-dom';
import {useEffect,useState} from 'react';
import {api,type AuthUser} from './api';
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
import DetailPlanPage from './pages/DetailPlanPage';
import DetailJobPage from './pages/DetailJobPage';
import PartsLabPage from './pages/PartsLabPage';
import PartsGeneratePage from './pages/PartsGeneratePage';
import PartsAssemblyPage from './pages/PartsAssemblyPage';
import PartsComparePage from './pages/PartsComparePage';
import GpuConsolePage from './pages/GpuConsolePage';
import PrinterConsolePage from './pages/PrinterConsolePage';
import PrintWorkflowPage from './pages/PrintWorkflowPage';
import SettingsPage from './pages/SettingsPage';
import LandingPage from './pages/LandingPage';

// 后台功能可见性：管理员组由后端 /me 返回（按 OIDC 用户组判定，非硬编码 role）。
function isAdmin(user:AuthUser):boolean{
  return user.role==='admin' || (!!user.adminGroup && (user.groups||[]).includes(user.adminGroup));
}

const nav=[['/',Home,'工作台',false],['/projects',FolderKanban,'项目管理',false],['/parts-lab',Scissors,'部件切分实验',false],['/assets',Layers3,'素材管理',false],['/queue',Activity,'任务队列',false],['/gpu',Cpu,'GPU 控制台',true],['/printer',PrinterIcon,'打印机',true],['/print-workflow',SlidersHorizontal,'打印工作台',false],['/library',Boxes,'模型 / 资产库',false],['/settings',Settings,'系统设置',true]] as const;
function Placeholder({title}:{title:string}){return <div className="empty"><Boxes/><h2>{title}</h2><p>该入口将在后续版本开放，当前 MVP 聚焦完整转换与验收流程。</p></div>}
const pageNames: Array<[RegExp,string]> = [
  [/^\/create$/, '新建项目'], [/^\/validation\//, '素材校验'], [/^\/plan\//, '方案确认'],
  [/^\/jobs\//, '生成任务'], [/^\/review\//, '预览验收'], [/^\/refinement\/new\//, '优化配置'],
  [/^\/refinement\/jobs\//, '优化任务'], [/^\/revisions\/new\//, '修订方案'], [/^\/revisions\//, '修订任务'],
  [/^\/detail-plans\//, 'AI 细节规划'], [/^\/detail-jobs\//, 'AI 候选任务'],
  [/^\/parts-lab$/, '三视图部件切分实验'],
  [/^\/parts-lab\/generate\//, '部件条件生成'],
  [/^\/parts-lab\/assembly\//, '部件基线装配'], [/^\/parts-lab\/compare\//, '部件 A/B 验收'],
  [/^\/projects$/, '项目管理'], [/^\/assets$/, '素材管理'], [/^\/queue$/, '任务队列'],
  [/^\/gpu$/, 'GPU 控制台'], [/^\/printer$/, '打印机'], [/^\/print-workflow$/, '打印工作台'], [/^\/library$/, '模型 / 资产库'], [/^\/settings$/, '系统设置'],
];

function Breadcrumbs(){
  const location=useLocation();
  const navigate=useNavigate();
  const current=pageNames.find(([pattern])=>pattern.test(location.pathname))?.[1]||'工作台';
  const isWorkflow=/^\/(create|validation|plan|jobs|review|refinement|revisions|detail-plans|detail-jobs)(\/|$)/.test(location.pathname);
  const parentPath=isWorkflow?'/projects':'/';
  return <nav className="breadcrumbs" aria-label="页面路径">
    {location.pathname!=='/'&&<button type="button" className="back-button" onClick={()=>navigate(parentPath)} aria-label="返回上级页面"><ArrowLeft/>返回上级</button>}
    <Link to="/" className="breadcrumb-home"><Home/>首页</Link>
    {isWorkflow&&<span className="breadcrumb-item"><ChevronRight/><Link to="/projects">项目管理</Link></span>}
    {location.pathname!=='/'&&<span className="breadcrumb-item"><ChevronRight/><strong aria-current="page">{current}</strong></span>}
  </nav>;
}

function LoginPage(){const params=new URLSearchParams(location.search);const returnTo=params.get('return_to')||'/';const target=`/api/auth/login?return_to=${encodeURIComponent(returnTo)}`;useEffect(()=>{location.replace(target)},[target]);return <div className="empty" style={{minHeight:'100vh',justifyContent:'center'}}><Sparkles/><h1>2D→3D Studio</h1><p>正在进入账号密码登录页…</p><a className="button primary" href={target}>没有自动跳转时点这里 <ChevronRight size={16}/></a></div>}

function Shell({user}:{user:AuthUser}){const loc=useLocation(); const focused=/\/(create|validation|plan|jobs|review|refinement|revisions|detail-plans|detail-jobs)(\/|$)/.test(loc.pathname);const logout=()=>{location.assign('/api/auth/logout?return_to='+encodeURIComponent('/'))};return <div className={`shell ${focused?'focused':''}`}>
  {!focused&&<aside className="sidebar"><div className="brand"><span className="brandmark"><Sparkles/></span><div><b>2D→3D Studio</b><small>生产工作台</small></div></div><nav>{nav.filter(([, , ,admin])=>!admin||isAdmin(user)).map(([to,I,label])=><NavLink key={to} to={to} end={to==='/' }><I/>{label}</NavLink>)}</nav><div className="sidebar-foot"><span className="health-dot"/> {user.name} · {isAdmin(user)?'管理员':'用户'} <button type="button" onClick={logout} title="退出登录"><LogOut size={15}/></button></div></aside>}
  <section className="workspace"><header className="topbar"><div className="mobile-brand"><Menu/> 2D→3D Studio</div><div className="search"><Search/><span>搜索项目、任务或素材</span><kbd>⌘ K</kbd></div><div className="system-strip"><span><Activity/> 系统 <b>正常</b></span><span><Cpu/> GPU <b>就绪</b></span><span><Gauge/> CPU <b>24%</b></span><span><HardDrive/> 存储 <b>68%</b></span></div></header><Breadcrumbs/><main><Routes>
    <Route path="/" element={<Dashboard/>}/><Route path="/create" element={<CreateProject/>}/><Route path="/validation/:projectId" element={<ValidationPage/>}/><Route path="/plan/:projectId" element={<PlanPage/>}/><Route path="/jobs/:jobId" element={<MonitorPage/>}/><Route path="/review/:projectId" element={<ReviewPage/>}/>
    <Route path="/refinement/new/:versionId" element={<RefinementConfigPage/>}/><Route path="/refinement/jobs/:jobId" element={<RefinementMonitorPage/>}/>
    <Route path="/revisions/new/:versionId" element={<RevisionPlanPage/>}/><Route path="/revisions/:revisionId" element={<RevisionMonitorPage/>}/>
    <Route path="/detail-plans/:projectId" element={<DetailPlanPage/>}/><Route path="/detail-jobs/:jobId" element={<DetailJobPage/>}/>
    <Route path="/parts-lab" element={<PartsLabPage/>}/>
    <Route path="/parts-lab/generate/:partId" element={<PartsGeneratePage/>}/>
    <Route path="/parts-lab/assembly/:partId" element={<PartsAssemblyPage/>}/>
    <Route path="/parts-lab/compare/:partId" element={<PartsComparePage/>}/>
    <Route path="/parts-lab/*" element={<PartsLabPage/>}/>
    <Route path="/projects" element={<Dashboard/>}/><Route path="/assets" element={<Placeholder title="素材管理"/>}/><Route path="/queue" element={<Placeholder title="任务队列"/>}/><Route path="/gpu" element={isAdmin(user)?<GpuConsolePage/>:<Navigate to="/"/>}/><Route path="/printer" element={isAdmin(user)?<PrinterConsolePage/>:<Navigate to="/"/>}/><Route path="/print-workflow" element={<PrintWorkflowPage/>}/><Route path="/library" element={<Placeholder title="模型 / 资产库"/>}/><Route path="/settings" element={isAdmin(user)?<SettingsPage/>:<Navigate to="/"/>}/><Route path="*" element={<Navigate to="/"/>}/>
  </Routes></main></section>
</div>}
export default function App(){const [user,setUser]=useState<AuthUser|null|undefined>(undefined);useEffect(()=>{api.me().then(setUser).catch(()=>setUser(null))},[]);if(location.pathname==='/login')return <LoginPage/>;if(user===undefined)return <div className="empty"><Activity/><p>正在验证登录状态…</p></div>;if(!user)return <LandingPage/>;return <Shell user={user}/>}

export function PageHeader({eyebrow,title,description,action}:{eyebrow?:string;title:string;description?:string;action?:React.ReactNode}){return <div className="page-header"><div>{eyebrow&&<span className="eyebrow">{eyebrow}</span>}<h1>{title}</h1>{description&&<p>{description}</p>}</div>{action}</div>}
export function Button({children,kind='primary',...props}:React.ButtonHTMLAttributes<HTMLButtonElement>&{kind?:'primary'|'secondary'|'danger'|'success'}){return <button className={`button ${kind}`} {...props}>{children}<ChevronRight size={16}/></button>}
export function StatusBadge({status}:{status:string}){const map:Record<string,string>={draft:'草稿',validating:'检查中',needs_input:'等待素材',awaiting_confirmation:'等待方案确认',awaiting_geometry_confirmation:'等待几何确认',queued:'排队中',generating_geometry:'生成中',rendering_review:'渲染中',ready_for_review:'待验收',completed:'已完成',completed_with_notes:'有条件完成',transfer_pending:'传输中断·可恢复',failed:'异常',cancelled:'已取消'};return <span className={`badge status-${status}`}>{map[status]||status}</span>}
export function StageBar({passed,total=9}:{passed:number;total?:number}){return <div className="stagebar">{Array.from({length:total},(_,i)=><span key={i} className={i<passed?'done':i===passed?'current':''}>{i<passed?'✓':i+1}</span>)}</div>}
