import {useCallback, useEffect, useState} from 'react';
import {Activity, Cpu, Plus, Printer as PrinterIcon, RefreshCw, Thermometer, Trash2, X, Layers} from 'lucide-react';
import {api} from '../api';
import type {Printer,PrinterOverview} from '../types';
import {PageHeader} from '../App';

const MODELS=['A1 mini','A1','P1P','P1S','X1C','X1E'];
const STATE_COLOR:Record<string,string>={idle:'#7d8590',running:'#22d3ee',finish:'#34d399',failed:'#f87171',pause:'#fbbf24',prepare:'#a78bfa'};

function PrinterCard({p,onAction,onEdit}:{p:Printer;onAction:(t:'probe'|'toggle'|'delete',p:Printer)=>void;onEdit:(p:Printer)=>void}){
  const s=p.status?.status;
  const ok=!!p.status?.ok;
  const state=s?.state||'unknown';
  const color=STATE_COLOR[state]||'#7d8590';
  const prog=s?.progress??0;
  return <div className={`printer-card ${ok?'online':'offline'} ${p.enabled?'':'disabled'}`}>
    <div className="printer-head">
      <span className="printer-state-dot" style={{background:color,boxShadow:`0 0 8px ${color}88`}}/>
      <b>{p.name}</b><span className="printer-model">{p.model}</span>
      <span className="printer-ip">{p.ip}</span>
      <div className="printer-actions">
        <button title="探测" onClick={()=>onAction('probe',p)}><RefreshCw size={13}/></button>
        <button title="编辑" onClick={()=>onEdit(p)}><PrinterIcon size={13}/></button>
        <button title={p.enabled?'停用':'启用'} onClick={()=>onAction('toggle',p)}>{p.enabled?'停用':'启用'}</button>
        <button title="删除" className="danger" onClick={()=>onAction('delete',p)}><Trash2 size={13}/></button>
      </div>
    </div>
    <div className="printer-state-line"><span style={{color}}>{ok?(s?.stateLabel||'未知'):'离线'}</span>
      {s?.gcodeName&&<span className="muted gcode-name" title={s.gcodeName}>{s.gcodeName.slice(0,36)}</span>}
      {s?.remainingSeconds?s?.remainingSeconds>0&&<span className="muted">剩余 {Math.floor(s.remainingSeconds/60)}min</span>:null}
    </div>
    {ok&&s&&<>
      <div className="printer-progress"><div className="printer-progress-fill" style={{width:`${prog}%`}}/></div>
      <div className="printer-temps">
        <span><Thermometer size={13}/> 喷嘴 <b>{s.nozzleTemp}°</b>/{s.nozzleTarget>0?`${s.nozzleTarget}°`:''}</span>
        <span><Thermometer size={13}/> 热床 <b>{s.bedTemp}°</b>/{s.bedTarget>0?`${s.bedTarget}°`:''}</span>
        <span><Layers size={13}/> 层 <b>{s.layerNum}/{s.totalLayers}</b></span>
        <span><Activity size={13}/> 进度 <b>{prog}%</b></span>
      </div>
    </>}
    <div className="printer-foot">
      <span>串口序列 {p.serial||'—'}</span>
      <span className="muted">{p.status?.probedAt?new Date(p.status.probedAt).toLocaleTimeString():'未探测'}</span>
    </div>
    {p.status?.error&&<div className="printer-error" title={p.status.error}>{p.status.error.slice(0,90)}</div>}
  </div>;
}

const EMPTY={name:'',model:'A1',ip:'',accessCode:'',serial:''};

