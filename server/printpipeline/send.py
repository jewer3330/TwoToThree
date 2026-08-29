"""打印发送服务：导出多色 3MF（本地纯 Python）→ FTP 上传打印机（curl）→ MQTT 启动打印（独立模块）。"""
from __future__ import annotations
import hashlib, json, ssl, time
from pathlib import Path
from ..backends import BackendError
from .pipeline import export_multicolor_3mf  # 复用带故障转移的导出

def export_3mf(parts_dir:Path, colors:dict[str,str], output:Path, timeout_seconds:int=600):
    """远程 Blender：部件 STL + 颜色 → 多对象多色 3MF（GPU-1→GPU-2→… 故障转移）。"""
    return export_multicolor_3mf(parts_dir,colors,output,timeout_seconds=timeout_seconds)

# ---------- FTP 上传（拓竹 A1: FTPS 隐式 TLS 端口 990，用户 bblp/访问码） ----------

class BambuFTP:
    def __init__(self,ip:str,access_code:str,port:int=990):
        self.ip=ip;self.access_code=access_code;self.port=port
    def upload(self,local:Path):
        # 拓竹 990 隐式 TLS：curl --ftp-ssl 兼容最好（ftplib 对其握手行为处理不佳）
        import subprocess
        remote=f'ftps://{self.ip}/{local.name}'
        proc=subprocess.run(['curl','-s','-k','--ftp-ssl','-u',f'bblp:{self.access_code}',
                             '-T',str(local),remote],capture_output=True,text=True,timeout=120)
        if proc.returncode!=0:
            raise RuntimeError(f'FTP 上传失败: {(proc.stderr or proc.stdout)[:200]}')
        return local.name

# ---------- MQTT 打印命令 ----------

def mqtt_send_print(serial:str,ip:str,access_code:str,subtask_name:str,file_md5:str,gcode_param:str='Metadata/plate_1.gcode'):
    """发布 project_file 命令启动打印。需打印机已有上传的已切片 3MF。"""
    import paho.mqtt.client as mqtt
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLSv1_2);ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
    c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=f'bbl-print-{int(time.time())}')
    c.tls_set_context(ctx);c.username_pw_set('bblp',access_code)
    ok={'ok':False}
    def on_connect(client,userdata,flags,rc,props=None):
        code=int(rc.value) if hasattr(rc,'value') else int(rc)
        if code==0:
            payload={'print':{'command':'project_file','param':gcode_param,
                              'subtask_name':subtask_name,'profile_id':'0','project_id':'0','md5':file_md5}}
            client.publish(f'device/{serial}/request',json.dumps(payload),qos=1)
            ok['ok']=True
        else:
            ok['error']=f'MQTT 连接失败 rc={code}'
        client.disconnect()
    c.on_connect=on_connect
    try:
        c.connect(ip,8883,keepalive=10);c.loop(timeout=8)
    except Exception as exc:
        ok['error']=str(exc)[:150]
    return ok

def file_md5(path:Path)->str:
    h=hashlib.md5()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()
