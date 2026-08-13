import json, os
import bpy
from mathutils import Vector

ROOT = r"C:\Users\vip\Documents\3d"
SOURCE = os.path.join(ROOT, "yoyo-blender", "yoyo-volume-v2.blend")
REFERENCE = os.path.join(ROOT, "public", "yoyo-reference.png")
OUT_DIR = os.path.join(ROOT, "yoyo-blender", "free-workbench")
BLEND = os.path.join(ROOT, "yoyo-blender", "yoyo-free-sculpt-paint.blend")
os.makedirs(OUT_DIR, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=SOURCE)
source = bpy.data.objects.get("YOYO_VOLUME_V2")
if source is None:
    raise RuntimeError("YOYO_VOLUME_V2 baseline missing")

# Keep the accepted volume in the same file as an immutable visual/geometry reference.
source.name = "YOYO_BASELINE_LOCKED"
source.hide_render = True
source.hide_set(True)
source.hide_select = True
source["role"] = "immutable-baseline"

work = source.copy()
work.data = source.data.copy()
work.name = "YOYO_SCULPT_WORK"
bpy.context.scene.collection.objects.link(work)
work.hide_render = False
work.hide_set(False)
work.hide_select = False
work["role"] = "multires-sculpt-and-paint"
work["baseline"] = "YOYO_BASELINE_LOCKED"

bpy.ops.object.select_all(action="DESELECT")
work.select_set(True)
bpy.context.view_layer.objects.active = work

# UVs are authored at the locked base level. Smart Project is robust for the fused
# SF3D-derived shell and gives the paint tools a usable first-pass atlas.
if not work.data.uv_layers:
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=0.03, area_weight=0.0, correct_aspect=True, scale_to_bounds=True)
    bpy.ops.object.mode_set(mode="OBJECT")
work.data.uv_layers.active.name = "YOYO_UV0"

# Initialize broad Face Sets via the sculpt face-set attribute. Values are coarse
# workflow masks only, not final color boundaries; artists refine them with lasso/polyline.
attr = work.data.attributes.get(".sculpt_face_set")
if attr is None:
    attr = work.data.attributes.new(".sculpt_face_set", "INT", "FACE")

pts = [work.matrix_world @ Vector(c) for c in work.bound_box]
lo = Vector(tuple(min(p[i] for p in pts) for i in range(3)))
hi = Vector(tuple(max(p[i] for p in pts) for i in range(3)))
size = hi - lo
face_set_counts = {}
for poly, item in zip(work.data.polygons, attr.data):
    p = work.matrix_world @ poly.center
    q = (p.z - lo.z) / size.z
    xn = abs((p.x - (lo.x + hi.x) * .5) / (size.x * .5))
    # 1 boots, 2 legs, 3 coat, 4 hands/sleeves, 5 cape, 6 face/hood, 7 cap.
    if q < .20: region = 1
    elif q < .30: region = 2
    elif q < .53: region = 4 if xn > .58 else 3
    elif q < .66: region = 5
    elif q < .84: region = 6
    else: region = 7
    item.value = region
    face_set_counts[str(region)] = face_set_counts.get(str(region), 0) + 1

# Multires is intentionally non-applied. Level 0 remains the accepted baseline;
# level 1 is the first detail layer. Users can add one more level only when needed.
multires = work.modifiers.get("YOYO_Multires") or work.modifiers.new("YOYO_Multires", "MULTIRES")
bpy.context.view_layer.objects.active = work
bpy.ops.object.multires_subdivide(modifier=multires.name, mode="CATMULL_CLARK")
multires.levels = 1
multires.sculpt_levels = 1
multires.render_levels = 1
multires.show_only_control_edges = True

# 4K paint targets and a single PBR material. Images are packed into the blend now;
# artists save external PNGs after real strokes are added.
def image(name, color, colorspace="sRGB"):
    existing = bpy.data.images.get(name)
    img = existing or bpy.data.images.new(name, width=4096, height=4096, alpha=False, float_buffer=False)
    img.generated_color = color
    img.colorspace_settings.name = colorspace
    img.pack()
    return img

base_color = image("YOYO_BaseColor_4K", (0.72, 0.72, 0.72, 1), "sRGB")
roughness = image("YOYO_Roughness_4K", (0.58, 0.58, 0.58, 1), "Non-Color")
normal = image("YOYO_Normal_4K", (0.5, 0.5, 1.0, 1), "Non-Color")

