import json
import math
import os

import bpy
from mathutils import Vector

ROOT = r"C:\Users\vip\Documents\3d"
SOURCE = os.path.join(ROOT, "yoyo-blender", "yoyo-volume-v2.blend")
OUT_DIR = os.path.join(ROOT, "yoyo-blender", "preview-v3-identity")
OUT_BLEND = os.path.join(ROOT, "yoyo-blender", "yoyo-identity-v3.blend")
OUT_GLB = os.path.join(ROOT, "public", "models", "yoyo-identity-v3.glb")
os.makedirs(OUT_DIR, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=SOURCE)

body = bpy.data.objects.get("YOYO_VOLUME_V2")
if body is None:
    raise RuntimeError("YOYO volume base not found")

def mat(name, color, roughness=0.45, metallic=0.0):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1.0)
    material.roughness = roughness
    material.metallic = metallic
    return material

skin = mat("YOYO_Skin", (0.92, 0.65, 0.57), 0.5)
black = mat("YOYO_Eye", (0.006, 0.008, 0.012), 0.12)
gold = mat("YOYO_Gold", (0.93, 0.52, 0.08), 0.28, 0.18)
brown = mat("YOYO_Leather", (0.24, 0.075, 0.025), 0.58)
freckle = mat("YOYO_Freckle", (0.85, 0.20, 0.07), 0.48)

parts = bpy.data.collections.get("YOYO_IDENTITY_PARTS") or bpy.data.collections.new("YOYO_IDENTITY_PARTS")
if parts.name not in bpy.context.scene.collection.children:
    bpy.context.scene.collection.children.link(parts)

def move_to_parts(obj):
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    parts.objects.link(obj)
    return obj

def uv_sphere(name, location, scale, material, segments=40, rings=24):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, location=location)
    obj = move_to_parts(bpy.context.object)
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    for poly in obj.data.polygons: poly.use_smooth = True
    return obj

def cube_bevel(name, location, scale, material, bevel=0.02):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = move_to_parts(bpy.context.object)
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    modifier = obj.modifiers.new("Rounded", "BEVEL")
    modifier.width = bevel
    modifier.segments = 4
    obj.data.materials.append(material)
    return obj

def curve_tube(name, points, radius, material):
    data = bpy.data.curves.new(name + "_Curve", "CURVE")
    data.dimensions = "3D"
    data.bevel_depth = radius
    data.bevel_resolution = 4
    spline = data.splines.new("BEZIER")
    spline.bezier_points.add(len(points)-1)
    for bp, point in zip(spline.bezier_points, points):
        bp.co = point
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    obj = bpy.data.objects.new(name, data)
    parts.objects.link(obj)
    obj.data.materials.append(material)
    return obj

# Front points toward +Y. Place details slightly proud of the volume shell.
for side in (-1, 1):
    eye = uv_sphere(
        f"{'Left' if side < 0 else 'Right'}_Eye",
        (side * 0.073, 0.234, 0.603),
        (0.023, 0.011, 0.045), black
    )
    eye.rotation_euler.x = math.radians(4)
    for index, dx in enumerate((-0.022, 0.0, 0.022), 1):
        uv_sphere(
            f"{'Left' if side < 0 else 'Right'}_Freckle_{index}",
            (side * 0.112 + dx, 0.235, 0.558 - abs(dx)*0.12),
            (0.0042, 0.0023, 0.0042), freckle, 20, 12
        )

# Crescent clasp: torus with a small masking sphere is avoided; an open curve reads cleanly
# and remains an individually selectable part.
crescent_points = []
for i in range(19):
    angle = math.radians(55 + i * 250 / 18)
    crescent_points.append((0.0 + math.cos(angle)*0.030, 0.235, 0.477 + math.sin(angle)*0.030))
curve_tube("Crescent_Clasp", crescent_points, 0.008, gold)

strap = curve_tube("Satchel_Strap", [
    (-0.035, 0.229, 0.465),
    (0.015, 0.238, 0.390),
    (0.090, 0.233, 0.285),
    (0.155, 0.207, 0.205),
], 0.010, brown)

bag = cube_bevel("Satchel_Body", (0.164, 0.202, 0.238), (0.080, 0.030, 0.075), brown, 0.026)
bag.rotation_euler.y = math.radians(-7)
flap = cube_bevel("Satchel_Flap", (0.164, 0.237, 0.281), (0.083, 0.012, 0.038), brown, 0.018)
flap.rotation_euler.y = math.radians(-7)
uv_sphere("Satchel_Stud", (0.164, 0.252, 0.267), (0.009, 0.005, 0.009), gold, 24, 14)

# Warm face insert restores the face/hood separation that voxel remeshing softened.
face = uv_sphere("Face_Volume", (0.0, 0.177, 0.588), (0.172, 0.050, 0.125), skin, 64, 40)
# Keep identity parts in front of the face by creation-order independent geometry placement.

body["stage"] = "identity-parts-v3"
body["changes"] = "Added separate face, eyes, freckles, crescent clasp, strap and satchel assembly."
body["still_missing"] = "Hood/cape thickness, articulated fingers, boot soles, star cleanup and final texture projection."

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 720
scene.render.resolution_y = 960
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"

all_model = [body] + list(parts.objects)
corners = [o.matrix_world @ Vector(c) for o in all_model if o.type in {"MESH", "CURVE"} for c in o.bound_box]
mins = Vector(tuple(min(v[i] for v in corners) for i in range(3)))
maxs = Vector(tuple(max(v[i] for v in corners) for i in range(3)))
dims = maxs - mins
target = Vector((0, 0, mins.z + dims.z * 0.51))
camera = bpy.data.objects.get("Review_Camera")
scene.camera = camera
camera.data.type = "ORTHO"
camera.data.ortho_scale = dims.z * 1.13
views = {"front":(0,1,.06), "three-quarter":(.72,1,.12), "side":(1,0,.06), "back":(0,-1,.06)}
for name, direction in views.items():
    camera.location = target + Vector(direction).normalized() * max(dims) * 3
    camera.rotation_euler = (target-camera.location).to_track_quat("-Z","Y").to_euler()
    scene.render.filepath = os.path.join(OUT_DIR, f"yoyo-identity-{name}.png")
    bpy.ops.render.render(write_still=True)

bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)
bpy.ops.object.select_all(action="DESELECT")
for obj in all_model:
    obj.hide_set(False)
    obj.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.export_scene.gltf(filepath=OUT_GLB, export_format="GLB", use_selection=True, export_apply=True, export_yup=True)

report = {
    "blend": OUT_BLEND, "glb": OUT_GLB,
    "named_parts": [obj.name for obj in parts.objects],
    "pass": "identity-parts-v3", "decision": "refine-code",
    "still_missing": body["still_missing"],
}
with open(os.path.join(OUT_DIR, "report.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=False))
