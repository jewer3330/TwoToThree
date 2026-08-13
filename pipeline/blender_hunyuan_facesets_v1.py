import json
import math
import os
from collections import Counter

import bpy
from mathutils import Vector


ROOT = r"C:\Users\vip\Documents\3d"
SOURCE = os.path.join(ROOT, "yoyo-blender", "yoyo-hunyuan-shape-v1.blend")
OUT = os.path.join(ROOT, "yoyo-blender", "hunyuan-facesets-v1")
BLEND = os.path.join(ROOT, "yoyo-blender", "yoyo-hunyuan-facesets-v1.blend")
os.makedirs(OUT, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=SOURCE)

source = next(o for o in bpy.context.scene.objects if o.type == "MESH" and o.name.startswith("YOYO_HUNYUAN"))
source.name = "YOYO_HUNYUAN_V1_LOCKED"
source.hide_render = True
source.hide_set(True)
source.hide_select = True
work = source.copy()
work.data = source.data.copy()
work.name = "YOYO_HUNYUAN_FACESETS_WORK"
bpy.context.scene.collection.objects.link(work)
work.hide_render = False
work.hide_set(False)
work.hide_select = False

corners = [work.matrix_world @ Vector(c) for c in work.bound_box]
lo = Vector(tuple(min(p[i] for p in corners) for i in range(3)))
hi = Vector(tuple(max(p[i] for p in corners) for i in range(3)))
size = hi - lo

palette = {
    "Star": (1.0, .65, .08, 1),
    "Cap": (.04, .42, .56, 1),
    "Hood": (.08, .12, .32, 1),
    "Face": (.96, .69, .62, 1),
    "Eyes": (.01, .01, .015, 1),
    "Cape": (.11, .15, .38, 1),
    "Moon": (1.0, .58, .07, 1),
    "Coat": (.82, .76, .63, 1),
    "Arm_L": (.70, .65, .54, 1),
    "Arm_R": (.70, .65, .54, 1),
    "Boot_L": (.94, .52, .06, 1),
    "Boot_R": (.94, .52, .06, 1),
    "Strap": (.38, .16, .045, 1),
    "Satchel": (.29, .09, .025, 1),
}

materials = {}
for name, color in palette.items():
    mat = bpy.data.materials.new("FS_" + name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = .58
    work.data.materials.append(mat)
    materials[name] = len(work.data.materials) - 1

def classify(poly):
    p = work.matrix_world @ poly.center
    n = (work.matrix_world.to_3x3() @ poly.normal).normalized()
    x = (p.x - (lo.x + hi.x) / 2) / size.x
    z = (p.z - lo.z) / size.z
    front = -n.y

    # Ordered seeds: small identity/accessory regions first, broad garments last.
    if z > .925 and abs(x) < .18 and p.y < .04:
        return "Star"
    if z > .73:
        return "Cap"
    if front > .18 and .49 < z < .72 and abs(x) < .27:
        # Embossed eye islands in the generated geometry.
        eye_l = ((x + .090) / .035) ** 2 + ((z - .615) / .040) ** 2 < 1
        eye_r = ((x - .090) / .035) ** 2 + ((z - .615) / .040) ** 2 < 1
        if eye_l or eye_r:
            return "Eyes"
        return "Face"
    if z > .49:
        return "Hood"
    if .405 < z < .515 and abs(x) < .12 and front > .2:
        return "Moon"
    if .36 < z < .53 and abs(x) > .31:
        return "Arm_L" if x < 0 else "Arm_R"
    if .33 < z < .52 and x > .20 and p.y < .12:
        return "Satchel"
    if .27 < z < .58 and x > -.02 and x < .25 and front > .15:
        # Diagonal band seed; later boundary smoothing follows the raised ridge.
        line = .17 - .30 * (z - .27)
        if abs(x - line) < .035:
            return "Strap"
    if .38 < z < .52:
        return "Cape"
    if z < .25:
        return "Boot_L" if x < 0 else "Boot_R"
    return "Coat"

labels = [classify(p) for p in work.data.polygons]

# Curvature-aware cleanup: only absorb isolated faces when neighbors agree and
# their normals are close. This preserves concave garment seams as boundaries.
edge_faces = {}
for poly in work.data.polygons:
    for edge in poly.edge_keys:
        edge_faces.setdefault(edge, []).append(poly.index)
neighbors = [set() for _ in work.data.polygons]
for faces in edge_faces.values():
    if len(faces) == 2:
        a, b = faces
        neighbors[a].add(b)
        neighbors[b].add(a)
protected = {"Star", "Eyes", "Moon", "Strap", "Satchel"}
for _ in range(3):
    updated = labels[:]
    for i, adjacent in enumerate(neighbors):
        if labels[i] in protected or not adjacent:
            continue
        compatible = [j for j in adjacent if work.data.polygons[i].normal.dot(work.data.polygons[j].normal) > .94]
        if not compatible:
            continue
        winner, votes = Counter(labels[j] for j in compatible).most_common(1)[0]
        if votes >= max(2, math.ceil(len(compatible) * .75)):
            updated[i] = winner
    labels = updated

counts = Counter(labels)
for poly, label in zip(work.data.polygons, labels):
    poly.material_index = materials[label]
    poly.use_smooth = True

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 720
scene.render.resolution_y = 960
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"

cam = bpy.data.objects.get("Review_Camera")
scene.camera = cam
cam.data.ortho_scale = size.z * 1.16
target = Vector((0, 0, size.z * .5))
scale = max(size)
for name, direction in {
    "front": (0, -1, .10),
    "three-quarter": (1, -1, .18),
    "side": (1, 0, .10),
    "back": (0, 1, .10),
}.items():
    cam.location = target + Vector(direction).normalized() * scale * 3
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.join(OUT, f"facesets-{name}.png")
    bpy.ops.render.render(write_still=True)

work["faceset_status"] = "preview-only; source geometry locked; boundaries require approval before mesh separation"
work["faceset_counts"] = json.dumps(counts)
bpy.ops.wm.save_as_mainfile(filepath=BLEND)
report = {
    "source": SOURCE,
    "blend": BLEND,
    "source_locked": True,
    "geometry_cut": False,
    "method": "spatial seeds + normal-continuity cleanup; concave seams preserved",
    "face_counts": dict(counts),
    "decision": "review-boundaries-before-separation",
}
with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=False))