mat = bpy.data.materials.get("YOYO_Paint_PBR") or bpy.data.materials.new("YOYO_Paint_PBR")
mat.use_nodes = True
nodes = mat.node_tree.nodes
links = mat.node_tree.links
for node in list(nodes): nodes.remove(node)
out = nodes.new("ShaderNodeOutputMaterial")
bsdf = nodes.new("ShaderNodeBsdfPrincipled")
tex_base = nodes.new("ShaderNodeTexImage"); tex_base.name = "PAINT_BaseColor"; tex_base.image = base_color
tex_rough = nodes.new("ShaderNodeTexImage"); tex_rough.name = "PAINT_Roughness"; tex_rough.image = roughness
tex_normal = nodes.new("ShaderNodeTexImage"); tex_normal.name = "PAINT_Normal"; tex_normal.image = normal
nmap = nodes.new("ShaderNodeNormalMap")
links.new(tex_base.outputs["Color"], bsdf.inputs["Base Color"])
links.new(tex_rough.outputs["Color"], bsdf.inputs["Roughness"])
links.new(tex_normal.outputs["Color"], nmap.inputs["Color"])
links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
work.data.materials.clear(); work.data.materials.append(mat)

# Reference-alignment camera. The background image appears only in camera view and
# is the stencil/alignment authority for front projection painting.
scene = bpy.context.scene
camera = bpy.data.objects.get("YOYO_REFERENCE_CAMERA")
if camera is None:
    cam_data = bpy.data.cameras.new("YOYO_REFERENCE_CAMERA")
    camera = bpy.data.objects.new("YOYO_REFERENCE_CAMERA", cam_data)
    scene.collection.objects.link(camera)
camera.data.type = "ORTHO"
camera.data.ortho_scale = size.z * 1.08
target = Vector(((lo.x + hi.x) * .5, (lo.y + hi.y) * .5, lo.z + size.z * .51))
camera.location = target + Vector((0, 1, .025)).normalized() * max(size) * 3
camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = camera

camera.data.background_images.clear()
bg = camera.data.background_images.new()
bg.image = bpy.data.images.load(REFERENCE, check_existing=True)
bg.display_depth = "FRONT"
bg.alpha = 0.32
bg.frame_method = "FIT"
camera.data.show_background_images = True
camera["reference_path"] = REFERENCE
camera["usage"] = "Lock this camera for stencil alignment and front projection."

# A dedicated reference plane beside the model remains visible in rendered workbench previews.
bpy.ops.mesh.primitive_plane_add(size=2, location=(size.x * 1.35, .08, target.z))
ref_plane = bpy.context.object
ref_plane.name = "REFERENCE_BOARD"
ref_plane.scale = (size.z * .374, size.z * .5, 1)
ref_plane.rotation_euler = (1.57079632679, 0, 0)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
ref_mat = bpy.data.materials.new("Reference_Board_Material"); ref_mat.use_nodes = True
rnodes=ref_mat.node_tree.nodes; rlinks=ref_mat.node_tree.links
rbsdf=rnodes.get("Principled BSDF"); rtex=rnodes.new("ShaderNodeTexImage"); rtex.image=bg.image
rlinks.new(rtex.outputs["Color"],rbsdf.inputs["Base Color"]);rbsdf.inputs["Roughness"].default_value=1
ref_plane.data.materials.append(ref_mat)
ref_plane.hide_render = True
ref_plane.hide_select = True

scene["YOYO_WORKFLOW"] = json.dumps({
    "baseline": "YOYO_BASELINE_LOCKED",
    "sculpt": "YOYO_SCULPT_WORK",
    "camera": "YOYO_REFERENCE_CAMERA",
    "reference": REFERENCE,
    "face_sets": {"1":"boots","2":"legs","3":"coat","4":"arms-hands","5":"cape","6":"face-hood","7":"cap"},
    "rule": "Never edit level 0 silhouette; sculpt level 1+ with Face Set isolation."
}, ensure_ascii=False)

bpy.ops.wm.save_as_mainfile(filepath=BLEND)
report = {
    "blend": BLEND,
    "baseline_dimensions": list(size),
    "base_faces": len(work.data.polygons),
    "multires_level": multires.levels,
    "uv": work.data.uv_layers.active.name,
    "paint_images": [base_color.name, roughness.name, normal.name],
    "face_set_counts": face_set_counts,
    "reference_camera": camera.name,
    "next": "Open Blender file, enter camera view, refine Face Sets with lasso/polyline, then sculpt level 1 and stencil-paint BaseColor."
}
with open(os.path.join(OUT_DIR, "workbench-report.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=False))
