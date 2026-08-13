import os

import bpy


ROOT = r"C:\Users\vip\Documents\3d"
SOURCE = os.path.join(ROOT, "yoyo-blender", "yoyo-hunyuan-facesets-v1.blend")
OUTPUT = os.path.join(ROOT, "public", "models", "yoyo-hunyuan-facesets-preview-v1.glb")

bpy.ops.wm.open_mainfile(filepath=SOURCE)
work = bpy.data.objects.get("YOYO_HUNYUAN_FACESETS_WORK")
if work is None:
    raise RuntimeError("Face Sets work mesh missing")
work.hide_set(False)
work.hide_render = False
bpy.ops.object.select_all(action="DESELECT")
work.select_set(True)
bpy.context.view_layer.objects.active = work
bpy.ops.export_scene.gltf(
    filepath=OUTPUT,
    export_format="GLB",
    use_selection=True,
    export_apply=True,
    export_yup=True,
)
print(OUTPUT)
