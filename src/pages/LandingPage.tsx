import {ArrowRight, Sparkles} from 'lucide-react';
import {useEffect,useRef,useState,type MouseEvent} from 'react';
import './landing.css';

const FEATURES = [
  {n:'01', title:'画稿成真', desc:'交来几张正、侧、背的画稿，还你一个能握在手里的立体。AI 读图，替你长出体积、纹理与质感。'},
  {n:'02', title:'四角端详', desc:'前、侧、后，还有四分之三，四个角度慢慢转、细细看。看真切了，才肯放行。'},
  {n:'03', title:'众人合力', desc:'一台调度，多台齐忙。活儿来了自动分派，谁闲谁忙、谁来搭把手，都替你张罗妥当。'},
  {n:'04', title:'化整为零', desc:'大件拆成小件，各自成形、各自检视。逐块推敲，拼回去依然严丝合缝。'},
  {n:'05', title:'一键成物', desc:'连着打印机，多色分料，轻轻一按送出门。机器在不在忙、进展到哪，抬眼便知。'},
  {n:'06', title:'妥帖收好', desc:'每一版都安放得整整齐齐，可回溯、可比对。最满意的那一件，稳稳定下。'},
];

const STEPS = [
  {t:'管家 · 主控', d:'把每件事记在心上、排得妥帖。谁来做什么、做到哪一步，一目了然。'},
  {t:'驿站 · 存储', d:'大件的图纸与成品，先在这里歇脚，再稳稳地送到该去的地方。'},
  {t:'工匠 · 算力', d:'需要力气时唤它来，干完就歇，不白白耗费一分一毫。'},
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
          <p className="hero-intro">交来几张画稿，AI 替你长出体积与质感；四个角度端详过，再稳稳送进打印机。每一步，都有人认真复核。</p>
          <div className="hero-actions">
            <a className="landing-btn primary" href={loginHref}>开始造物 <ArrowRight size={15}/></a>
            <a className="text-link" href="#features">看看工坊清单 <span aria-hidden="true">↘</span></a>
          </div>
          <div className="workshop-note" aria-label="今日工坊状态">
            <span className="sun" aria-hidden="true"/>
            <div><strong>工坊今日开张</strong><small>无人排队 · 成品暂存 48 小时</small></div>
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
          <p>不必记挂复杂流程。六件扎实的小事，串成一条从画稿到实物的温柔流水线。</p>
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
          <p>一位管家、一座驿站、一群工匠，各司其职，静静协作。</p>
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
            <p>账号与权限，统一由一扇温柔的门看管；该看什么、能做什么，各就其位。</p>
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
