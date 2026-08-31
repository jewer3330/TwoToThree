"""打印机管理 API 路由（独立模块）。"""
from __future__ import annotations
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from . import registry
from .bambu import BambuClient, parse_print
from .probe import PrinterProbeThread

router=APIRouter(prefix='/api/printer',tags=['printer'])

class PrinterInput(BaseModel):
    name:str|None=None;model:str='A1';ip:str=Field(min_length=7);accessCode:str='';serial:str='';enabled:bool=True
class PrinterPatch(BaseModel):
    name:str|None=None;model:str|None=None;ip:str|None=None;accessCode:str|None=None;serial:str|None=None;enabled:bool|None=None

@router.get('/printers')
def list_printers():return registry.list_printers()

@router.post('/printers',status_code=201)
def create_printer(body:PrinterInput):
    try:return registry.add_printer(body.model_dump(exclude_none=True))
    except ValueError as exc:raise HTTPException(409,str(exc))

@router.patch('/printers/{printer_id}')
def patch_printer(printer_id:str,body:PrinterPatch):
    try:return registry.update_printer(printer_id,body.model_dump(exclude_none=True))
    except KeyError:raise HTTPException(404,'打印机不存在')

@router.delete('/printers/{printer_id}',status_code=204)
def remove_printer(printer_id:str):registry.delete_printer(printer_id)

@router.post('/printers/{printer_id}/probe')
def probe_printer(printer_id:str):
    p=registry.get_printer(printer_id)
    if not p:raise HTTPException(404,'打印机不存在')
    client=BambuClient(p['ip'],p['accessCode'],p.get('serial') or None)
    res=client.fetch()
    if res['ok']:
        parsed=parse_print(res['data'])
        registry.set_state(printer_id,ok=True,status=parsed,error=None)
        return {'ok':True,'status':parsed,'serial':client.serial}
    registry.set_state(printer_id,ok=False,status={},error=res['error'])
    raise HTTPException(502,res['error'])

@router.post('/printers/{printer_id}/toggle')
def toggle_printer(printer_id:str):
    try:
        p=registry.get_printer(printer_id)
        return registry.update_printer(printer_id,{'enabled':not p['enabled']})
    except KeyError:raise HTTPException(404,'打印机不存在')

@router.get('/overview')
def overview():return registry.summary()

def start_services():
    PrinterProbeThread(interval=20).start()
