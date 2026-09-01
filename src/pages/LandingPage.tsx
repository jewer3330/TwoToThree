import {Boxes, Cpu, Layers3, Printer as PrinterIcon, Scissors, Sparkles, ChevronRight, ArrowRight, ShieldCheck, Server, HardDrive} from 'lucide-react';
import {useState} from 'react';
import './landing.css';

const FEATURES = [
  {icon: Sparkles, title: '2D → 3D 转换', desc: '上传正面/侧面/背面参考图，Hunyuan3D 多视图推理生成带 PBR 材质的可打印 GLB。'},
  {icon: Layers3, title: '四视图预览', desc: '固定 front / 3/4 / side / back 四视图，Three.js 实时视口验收，人工复核闭环。'},
  {icon: Cpu, title: 'GPU 集群调度', desc: '主控统一调度 N 台算力节点，能力匹配、并发控制、故障自动转移。'},
  {icon: Scissors, title: '部件切分', desc: '按连通体自动拆分模块，独立预览、条件生成与 A/B 验收。'},
  {icon: PrinterIcon, title: '拓竹打印接入', desc: 'LAN MQTT 实时读取打印机状态，分模块 AMS 多色，导出 3MF 一键发送。'},
  {icon: Boxes, title: '模型 / 资产库', desc: '版本化存储模型、渲染与质量报告，Base 版本锁定与完整可追踪性。'},
];

const ARCH = [
  {icon: Server, title: '总控（主控）', desc: 'FastAPI + SQLite + 队列调度，OIDC 登录，统一编排所有任务。'},
  {icon: HardDrive, title: 'OSS 对象存储', desc: '大文件走阿里云 OSS CDN 中转，绕开低带宽回传，scp 仅作兜底。'},
  {icon: Cpu, title: '算力机器', desc: 'Windows GPU 节点 + AutoDL 云算力，按需开机、用完关机，控制成本。'},
];

export default function LandingPage(){
  const returnTo = location.pathname === '/' ? '/' : location.pathname + location.search;
  const loginHref = `/api/auth/login?return_to=${encodeURIComponent(returnTo)}`;
  const [email,setEmail]=useState('');
  return <div className="landing">
    <header className="landing-nav">
      <div className="brand"><span className="brandmark"><Sparkles/></span><div><b>2D→3D Studio</b><small>生产工作台</small></div></div>
      <nav className="landing-links">
        <a href="#features">功能</a><a href="#architecture">架构</a><a href="#contact">联系</a>
      </nav>
      <a className="button ghost" href={loginHref}>登录 <ArrowRight size={15}/></a>
    </header>

    <section className="landing-hero">
      <div className="hero-badge"><Sparkles size={14}/> 2D 设计稿 → 可打印 3D 模型 · 分布式 GPU 生产</div>
      <h1>把二维设计，<span>变成可打印的三维现实</span></h1>
      <p className="hero-sub">面向 3D 打印工作流的 2D→3D 生产平台：多视图参考、Hunyuan3D 推理、Blender 精修、四视图验收与拓竹打印，一条链路闭环。</p>
      <div className="hero-cta">
        <a className="button primary lg" href={loginHref}>开始生产 <ChevronRight size={16}/></a>
        <a className="button ghost lg" href="#features">了解功能</a>
      </div>
      <div className="hero-stats">
        <div><b>6</b><span>核心页面</span></div>
        <div><b>9</b><span>任务阶段</span></div>
        <div><b>N</b><span>GPU 节点</span></div>
        <div><b>48h</b><span>产物保留</span></div>
      </div>
    </section>

    <section className="landing-features" id="features">
      <h2>生产能力矩阵</h2>
      <p className="section-sub">从素材校验到验收闭环，每个环节都有据可查、可追溯。</p>
      <div className="feature-grid">
        {FEATURES.map(({icon:I,title,desc})=><article key={title}><span className="feat-ico"><I/></span><h3>{title}</h3><p>{desc}</p></article>)}
      </div>
    </section>

    <section className="landing-arch" id="architecture">
      <h2>分布式架构</h2>
      <p className="section-sub">总控 + OSS + 算力机器，新增机器只需注册一条配置。</p>
      <div className="arch-grid">
        {ARCH.map(({icon:I,title,desc},i)=><div className="arch-node" key={title}><span className="arch-ico"><I/></span><h3>{title}</h3><p>{desc}</p>{i<ARCH.length-1&&<span className="arch-arrow"><ChevronRight/></span>}</div>)}
      </div>
    </section>

    <section className="landing-contact" id="contact">
      <div className="contact-card">
        <h2>需要账号？联系管理员开通</h2>
        <p>账号、密码与权限统一由 OIDC 身份系统（Authentik）管理，按用户组开放后台功能。</p>
        <div className="contact-row">
          <input type="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="你的工作邮箱" aria-label="工作邮箱"/>
          <a className="button primary" href={`mailto:admin@example.com?subject=申请 Studio 账号&body=${encodeURIComponent(email)}`}>申请开通 <ArrowRight size={15}/></a>
        </div>
      </div>
    </section>

    <footer className="landing-foot">
      <div className="brand"><span className="brandmark"><Sparkles/></span><div><b>2D→3D Studio</b><small>生产工作台</small></div></div>
      <div className="foot-meta"><span><ShieldCheck size={13}/> OIDC 单点登录 · 数据隔离</span><span>© {new Date().getFullYear()} 2D→3D Studio</span></div>
    </footer>
  </div>;
}
