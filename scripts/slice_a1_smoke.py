"""Slice an existing normalized STL as a 20 mm A1/PLA acceptance sample."""
import json
from pathlib import Path
import subprocess
import sys

root=Path.home()/'Library/Application Support/OrcaSlicer/system/BBL'
out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
def preset(kind,name):
    value=json.loads((root/kind/(name+'.json')).read_text())
    parent=value.pop('inherits',None)
    return {**(preset(kind,parent) if parent else {}),**value}

machine=preset('machine','Bambu Lab A1 0.4 nozzle')
process=preset('process','0.20mm Standard @BBL A1')
filament=preset('filament','Bambu PLA Basic @BBL A1')
process.update(curr_bed_type='Textured PEI Plate',enable_support='1',support_type='tree(auto)',brim_type='outer_only',brim_width='3')
filament['filament_colour']=['#F4EE2A']
for name,value in [('machine',machine),('process',process),('filament',filament)]:
    (out/(name+'.json')).write_text(json.dumps(value))
command=['/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer',
    '--load-settings',f'{out}/machine.json;{out}/process.json',
    '--load-filaments',str(out/'filament.json'),'--scale',str(20/120),
    '--ensure-on-bed','--arrange','1','--orient','0','--slice','0',
    '--outputdir',str(out),'--export-3mf','acceptance.gcode.3mf',sys.argv[1]]
subprocess.run(command,check=True)
