import bpy, json
from mathutils import Vector

ROOT=r"C:\Users\vip\Documents\3d"
bpy.ops.wm.open_mainfile(filepath=ROOT+r"\field-commander\field-commander-sf3d.blend")
rows=[]
for o in bpy.context.scene.objects:
    if o.type != 'MESH':
        continue
    corners=[o.matrix_world @ Vector(c) for c in o.bound_box]
    mins=[min(v[i] for v in corners) for i in range(3)]
    maxs=[max(v[i] for v in corners) for i in range(3)]
    rows.append({"name":o.name,"vertices":len(o.data.vertices),"faces":len(o.data.polygons),
                 "hidden":o.hide_get(),"hide_viewport":o.hide_viewport,
                 "min":mins,"max":maxs,"materials":[m.name for m in o.data.materials]})
print(json.dumps(rows,indent=2))
