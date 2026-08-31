import {useEffect,useState} from 'react';
import {useParams} from 'react-router-dom';
import {ArrowRight,Ban,CheckCircle2,Clock3,Layers3,RefreshCw,XCircle} from 'lucide-react';
import {Button,PageHeader,StatusBadge} from '../App';
import {api} from '../api';
import type {DetailJob} from '../types';

export default function DetailJobPage(){
 const {jobId=''}=useParams();const [job,setJob]=useState<DetailJob>();const [error,setError]=useState('');
 const load=()=>api.detailJob(jobId).then(setJob).catch(e=>setError(e.message));
 useEffect(()=>{void load();const timer=window.setInterval(()=>void load(),2500);return()=>clearInterval(timer)},[jobId]);
 const reject=async(id:string)=>{try{await api.rejectDetailGroup(id,'当前候选组不采用');await load()}catch(e){setError((e as Error).message)}};
 const approve=async(id:string)=>{try{await api.approveDetailGroup(id,'整组候选已人工确认');await load()}catch(e){setError((e as Error).message)}};
 const retry=async()=>{try{const next=await api.retryDetailJob(jobId);location.assign(`/detail-jobs/${next.id}`)}catch(e){setError((e as Error).message)}};
 const latestReferenceSet=[...(job?.groups||[])].reverse().find(g=>g.referenceSetId)?.referenceSetId;
 return <><PageHeader eyebrow="AI 细节补充" title="候选组生成与审批" description="ComfyUI 正在本机串行生成受蒙版约束的候选。只有整组批准的资产会进入新的 Reference Set。" action={job&&<StatusBadge status={job.status}/>}/>
 {error&&<div className="notice danger">{error}</div>}
 {job?.status==='failed'&&<div className="notice danger"><XCircle/>{job.errorMessage}<Button kind="secondary" onClick={retry}><RefreshCw/>重试任务</Button></div>}
 {job&&<div className="panel detail-job-summary"><span><Layers3/> Provider <b>{job.provider}</b></span><span>模型 <b>{job.model}</b></span><span>Seed <b>{job.seed}</b></span></div>}
 {job&&<section className="panel detail-progress"><header><div><small>当前动作</small><h3>{job.progress.message||'等待任务状态'}</h3></div><b>{job.progress.current} / {job.progress.total}</b></header><div className="detail-progress-track"><span style={{width:`${job.progress.percent}%`}}/></div><div className="detail-progress-meta"><span>{job.progress.percent}%</span><span>GPU 串行执行 · 页面可安全刷新</span></div>{job.logs.length>0&&<details open={job.status==='generating'}><summary>运行日志（{job.logs.length}）</summary><pre>{job.logs.slice(-12).join('\n')}</pre></details>}</section>}
 <div className="candidate-grid">{job?.groups.map(g=><article className="panel candidate-card" key={g.id}><header><div><small>{g.regionKey}</small><h3>候选组 {g.groupIndex}</h3></div><StatusBadge status={g.status}/></header>{g.assets.length?<div className="candidate-assets">{g.assets.map(a=><figure key={a.assetId}><img src={a.url}/><figcaption>{a.viewRole}<small>{a.sha256.slice(0,12)}</small></figcaption></figure>)}</div>:<div className="candidate-empty"><Clock3/><p>等待 ComfyUI 生成资产</p><small>空候选组无法批准，也不会进入 Reference Set。</small></div>}<div className="tag-row"><span>{g.evidenceLevel}</span><span>{g.targetUsage}</span><span>{String(g.consistencyMetrics.status||'pending')}</span></div><div className="candidate-actions"><Button kind="success" disabled={!g.assets.length||g.status!=='draft'||g.consistencyMetrics.status!=='passed'} onClick={()=>approve(g.id)}><CheckCircle2/>批准整组</Button><Button kind="danger" disabled={g.status!=='draft'} onClick={()=>reject(g.id)}><Ban/>拒绝整组</Button></div></article>)}</div>
 {latestReferenceSet&&job&&<div className="sticky-actions"><span><CheckCircle2/>已创建锁定 Reference Set</span><Button onClick={()=>location.assign(`/plan/${job.projectId}?referenceSetId=${latestReferenceSet}`)}>查看实际输入并生成粗模<ArrowRight/></Button></div>}</>;
}