export default function PrinterConsolePage(){
  const [printers,setPrinters]=useState<Printer[]>([]);
  const [overview,setOverview]=useState<PrinterOverview|null>(null);
  const [adding,setAdding]=useState(false);
  const [editing,setEditing]=useState<Printer|null>(null);
  const [form,setForm]=useState(EMPTY);
  const [busy,setBusy]=useState(false);

  const refresh=useCallback(async()=>{
    try{const [p,o]=await Promise.all([api.printers(),api.printerOverview()]);setPrinters(p);setOverview(o);}catch(e){console.error(e);}
  },[]);
  useEffect(()=>{refresh();const t=setInterval(refresh,15000);return()=>clearInterval(t);},[refresh]);

  const onAction=async(t:'probe'|'toggle'|'delete',p:Printer)=>{
    if(t==='delete'&&!confirm(`删除打印机 ${p.name}？`))return;
    setBusy(true);
    try{
      if(t==='probe')await api.printerProbe(p.id);
      if(t==='toggle')await api.printerToggle(p.id);
      if(t==='delete')await api.printerDelete(p.id);
      await refresh();
    }catch(e){alert(`操作失败：${(e as Error).message}`);}finally{setBusy(false);}
  };
  const openAdd=()=>{setForm(EMPTY);setEditing(null);setAdding(true);};
  const openEdit=(p:Printer)=>{setForm({name:p.name,model:p.model,ip:p.ip,accessCode:p.accessCode,serial:p.serial});setEditing(p);setAdding(true);};
  const save=async()=>{
    if(!form.ip){alert('请填写打印机 IP');return;}
    setBusy(true);
    try{
      if(editing)await api.printerPatch(editing.id,form);
      else await api.printerAdd(form);
      setAdding(false);setEditing(null);setForm(EMPTY);await refresh();
    }catch(e){alert(`保存失败：${(e as Error).message}`);}finally{setBusy(false);}
  };
  const F=({k,label,ph}:{k:keyof typeof EMPTY;label:string;ph?:string})=>(
    <label className="printer-field">{label}<input value={form[k]} placeholder={ph||label} onChange={e=>setForm({...form,[k]:e.target.value})}/></label>);

  return <div className="page printer-console">
    <PageHeader eyebrow="3D 打印机" title="打印机管理" description="拓竹 LAN 模式接入：注册打印机后自动探测状态；打印流程（切片/上传/发送任务）后续衔接。" action={
      <button className="button" onClick={()=>adding?setAdding(false):openAdd()} disabled={busy}>{adding?<X size={16}/>:<Plus size={16}/>}{adding?'取消':editing?'编辑':'注册打印机'}</button>}/>

    <div className="printer-stats">
      <div className="printer-stat"><PrinterIcon size={18}/><b>{overview?.printerCount||0}</b><span>打印机</span></div>
      <div className="printer-stat ok"><Activity size={18}/><b>{overview?.online||0}</b><span>在线</span></div>
      <div className="printer-stat printing"><Cpu size={18}/><b>{overview?.printing||0}</b><span>打印中</span></div>
    </div>

    {adding&&<div className="printer-add-form">
      <h3>{editing?'编辑打印机':'注册新打印机'}</h3>
      <div className="printer-form-grid">
        <F k="name" label="名称" ph="客厅 A1"/>
        <label className="printer-field">型号<select value={form.model} onChange={e=>setForm({...form,model:e.target.value})}>{MODELS.map(m=><option key={m}>{m}</option>)}</select></label>
        <F k="ip" label="IP 地址" ph="192.168.31.45"/>
        <F k="accessCode" label="访问码 (LAN Mode)" ph="打印机设置→局域网 中查看"/>
        <F k="serial" label="序列号（可选）" ph="设备信息中查看"/>
      </div>
      <button className="button primary" onClick={save} disabled={busy||!form.ip}>保存</button>
    </div>}

    <div className="printer-grid">{printers.map(p=><PrinterCard key={p.id} p={p} onAction={onAction} onEdit={openEdit}/>)}
      {!printers.length&&<div className="empty"><PrinterIcon/><h3>尚未注册打印机</h3><p>点击「注册打印机」，填写 IP 与 LAN 访问码即可接入拓竹打印机状态。</p></div>}
    </div>

    {printers.length>0&&<div className="printer-hint"><PrinterIcon size={14}/> 接入拓竹 LAN 模式：打印机需开启 设置→局域网→局域网模式，访问码在打印机屏幕上查看。状态每 20s 自动刷新。</div>}
  </div>;
}
