import json
import os

import bpy


ROOT = r"C:\Users\vip\Documents\3d"
SOURCE = os.path.join(ROOT, "yoyo-blender", "yoyo-hunyuan-facesets-v1.blend")
OUT_BLEND = os.path.join(ROOT, "yoyo-blender", "yoyo-hunyuan-parts-preview-v1.blend")
OUT_GLB = os.path.join(ROOT, "public", "models", "yoyo-hunyuan-parts-preview-v1.glb")
REPORT = os.path.join(ROOT, "yoyo-blender", "hunyuan-facesets-v1", "parts-preview-report.json")

bpy.ops.wm.open_mainfile(filepath=SOURCE)
source = bpy.data.objects.get("YOYO_HUNYUAN_V1_LOCKED")
work = bpy.data.objects.get("YOYO_HUNYUAN_FACESETS_WORK")
if source is None or work is None:
    raise RuntimeError("Expected locked source and Face Sets work mesh")

source.hide_set(True)
source.hide_render = True
source.hide_select = True
work.hide_set(False)
work.hide_render = False
work.hide_select = False

# Separate the reversible working copy by its reviewed material regions.
bpy.ops.object.select_all(action="DESELECT")
work.select_set(True)
bpy.context.view_layer.objects.active = work
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.separate(type="MATERIAL")
bpy.ops.object.mode_set(mode="OBJECT")

parts = [o for o in bpy.context.selected_objects if o.type == "MESH"]
for obj in parts:
    material = next((slot.material for slot in obj.material_slots if slot.material), None)
    label = material.name.removeprefix("FS_") if material else obj.name
    obj.name = "PART_" + label
    obj.data.name = obj.name + "_Mesh"
    obj["part_name"] = label
    obj["preview_status"] = "reversible working-copy separation; boundaries not approved"

# Keep only visible part objects selected for export.
bpy.ops.object.select_all(action="DESELECT")
for obj in parts:
    obj.select_set(True)
bpy.context.view_layer.objects.active = parts[0]
bpy.ops.export_scene.gltf(
    filepath=OUT_GLB,
    export_format="GLB",
    use_selection=True,
    export_apply=True,
    export_yup=True,
)
bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)

report = {
    "source_locked": source.name,
    "working_copy": work.name,
    "part_count": len(parts),
    "parts": sorted(o.name for o in parts),
    "glb": OUT_GLB,
    "blend": OUT_BLEND,
    "status": "preview separation only; boundaries require review",
}
with open(REPORT, "w", encoding="utf-8") as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=False))
