import {ArrowRight, Sparkles} from 'lucide-react';
import {useEffect,useRef,useState,type MouseEvent} from 'react';
import './landing.css';

const FEATURES = [
  {n:'01', title:'2D → 3D 转换', desc:'上传正面 / 侧面 / 背面参考图，Hunyuan3D 多视图推理，生成带 PBR 材质的可打印 GLB。'},
  {n:'02', title:'四视图预览', desc:'固定 front / 3/4 / side / back 四视图，Three.js 实时视口验收，人工复核闭环。'},
  {n:'03', title:'GPU 集群调度', desc:'主控统一调度 N 台算力节点，能力匹配、并发控制、故障自动转移。'},
  {n:'04', title:'部件切分', desc:'按连通体自动拆分模块，独立预览、条件生成与 A/B 验收。'},
  {n:'05', title:'拓竹打印接入', desc:'LAN MQTT 实时读取打印机状态，分模块 AMS 多色，导出 3MF 一键发送。'},
  {n:'06', title:'模型 / 资产库', desc:'版本化存储模型、渲染与质量报告，Base 版本锁定与完整可追踪性。'},
];

const STEPS = [
  {t:'总控 · 主控', d:'FastAPI + SQLite + 队列调度，OIDC 登录，统一编排所有任务。'},
  {t:'OSS 对象存储', d:'大文件走阿里云 OSS CDN 中转，绕开低带宽回传，scp 仅作兜底。'},
  {t:'算力机器', d:'Windows GPU 节点 + AutoDL 云算力，按需开机、用完关机，控制成本。'},
];

function makePetal(container: HTMLDivElement, burst: boolean, x: number, y: number) {
  const petal = document.createElement('i');
  petal.className = burst ? 'petal burst' : 'petal';
  if (burst) {
    petal.style.setProperty('--x', `${x}px`);
    petal.style.setProperty('--y', `${y}px`);
    petal.style.setProperty('--dx', `${(Math.random() - .5) * 170}px`);
    petal.style.setProperty('--dy', `${-40 - Math.random() * 90}px`);
    petal.style.transform = `rotate(${Math.random() * 180}deg)`;
    container.appendChild(petal);
    window.setTimeout(() => petal.remove(), 1000);
  } else {
    petal.style.left = `${Math.random() * 100}vw`;
    petal.style.setProperty('--drift', `${(Math.random() - .5) * 200}px`);
    petal.style.animationDuration = `${8 + Math.random() * 6}s`;
    petal.style.opacity = String(.3 + Math.random() * .45);
    container.appendChild(petal);
    window.setTimeout(() => petal.remove(), 14500);
  }
}

