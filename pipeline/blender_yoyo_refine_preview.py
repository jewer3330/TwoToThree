import json
import math
import os

import bpy
from mathutils import Vector

ROOT = r"C:\Users\vip\Documents\3d"
SOURCE = os.path.join(ROOT, "yoyo-blender", "yoyo-sf3d-base.blend")
OUT_DIR = os.path.join(ROOT, "yoyo-blender", "preview-v1")
OUT_BLEND = os.path.join(ROOT, "yoyo-blender", "yoyo-refined-v1.blend")
OUT_GLB = os.path.join(ROOT, "public", "models", "yoyo-refined-v1.glb")
os.makedirs(OUT_DIR, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=SOURCE)
source = next((o for o in bpy.context.scene.objects if o.type == "MESH" and o.name.startswith("YOYO_SF3D")), None)
if source is None:
    raise RuntimeError("YOYO SF3D source mesh not found")

source.name = "YOYO_SF3D_ORIGINAL"
source.hide_render = True
source.hide_set(True)

work = source.copy()
work.data = source.data.copy()
work.name = "YOYO_REFINED_V1"
bpy.context.scene.collection.objects.link(work)
work.hide_render = False
work.hide_set(False)
bpy.ops.object.select_all(action="DESELECT")
work.select_set(True)
bpy.context.view_layer.objects.active = work

# Preserve the SF3D UVs/material while reducing faceted shading. Catmull-Clark is
# kept non-applied in the authoring file; the exported preview evaluates it.
sub = work.modifiers.new("Preview_Subdivision", "SUBSURF")
sub.subdivision_type = "CATMULL_CLARK"
sub.levels = 1
sub.render_levels = 1
sub.show_only_control_edges = True

smooth = work.modifiers.new("Surface_Relax", "CORRECTIVE_SMOOTH")
smooth.factor = 0.16
smooth.iterations = 3
smooth.scale = 1.0
smooth.smooth_type = "LENGTH_WEIGHTED"
smooth.use_only_smooth = True

for poly in work.data.polygons:
    poly.use_smooth = True
work["stage"] = "sf3d-surface-cleanup-v1"
work["changes"] = "Non-destructive subdivision plus restrained corrective smoothing."
work["still_missing"] = "Separate face, fingers, cape thickness, bag hardware, and inferred back topology."

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 720
scene.render.resolution_y = 960
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False

meshes = [work]
corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
mins = Vector(tuple(min(v[i] for v in corners) for i in range(3)))
maxs = Vector(tuple(max(v[i] for v in corners) for i in range(3)))
dims = maxs - mins
center = (mins + maxs) * 0.5
target = Vector((center.x, center.y, mins.z + dims.z * 0.51))
scale = max(dims)

camera = bpy.data.objects.get("Review_Camera")
if camera is None:
    data = bpy.data.cameras.new("Review_Camera")
    camera = bpy.data.objects.new("Review_Camera", data)
    scene.collection.objects.link(camera)
scene.camera = camera
camera.data.type = "ORTHO"
camera.data.ortho_scale = dims.z * 1.13

# The SF3D textured face points toward Blender +Y.
views = {
    "front": (0, 1, 0.06),
    "three-quarter": (0.72, 1, 0.12),
    "side": (1, 0, 0.06),
    "back": (0, -1, 0.06),
}
for name, direction in views.items():
    camera.location = target + Vector(direction).normalized() * scale * 3.0
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.join(OUT_DIR, f"yoyo-{name}.png")
    bpy.ops.render.render(write_still=True)

bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)

# Export only the cleaned working mesh. Keep the modifiers evaluated and retain SF3D material/UV.
bpy.ops.object.select_all(action="DESELECT")
work.select_set(True)
bpy.context.view_layer.objects.active = work
bpy.ops.export_scene.gltf(
    filepath=OUT_GLB,
    export_format="GLB",
    use_selection=True,
    export_apply=True,
    export_yup=True,
    export_materials="EXPORT",
    export_image_format="AUTO",
)

report = {
    "blend": OUT_BLEND,
    "glb": OUT_GLB,
    "source_vertices": len(source.data.vertices),
    "source_polygons": len(source.data.polygons),
    "pass": "surface-cleanup-v1",
    "decision": "refine-code",
    "still_missing": work["still_missing"],
}
with open(os.path.join(OUT_DIR, "report.json"), "w", encoding="utf-8") as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=False))
