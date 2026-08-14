import {useEffect,useState} from 'react';
import {useNavigate,useParams} from 'react-router-dom';
import {AlertTriangle,CheckCircle2,Sparkles} from 'lucide-react';
import {Button,PageHeader,StatusBadge} from '../App';
import {api} from '../api';
import type {DetailPlan} from '../types';

const labels:Record<string,string>={head:'头部整体',face:'面部',hair:'头发 / 发髻',neck_collar:'颈部与衣领',torso_garment:'躯干服装',left_shoulder_sleeve:'左肩袖',right_shoulder_sleeve:'右肩袖',arms_hands:'手臂与手',lower_body:'下半身',back_structure:'背部结构',accessories:'独立配饰'};
export default function DetailPlanPage(){
 const {projectId=''}=useParams();const nav=useNavigate();const [plan,setPlan]=useState<DetailPlan>();const [mode,setMode]=useState('balanced');const [error,setError]=useState('');
 useEffect(()=>{api.createDetailPlan(projectId,mode).then(setPlan).catch(e=>setError(e.message))},[projectId]);
 const patch=async(id:string,body:unknown)=>{try{setPlan(await api.updateDetailRegion(plan!.id,id,body))}catch(e){setError((e as Error).message)}};
 const recreate=async()=>{try{setPlan(await api.createDetailPlan(projectId,mode));setError('')}catch(e){setError((e as Error).message)}};
 const confirm=async()=>{try{const confirmed=await api.confirmDetailPlan(plan!.id);const job=await api.createDetailJob(confirmed.id,2);nav(`/detail-jobs/${job.id}`)}catch(e){setError((e as Error).message)}};
 return <><PageHeader eyebrow="AI 细节补充 · 规则规划 v1" title="选择需要补充的细节区域" description="规划结果来自视图覆盖度和清晰度规则。候选不会自动进入几何流程，必须整组批准。" action={plan&&<StatusBadge status={plan.status}/>}/>
 <div className="detail-toolbar panel"><label>生成模式<select value={mode} onChange={e=>setMode(e.target.value)}><option value="conservative">保守</option><option value="balanced">平衡</option><option value="creative">创作（高风险）</option></select></label><Button kind="secondary" onClick={recreate}>重新分析</Button><span><AlertTriangle/> 修改素材后应重新创建计划</span></div>
 {error&&<div className="notice danger">{error}</div>}
 {plan&&<div className="detail-region-grid">{plan.regions.map(r=><article className={`panel detail-region ${r.selected?'selected':''}`} key={r.id}><header><div><small>{r.regionKey}</small><h3>{labels[r.regionKey]||r.regionKey}</h3></div><input type="checkbox" checked={r.selected} disabled={plan.status!=='awaiting_confirmation'} onChange={e=>patch(r.id,{selected:e.target.checked})}/></header><div className="metric-row"><span>覆盖度 <b>{Math.round(r.coverageScore*100)}%</b></span><span>清晰度 <b>{Math.round(r.clarityScore*100)}%</b></span><span>一致性 <b>{Math.round(r.consistencyScore*100)}%</b></span></div><p>可见视图：{r.visibleViews.join('、')||'无直接证据'}</p><p>建议补充：{r.recommendedViews.join('、')||'当前覆盖充分'}</p><div className="tag-row"><span>{r.evidenceLevel}</span><span>{r.targetUsage}</span><span className={`risk-${r.riskLevel}`}>{r.riskLevel} risk</span></div><label>目标用途<select value={r.targetUsage} disabled={plan.status!=='awaiting_confirmation'} onChange={e=>patch(r.id,{targetUsage:e.target.value})}><option value="geometry">几何</option><option value="normal_displacement">法线 / 置换</option><option value="material">材质</option></select></label></article>)}</div>}
 {plan&&<div className="sticky-actions"><span><CheckCircle2/> 已选择 {plan.regions.filter(r=>r.selected).length} 个区域</span><Button disabled={!plan.regions.some(r=>r.selected)||plan.status!=='awaiting_confirmation'} onClick={confirm}><Sparkles/>确认计划并创建候选任务</Button></div>}</>;
}
