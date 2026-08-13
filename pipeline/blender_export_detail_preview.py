import bpy
import os

WORKSPACE=r"C:\Users\vip\Documents\3d"
OUT=os.path.join(WORKSPACE,"field-commander","public","models","field-commander-blender-detail.glb")
os.makedirs(os.path.dirname(OUT),exist_ok=True)

bpy.ops.object.select_all(action='DESELECT')
selected=[]
source=bpy.data.objects.get('Field_Commander_SF3D')
if source:
    source.hide_viewport=False;source.hide_render=False;source.select_set(True);selected.append(source)
details=bpy.data.collections.get('DETAIL_GEOMETRY')
if details:
    for obj in details.objects:
        obj.hide_viewport=False;obj.hide_render=False;obj.select_set(True);selected.append(obj)
if source:bpy.context.view_layer.objects.active=source

bpy.ops.export_scene.gltf(
    filepath=OUT,
    export_format='GLB',
    use_selection=True,
    export_apply=True,
    export_yup=True,
    export_materials='EXPORT',
    export_image_format='AUTO',
)
print({'exported':OUT,'objects':len(selected)})
