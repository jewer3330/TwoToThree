import {useCallback, useEffect, useState} from 'react';
import {ChevronLeft, ChevronRight, Plus, Printer as PrinterIcon, RefreshCw, Trash2, Upload} from 'lucide-react';
import {api} from '../api';
import type {Printer} from '../types';
import {PageHeader} from '../App';

interface PrintPart { index:number; name:string; stl:string; preview:string; dims:number[]; volume:number }
interface PrintJob { id:string; name:string; status:string; step:string; modelUrl:string|null; modelFile?:string; split:{status:string;parts:PrintPart[];partCount?:number;error?:string;maxParts?:number;targetHeightMm?:number}; color:{palette:Array<{id:string;name:string;hex:string}>;assignments:Record<string,string>;preview3mf?:string} }

const PALETTE=[['白','#FFFFFF'],['黑','#1F1F1F'],['红','#E53935'],['橙','#FB8C00'],['黄','#FDD835'],['绿','#43A047'],['蓝','#1E88E5'],['紫','#8E24AA'],['粉','#EC407A'],['青','#00ACC1'],['棕','#6D4C41'],['灰','#9E9E9E']];

export default function PrintWorkflowPage(){
  const [jobs,setJobs]=useState<PrintJob[]>([]);
  const [printers,setPrinters]=useState<Printer[]>([]);
  const [job,setJob]=useState<PrintJob|null>(null);
  const [busy,setBusy]=useState(false);
  const [name,setName]=useState('打印任务');
  const [drag,setDrag]=useState(false);
  const [maxParts,setMaxParts]=useState(12);
  const [targetHeightMm,setTargetHeightMm]=useState(120);
  const [selPrinter,setSelPrinter]=useState('');
  const [startPrint,setStartPrint]=useState(false);
  const [sendResult,setSendResult]=useState('');
  const [amsSlot,setAmsSlot]=useState('3');
  const uploadSliced=async(f:File)=>{if(!job)return;setBusy(true);try{const j=await api.printJobUploadSliced(job.id,f);setJob(j as unknown as PrintJob);setSendResult('切片文件已校验并导入');}catch(e){alert(String(e));}finally{setBusy(false);}};

  const refresh=useCallback(async()=>{try{const [j,p]=await Promise.all([api.printJobs(),api.printers()]);setJobs(j as unknown as PrintJob[]);setPrinters(p);}catch(e){console.error(e);}},[ ]);
  useEffect(()=>{refresh();},[refresh]);

  const create=async()=>{setBusy(true);try{const j=await api.printJobCreate({name});setJob(j as unknown as PrintJob);await refresh();}catch(e){alert(String(e));}finally{setBusy(false);}};
  const load=(j:PrintJob)=>{setJob(j);setMaxParts(j.split?.maxParts||12);setTargetHeightMm(j.split?.targetHeightMm||120);};

  const upload=async(f:File)=>{if(!job)return;setBusy(true);try{const j=await api.printJobUploadModel(job.id,f);setJob(j as unknown as PrintJob);}catch(e){alert(String(e));}finally{setBusy(false);}};
  const doSplit=async()=>{if(!job)return;setBusy(true);try{const j=await api.printJobSplit(job.id,{maxParts,targetHeightMm});setJob(j as unknown as PrintJob);}catch(e){alert(String(e));}finally{setBusy(false);}};
  const doColor=async()=>{if(!job)return;setBusy(true);try{const j=await api.printJobColor(job.id,job.color.assignments);setJob(j as unknown as PrintJob);}catch(e){alert(String(e));}finally{setBusy(false);}};
  const doExport=async()=>{if(!job)return;setBusy(true);setSendResult('');try{const j=await api.printJobExport3mf(job.id);setJob({...job,color:{...job.color,preview3mf:(j as any).url,preview3mfHash:(j as any).hash},step:'send'} as PrintJob);setSendResult(`3MF 导出成功 (${((j as any).size/1048576).toFixed(1)} MB)`);}catch(e){alert(String(e));}finally{setBusy(false);}};
  const doSend=async()=>{if(!job)return;setBusy(true);setSendResult('');try{const r=await api.printJobSend(job.id,{printerId:selPrinter,startPrint,amsMapping:amsSlot===''?[]:[Number(amsSlot)]});const rj=r as any;setSendResult(`文件已上传: ${rj.uploaded} (${(rj.size/1048576).toFixed(1)} MB)`+(rj.printCommand?`\n${rj.printCommand.accepted?'打印机已接受任务，实际进度请查看打印机状态':rj.printCommand.error||'未确认启动'}`:''));}catch(e){alert(`发送失败：${(e as Error).message}`);}finally{setBusy(false);}};
  const del=async(id:string)=>{if(!confirm('删除该打印任务？'))return;setBusy(true);try{await api.printJobDelete(id);if(job?.id===id)setJob(null);await refresh();}catch(e){alert(String(e));}finally{setBusy(false);}};

  const pickColor=(stlName:string,hex:string)=>{if(!job)return;const a={...job.color.assignments,[stlName]:hex};setJob({...job,color:{...job.color,assignments:a}});};

  return <div className="page print-workflow">
    <PageHeader eyebrow="打印流程" title="打印工作台" description="分模块打印（自动拆分）+ AMS 多色上色。步骤：导入模型 → 分模块 → 上色 → 打印。" action={
      <div className="wf-actions"><button className="button" onClick={create} disabled={busy}><Plus size={16}/>新建任务</button></div>}/>

    <div className="wf-layout">
      <aside className="wf-side">
        <h3>打印任务</h3>
        {jobs.map(j=><div key={j.id} className={`wf-job ${job?.id===j.id?'active':''}`} onClick={()=>load(j)}>
          <b>{j.name}</b><span>{j.status}</span><button className="icon-btn" onClick={e=>{e.stopPropagation();del(j.id);}}><Trash2 size={12}/></button>
        </div>)}
        {!jobs.length&&<p className="muted">暂无任务，点击「新建任务」</p>}
      </aside>

      <section className="wf-main">
        {!job?<div className="empty"><PrinterIcon/><h3>开始一个打印任务</h3><p>新建任务后上传 3D 模型（GLB/STL），自动拆分为可打印模块并分配 AMS 颜色。</p></div>:<>
          <div className="wf-steps"><span className={job.step==='model'?'cur':job.step!=='model'?'done':''}>① 模型</span><span className={job.step==='split'?'cur':['color','ready'].includes(job.step)?'done':''}>② 分模块</span><span className={['color','ready'].includes(job.step)?'cur':''}>③ 上色</span><span>④ 打印</span></div>

          {(!job.modelFile)&&<div className={`wf-drop ${drag?'over':''}`} onDragOver={e=>{e.preventDefault();setDrag(true);}} onDragLeave={()=>setDrag(false)} onDrop={e=>{e.preventDefault();setDrag(false);const f=e.dataTransfer.files?.[0];if(f)upload(f);}}>
            <Upload size={28}/><p>拖入模型文件，或 <label className="link">选择文件<input type="file" hidden accept=".glb,.stl,.obj,.3mf" onChange={e=>{const f=e.target.files?.[0];if(f)upload(f);}}/></label></p>
          </div>}

          {job.modelFile&&<>
              <div className="wf-row"><input value={name} onChange={e=>setName(e.target.value)} style={{display:'none'}}/>
                <div className="wf-model-info"><b>模型已上传</b><span>{job.modelUrl}</span></div>
                <label className="wf-height">成品高度 <input type="number" min="10" max="500" step="1" value={targetHeightMm} onChange={e=>setTargetHeightMm(Math.max(10,Math.min(500,Number(e.target.value)||120)))}/><span>mm</span></label>
                <button className="button secondary" onClick={doSplit} disabled={busy}><RefreshCw size={14}/>执行分模块</button>
            </div>
            {job.split?.status==='failed'&&<div className="wf-error">{job.split.error}</div>}
            {job.split?.status==='done'&&<>
              <div className="wf-color-help">③ 上色：点击每个部件下的<b>色块</b>为它指定 AMS 颜色（一个部件一个色；多个部件可各选不同色实现<b>多色打印</b>）。选好后点右下「完成上色（保存）」。</div>
              <div className="wf-parts">
                {job.split.parts.map(p=>{
                  const stlName=p.stl.split('/').pop()!;
                  const color=job.color.assignments[stlName]||'#9E9E9E';
                  const colorName=PALETTE.find(([n,h])=>h===color)?.[0]||'灰';
                  return <div key={p.index} className="wf-part" style={{borderColor:color}}>
                    <img src={p.preview} alt={p.name} loading="lazy"/>
                    <b>{p.name||`部件 ${p.index}`}</b>
                    <span>{p.dims.map(d=>d.toFixed(1)).join('×')}mm</span>
                    <span className="wf-part-curcolor">当前颜色：{colorName}</span>
                    <div className="wf-part-colors">{PALETTE.map(([n,h])=><button key={h} title={n} style={{background:h}} className={color===h?'sel':''} onClick={()=>pickColor(stlName,h)}/>)}</div>
                  </div>;
                })}
              </div>
              <div className="wf-footer"><button className="button primary" onClick={doColor} disabled={busy}><ChevronRight size={16}/>完成上色（保存）</button><button className="button secondary" onClick={doExport} disabled={busy}>导出模型 3MF</button><label className="button secondary">导入切片版 3MF<input hidden type="file" accept=".3mf" disabled={busy} onChange={e=>{const f=e.target.files?.[0];if(f)uploadSliced(f);}}/></label></div>
            </>}
            {(job.color?.preview3mf||(job as any).sliced)&&<div className="wf-send">
              <h4>④ 发送打印</h4>
              <div className="wf-send-row">
                {job.color.preview3mf&&<a className="button secondary" href={job.color.preview3mf.startsWith('/')?job.color.preview3mf:`/data/${job.color.preview3mf}`} download>下载模型 3MF</a>}
                <label>耗材槽<select value={amsSlot} onChange={e=>setAmsSlot(e.target.value)}><option value="">外置料盘</option>{[0,1,2,3].map(i=><option key={i} value={i}>AMS {i+1}</option>)}</select></label>
                <select className="printer-select" value={selPrinter} onChange={e=>setSelPrinter(e.target.value)}>
                  <option value="">选择打印机…</option>
                  {printers.filter(p=>p.enabled).map(p=><option key={p.id} value={p.id}>{p.name} ({p.ip})</option>)}
                </select>
                <button className="button secondary" onClick={doExport} disabled={busy||!job.color.preview3mf}><RefreshCw size={14}/>重新导出 3MF</button>
                <button className="button primary" onClick={doSend} disabled={busy||!selPrinter}><PrinterIcon size={14}/>上传到打印机</button>
                <label className="start-print"><input type="checkbox" checked={startPrint} onChange={e=>setStartPrint(e.target.checked)}/>上传后直接发送打印</label>
              </div>
              {sendResult&&<pre className="wf-send-result">{sendResult}</pre>}
              <p className="muted note">说明：多色 3MF 需经 Bambu Studio/OrcaSlicer 切片后才可打印；「上传到打印机」将 3MF 传到打印机（FTP），可稍后在打印机屏幕选择打印，或勾选「直接发送打印」（需已切片文件）。</p>
            </div>}
          </>}
        </>}
      </section>
    </div>
  </div>;
}
