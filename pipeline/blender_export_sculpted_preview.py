import bpy
import os

OUT=r"C:\Users\vip\Documents\3d\field-commander\public\models\field-commander-blender-sculpted.glb"
obj=bpy.data.objects.get("Field_Commander_Sculpted")
if not obj:raise RuntimeError("Sculpted object missing")
bpy.ops.object.select_all(action='DESELECT');obj.hide_viewport=False;obj.hide_render=False;obj.select_set(True);bpy.context.view_layer.objects.active=obj
bpy.ops.export_scene.gltf(filepath=OUT,export_format='GLB',use_selection=True,export_apply=True,export_yup=True,export_materials='EXPORT',export_image_format='AUTO')
print({"exported":OUT,"vertices":len(obj.data.vertices),"polygons":len(obj.data.polygons)})
