"""拓竹（Bambu Lab）打印机局域网接入（独立模块）。

A1/P1/X1 系列支持 LAN 模式：MQTT over TLS (8883)，用户名 bblp，密码=访问码。
状态订阅 topic: device/<serial>/report；命令发布 topic: device/<serial>/request。
"""
from __future__ import annotations
import json, ssl, threading, time
from typing import Callable
import paho.mqtt.client as mqtt

class BambuError(RuntimeError):pass

class BambuClient:
    """单次会话：连接→订阅→收状态→断开。打印机状态实时性要求低，轮询即可。"""
    def __init__(self, ip:str, access_code:str, serial:str|None=None, timeout:int=12):
        self.ip=ip;self.access_code=access_code;self.serial=serial;self.timeout=timeout
        self.status:dict|None=None
        self._client=None;self._ready=threading.Event();self._done=threading.Event()
    def _on_connect(self,client,userdata,flags,rc,props=None):
        code=int(rc.value) if hasattr(rc,'value') else int(rc)
        if code!=0:
            self._ready.set();self._done.set();self._connect_error=f'MQTT 认证失败（rc={code}），请检查访问码'
            return
        topic='device/+/report' if not self.serial else f'device/{self.serial}/report'
        client.subscribe(topic);self._ready.set()
    def _on_message(self,client,userdata,msg):
        try:
            data=json.loads(msg.payload.decode('utf-8'))
            self.status=data
            # 从 topic 提取 serial 备用
            parts=msg.topic.split('/')
            if len(parts)>=2 and parts[1]!='+':self.serial=parts[1]
            self._done.set()
        except Exception:pass
    def fetch(self)->dict:
        """连接并读取一次打印机状态。返回 {'ok':True,'data':{...}} 或 {'ok':False,'error':...}"""
        self._connect_error=None
        try:
            ctx=ssl.SSLContext(ssl.PROTOCOL_TLSv1_2);ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
            c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=f'bbl-{int(time.time())}')
            c.tls_set_context(ctx);c.username_pw_set('bblp',self.access_code)
            c.on_connect=self._on_connect;c.on_message=self._on_message
            c.connect(self.ip,8883,keepalive=15);self._client=c
            c.loop_start()
            if not self._done.wait(self.timeout):
                # 没收到 report 也可能已连接成功（打印机空闲时也会周期上报）
                c.disconnect();c.loop_stop()
                if self._connect_error:return {'ok':False,'error':self._connect_error}
                return {'ok':False,'error':'连接成功但未收到状态上报（可能打印机未开机或访问码错误）'}
            c.disconnect();c.loop_stop()
            return {'ok':True,'data':self.status or {}}
        except Exception as exc:
            return {'ok':False,'error':str(exc)[:200]}

def parse_print(data:dict)->dict:
    """从 report JSON 提取关键状态字段。A1 空闲时无 stg_curr，按温度推断待机状态。"""
    p=data.get('print',{}) if data else {}
    def num(k,d=0):
        try:return round(float(p.get(k,d)),1)
        except Exception:return d
    stg=p.get('stg_curr') or p.get('gcode_state') or 'idle'
    # 空闲但喷嘴/热床仍在高温（预热保温）→ 待机；无 stg_curr 且低温 → 冷待机
    nozzle=num('nozzle_temper')
    if stg in ('idle',None) and nozzle>=50:
        stg='standby'
    stg_map={'idle':'空闲','standby':'待机(预热)','running':'打印中','finish':'完成','failed':'失败','pause':'暂停','prepare':'准备','unknown':'未知'}
    percent=p.get('mc_percent')
    percent=round(float(percent),1) if percent is not None else None
    fan=p.get('fan_gear') or p.get('spd_lvl') or 0
    result={
        'state':stg,'stateLabel':stg_map.get(stg,stg),
        'progress':percent,                      # 0-100
        'nozzleTemp':num('nozzle_temper'),       # 喷嘴温度 ℃
        'nozzleTarget':num('nozzle_target_temper'),
        'bedTemp':num('bed_temper'),             # 热床温度
        'bedTarget':num('bed_target_temper'),
        'chamberTemp':num('chamber_temper'),
        'speedLevel':int(fan or 0),
        'layerNum':int(p.get('layer_num') or 0),
        'totalLayers':int(p.get('total_layer_num') or 0),
        'wifiSignal':p.get('wifi_signal'),
        'remainingSeconds':int(p.get('mc_remaining_time') or 0),
        'gcodeName':(p.get('subtask_name') or p.get('gcode_file') or ''),
        'fanSpeed':int(p.get('big_fan1_speed') or 0),
        'hms':p.get('hms',[]),
    }
    ams=data.get('ams',{}) if data else {}
    if isinstance(ams,dict):
        result['amsHumidity']=ams.get('ams',[{}])[0].get('humidity') if ams.get('ams') else None
    return result
