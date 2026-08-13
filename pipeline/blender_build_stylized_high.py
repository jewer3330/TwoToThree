import bpy
import math

ROOT = r"C:\Users\vip\Documents\3d"
SOURCE_BLEND = ROOT + r"\field-commander\field-commander-sf3d.blend"
OUT_BLEND = ROOT + r"\field-commander\field-commander-stylized-high.blend"
OUT_GLB = ROOT + r"\public\models\field-commander-stylized-review.glb"

bpy.ops.wm.open_mainfile(filepath=SOURCE_BLEND)
source = next((o for o in bpy.context.scene.objects if o.type == "MESH"), None)
if source is None:
    raise RuntimeError("No source mesh in SF3D blend")

source.name = "Field_Commander_SF3D_Low"
high = source.copy()
high.data = source.data.copy()
high.name = "Field_Commander_Stylized_High"
bpy.context.scene.collection.objects.link(high)
high.hide_viewport = False
high.hide_render = False
high.hide_set(False)

bpy.ops.object.select_all(action="DESELECT")
high.select_set(True)
bpy.context.view_layer.objects.active = high
bpy.context.view_layer.update()

# Replace SF3D's uneven triangulation with a continuous sculptable shell.
# Object-level Remesh is stable in headless Blender and avoids viewport context.
remesh = high.modifiers.new("Uniform_Sculpt_Remesh", "REMESH")
remesh.mode = "VOXEL"
remesh.voxel_size = 0.004
remesh.use_smooth_shade = True
bpy.ops.object.modifier_apply(modifier=remesh.name)

# Relax remesh stair-stepping without shrinking the silhouette too aggressively.
smooth = high.modifiers.new("Sculpt_Base_Relax", "SMOOTH")
smooth.factor = 0.34
smooth.iterations = 4
bpy.ops.object.modifier_apply(modifier=smooth.name)

def gaussian(x, z, cx, cz, sx, sz):
    return math.exp(-0.5 * (((x-cx)/sx)**2 + ((z-cz)/sz)**2))

def segment_distance(x, z, x1, z1, x2, z2):
    dx, dz = x2-x1, z2-z1
    den = dx*dx + dz*dz
    if den == 0:
        return math.hypot(x-x1, z-z1)
    t = max(0.0, min(1.0, ((x-x1)*dx + (z-z1)*dz)/den))
    return math.hypot(x-(x1+t*dx), z-(z1+t*dz))

# Broad, stylized anatomy first: sockets, cheek plane, muzzle, jaw and chin.
for vertex in high.data.vertices:
    x, y, z = vertex.co
    if y <= 0:
        continue
    front = max(0.0, min(1.0, vertex.normal.y * 1.8))
    if front == 0:
        continue

    d = 0.0
    # Head planes and cheek volume.
    d += 0.0038 * gaussian(x, z, 0, 0.381, 0.050, 0.060)
    for side in (-1, 1):
        d += 0.0042 * gaussian(x, z, side*0.033, 0.369, 0.020, 0.020)
        d -= 0.0048 * gaussian(x, z, side*0.026, 0.397, 0.020, 0.012)
        # Eyebrow ridge and two eyelids.
        d += 0.0032 * gaussian(x, z, side*0.026, 0.415, 0.023, 0.005)
        d += 0.0025 * gaussian(x, z, side*0.026, 0.402, 0.020, 0.004)
        d += 0.0018 * gaussian(x, z, side*0.026, 0.390, 0.018, 0.004)

    # Nose: bridge merges into a stronger tip and restrained nostril wings.
    d += 0.0060 * gaussian(x, z, 0, 0.402, 0.009, 0.026)
    d += 0.0110 * gaussian(x, z, 0, 0.378, 0.013, 0.012)
    for side in (-1, 1):
        d += 0.0037 * gaussian(x, z, side*0.011, 0.373, 0.008, 0.006)
        d -= 0.0017 * gaussian(x, z, side*0.007, 0.369, 0.0035, 0.003)

    # Mouth muzzle, separate lip masses, mouth crease, chin and jaw taper.
    d += 0.0030 * gaussian(x, z, 0, 0.356, 0.027, 0.017)
    d += 0.0035 * gaussian(x, z, 0, 0.361, 0.021, 0.004)
    d -= 0.0028 * gaussian(x, z, 0, 0.356, 0.023, 0.0022)
    d += 0.0030 * gaussian(x, z, 0, 0.350, 0.019, 0.004)
    d -= 0.0017 * gaussian(x, z, 0, 0.343, 0.021, 0.004)
    d += 0.0040 * gaussian(x, z, 0, 0.332, 0.026, 0.014)

    # Raised square neckline and corset seams as medium-frequency cloth detail.
    neckline = [(-0.105,0.292),(-0.086,0.255),(0,0.244),(0.086,0.255),(0.105,0.292)]
    nd = min(segment_distance(x,z,*a,*b) for a,b in zip(neckline,neckline[1:]))
    d += 0.0035 * math.exp(-0.5*(nd/0.0042)**2)
    for bx in (-0.082,-0.054,-0.028,0.028,0.054,0.082):
        sd = segment_distance(x,z,bx,0.235,bx*0.82,0.100)
        d += 0.0024 * math.exp(-0.5*(sd/0.0032)**2)

    vertex.co.y += d * front

high.data.update()
for polygon in high.data.polygons:
    polygon.use_smooth = True

# Preserve the textured SF3D low mesh for later baking; review exports only the gray high shell.
source.hide_viewport = True
source.hide_render = True
high["stage"] = "stylized-high-base-v1"
high["intent"] = "Stylized female character; approximate likeness, not identity reconstruction"

bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)

# A browser-review copy: decimated, untextured geometry. Keep the Blender high mesh untouched.
review = high.copy()
review.data = high.data.copy()
review.name = "Field_Commander_Stylized_Review"
bpy.context.scene.collection.objects.link(review)
high.hide_viewport = True
high.hide_render = True
bpy.ops.object.select_all(action="DESELECT")
review.select_set(True)
bpy.context.view_layer.objects.active = review
dec = review.modifiers.new("Web_Review_Decimate", "DECIMATE")
dec.ratio = min(1.0, 110000 / max(1, len(review.data.polygons)))
bpy.ops.object.modifier_apply(modifier=dec.name)

for slot in list(review.material_slots):
    review.data.materials.pop(index=0)
mat = bpy.data.materials.new("Stylized_Gray")
mat.diffuse_color = (0.42, 0.45, 0.50, 1.0)
mat.roughness = 0.72
review.data.materials.append(mat)

bpy.ops.export_scene.gltf(filepath=OUT_GLB, export_format="GLB", use_selection=True)
print({"high_vertices": len(high.data.vertices), "high_faces": len(high.data.polygons),
       "review_faces": len(review.data.polygons), "blend": OUT_BLEND, "glb": OUT_GLB})
