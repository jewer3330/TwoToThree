import {Save} from 'lucide-react';
import {useEffect,useMemo,useState} from 'react';
import {api,type SiteSettings} from '../api';
import {PageHeader} from '../App';

/** 系统设置：站点级可配置项（域名/接入/存储/安全）统一在此查看与修改。 */
export default function SettingsPage() {
  const [settings,setSettings]=useState<SiteSettings|null>(null);
  const [values,setValues]=useState<Record<string,string>>({});
  const [saving,setSaving]=useState(false);
  const [msg,setMsg]=useState('');
  const [err,setErr]=useState('');

  useEffect(()=>{api.settings().then(s=>{setSettings(s);setValues(s.values);}).catch(e=>setErr(String(e.message||e)));},[]);

  const groups=useMemo(()=>{
    if(!settings)return [];
    const map=new Map<string,{key:string;label:string;hint:string}[]>();
    for(const e of settings.entries){const list=map.get(e.group)||[];list.push(e);map.set(e.group,list);}
    return [...map.entries()];
  },[settings]);

  const save=async()=>{
    setSaving(true);setMsg('');setErr('');
    try{
      const s=await api.saveSettings(values);
      setSettings(s);setValues(s.values);setMsg('已保存。域名/CORS 类配置重启服务后生效（部分立即生效）。');
    }catch(e){setErr(String((e as Error).message||e));}
    setSaving(false);
  };

  if(err && !settings)return <div className="empty"><h2>无法加载设置</h2><p>{err}</p></div>;
  if(!settings)return <div className="empty"><p>加载中…</p></div>;

  return <div className="settings-page">
    <PageHeader eyebrow="SYSTEM" title="系统设置" description="站点名称、域名接入、对象存储与安全开关统一在此维护。改动会持久化保存。" action={
      <button type="button" className="button primary" onClick={save} disabled={saving}><Save size={15}/>{saving?'保存中…':'保存配置'}</button>
    }/>
    {msg&&<p className="ok" style={{margin:'0 0 12px'}}>{msg}</p>}
    {err&&<p style={{color:'#c0392b',margin:'0 0 12px'}}>{err}</p>}
    {groups.map(([group,entries])=>(
      <section key={group} className="card" style={{marginBottom:16,padding:16,borderRadius:10,background:'var(--card,#fff)',border:'1px solid var(--border,#eee)'}}>
        <h3 style={{margin:'0 0 4px',fontSize:15}}>{group}</h3>
        {entries.map(e=>(
          <div key={e.key} style={{marginTop:12}}>
            <label htmlFor={`set-${e.key}`} style={{display:'flex',justifyContent:'space-between',fontSize:13,fontWeight:600,marginBottom:4}}>
              <span>{e.label}</span><code style={{color:'#999',fontSize:11}}>{e.key}</code>
            </label>
            <input id={`set-${e.key}`} type="text" value={values[e.key]??''}
              onChange={ev=>setValues(v=>({...v,[e.key]:ev.target.value}))}
              style={{width:'100%',padding:'8px 10px',borderRadius:6,border:'1px solid var(--border,#ddd)',fontSize:13,fontFamily:'monospace'}}/>
            {e.hint&&<p style={{margin:'3px 0 0',fontSize:12,color:'#888'}}>{e.hint}</p>}
          </div>
        ))}
      </section>
    ))}
    <style>{`.settings-page{max-width:860px}.settings-page .card{box-shadow:0 1px 3px rgba(0,0,0,.04)}`}</style>
  </div>;
}