export default function LandingPage() {
  const returnTo = location.pathname === '/' ? '/' : location.pathname + location.search;
  const loginHref = `/api/auth/login?return_to=${encodeURIComponent(returnTo)}`;
  const [email, setEmail] = useState('');
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [opened, setOpened] = useState(false);
  const petalField = useRef<HTMLDivElement>(null);

  const burstAt = (e: MouseEvent<HTMLElement>) => {
    const field = petalField.current;
    if (!field) return;
    const rect = e.currentTarget.getBoundingClientRect();
    for (let i = 0; i < 9; i += 1) {
      window.setTimeout(() => {
        if (!petalField.current) return;
        makePetal(petalField.current, true,
          rect.left + rect.width / 2 + (Math.random() - .5) * 100,
          rect.top + rect.height / 2 + (Math.random() - .5) * 50);
      }, i * 28);
    }
  };

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    for (let i = 0; i < 6; i += 1) window.setTimeout(() => { if (petalField.current) makePetal(petalField.current, false, 0, 0); }, i * 320);
    const timer = window.setInterval(() => { if (petalField.current) makePetal(petalField.current, false, 0, 0); }, 4200);
    return () => window.clearInterval(timer);
  }, []);

  return <div className="landing">
    <div className="petal-field" aria-hidden="true" ref={petalField}/>

    <header className="site-header">
      <a className="brand" href="#top" aria-label="2D→3D Studio 首页">
        <span className="brandmark"><Sparkles size={16}/></span>
        <span className="brand-text"><b>2D→3D 造物坊</b><small>生产工作台</small></span>
      </a>
      <nav aria-label="主导航">
        <a href="#features">工坊清单</a>
        <a href="#architecture">造物之旅</a>
        <a href="#contact">申请账号</a>
      </nav>
      <a className="landing-btn ghost" href={loginHref}>登录</a>
    </header>

    <main id="top">
      <section className="landing-hero" aria-labelledby="hero-title">
        <div className="hero-copy">
          <p className="eyebrow"><span/> 2D→3D STUDIO · 造物工坊</p>
          <h1 id="hero-title">让二维的想象，<br/><em>长成三维的实物</em></h1>
          <p className="hero-intro">上传参考图，Hunyuan3D 为你长出体积与材质；四视图人工验收，再送进打印机。每一步，都有人认真复核。</p>
          <div className="hero-actions">
            <a className="landing-btn primary" href={loginHref}>开始造物 <ArrowRight size={15}/></a>
            <a className="text-link" href="#features">看看工坊清单 <span aria-hidden="true">↘</span></a>
          </div>
          <div className="workshop-note" aria-label="今日工坊状态">
            <span className="sun" aria-hidden="true"/>
            <div><strong>GPU 就绪</strong><small>队列空闲 · 产物保留 48h</small></div>
          </div>
        </div>

        <figure className="hero-visual">
          <div className="image-frame">
            <img src="/yoyo-reference.png" alt="溜溜球设计稿——从二维参考图长成可打印的三维模型"/>
            <span className="image-tag">REF<br/>DESIGN<br/>2026</span>
          </div>
          <figcaption>
            <span>NO. 01</span>
            <p>从一张设计稿开始<br/>长成可以握住的样子</p>
          </figcaption>
        </figure>
      </section>

      <section className="landing-list" id="features" aria-labelledby="list-title">
        <div className="list-intro">
          <p className="eyebrow"><span/> WHAT THE WORKSHOP CAN DO</p>
          <h2 id="list-title">工坊的<br/>六件小本事</h2>
          <p>不必记挂复杂流程。六件扎实的小事，串成一条从设计稿到打印件的温柔流水线。</p>
        </div>

        <ol className="craft-list">
          {FEATURES.map(f => (
            <li key={f.n}>
              <button type="button" aria-pressed={!!checked[f.n]}
                onClick={e => { burstAt(e); setChecked(c => ({...c, [f.n]: !c[f.n]})); }}>
                <span className="item-number">{f.n}</span>
                <span className="item-copy"><strong>{f.title}</strong><small>{f.desc}</small></span>
                <span className="check" aria-hidden="true"/>
              </button>
            </li>
          ))}
        </ol>
      </section>

      <section className="landing-journey" id="architecture" aria-labelledby="journey-title">
        <div className="section-heading">
          <p className="eyebrow"><span/> BEHIND THE SCENES</p>
          <h2 id="journey-title">一封信，看懂造物之旅</h2>
          <p>总控 + OSS + 算力机器，新增机器只需注册一条配置。</p>
        </div>
        <div className="journey-grid">
          {STEPS.map((s, i) => (
            <div className="journey-card" key={s.t}>
              <span className="journey-no">{['I', 'II', 'III'][i]}</span>
              <h3>{s.t}</h3>
              <p>{s.d}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="landing-letter" id="contact" aria-labelledby="letter-title">
        <div className={`letter-card${opened ? ' open' : ''}`}>
          <span className="letter-flap" aria-hidden="true"/>
          <button type="button" className="letter-trigger" aria-expanded={opened}
            onClick={e => { burstAt(e); setOpened(!opened); }}>
            <span className="letter-seal" aria-hidden="true">造物</span>
            <span className="letter-hint">{opened ? '轻轻合上' : '点击拆信 · 申请账号'}</span>
          </button>
          <div className="letter-body">
            <p className="eyebrow"><span/> GET YOUR SEAT</p>
            <h2 id="letter-title">需要账号？<em>管理员开一扇门</em></h2>
            <p>账号、密码与权限统一由 OIDC 身份系统（Authentik）管理，按用户组开放后台功能。</p>
            <div className="letter-form">
              <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="你的工作邮箱" aria-label="工作邮箱"/>
              <a className="landing-btn primary" href={`mailto:admin@example.com?subject=申请 Studio 账号&body=${encodeURIComponent(email)}`}>申请开通 <ArrowRight size={15}/></a>
            </div>
          </div>
        </div>
      </section>
    </main>

    <footer className="landing-foot">
      <div className="footer-flower" aria-hidden="true"><i/><i/><i/><i/><span/></div>
      <p>愿每一次设计，都能安稳地落成实物。</p>
      <a href="#top">回到工坊 <span aria-hidden="true">↑</span></a>
      <small>2D→3D STUDIO · MADE WITH CARE</small>
    </footer>
  </div>;
}
