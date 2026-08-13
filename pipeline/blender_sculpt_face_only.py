import bpy
import math

ROOT = r"C:\Users\vip\Documents\3d"
SOURCE = ROOT + r"\field-commander\field-commander-sf3d.blend"
OUT_BLEND = ROOT + r"\field-commander\field-commander-sf3d-face-sculpt.blend"
OUT_GLB = ROOT + r"\public\models\field-commander-sf3d-face-sculpt.glb"

bpy.ops.wm.open_mainfile(filepath=SOURCE)
obj = next((o for o in bpy.context.scene.objects if o.type == "MESH"), None)
if obj is None:
    raise RuntimeError("SF3D mesh not found")
obj.name = "Field_Commander_SF3D_FaceSculpt"
bpy.ops.object.select_all(action="DESELECT")
obj.hide_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

# SIMPLE subdivision adds local working density while preserving the SF3D body silhouette exactly.
sub = obj.modifiers.new("Face_Working_Density", "SUBSURF")
sub.subdivision_type = "SIMPLE"
sub.levels = 3
sub.render_levels = 3
bpy.ops.object.modifier_apply(modifier=sub.name)

def g(x, z, cx, cz, sx, sz):
    return math.exp(-0.5 * (((x-cx)/sx)**2 + ((z-cz)/sz)**2))

def face_mask(x, y, z):
    # Confine all changes to the front of the head; torso, clothing, limbs and rear hair stay intact.
    vertical = max(0.0, min(1.0, (z-0.300)/0.045)) * max(0.0, min(1.0, (0.468-z)/0.025))
    lateral = max(0.0, min(1.0, (0.073-abs(x))/0.025))
    front = max(0.0, min(1.0, (y+0.004)/0.050))
    return vertical * lateral * front

# First relax only the facial patch. This removes inherited triangular planes without changing outfit/body.
mesh = obj.data
neighbors = [set() for _ in mesh.vertices]
for edge in mesh.edges:
    a, b = edge.vertices
    neighbors[a].add(b)
    neighbors[b].add(a)
for _ in range(5):
    old = [v.co.copy() for v in mesh.vertices]
    for v in mesh.vertices:
        x, y, z = old[v.index]
        mask = face_mask(x, y, z)
        if mask <= 0 or not neighbors[v.index]:
            continue
        avg = sum((old[i] for i in neighbors[v.index]), old[v.index]*0) / len(neighbors[v.index])
        # Tangentially mild relaxation; mask feather prevents a seam around the head patch.
        v.co = old[v.index].lerp(avg, 0.22 * mask)

mesh.update()

# Stylization applies only to facial anatomy: readable eyes/nose/lips with restrained proportions.
for v in mesh.vertices:
    x, y, z = v.co
    mask = face_mask(x, y, z)
    if mask <= 0:
        continue
    d = 0.0
    # Broad facial plane and cheeks.
    d += 0.0018*g(x,z,0,0.382,0.050,0.052)
    for side in (-1, 1):
        d += 0.0032*g(x,z,side*0.031,0.370,0.020,0.018)
        # Eye socket recess with upper/lower eyelid rims.
        d -= 0.0050*g(x,z,side*0.027,0.400,0.019,0.010)
        d += 0.0033*g(x,z,side*0.027,0.406,0.020,0.0038)
        d += 0.0022*g(x,z,side*0.027,0.394,0.018,0.0035)
        d += 0.0021*g(x,z,side*0.027,0.420,0.024,0.0045)
    # Nose bridge, tip, alar wings and nostril cues.
    d += 0.0055*g(x,z,0,0.401,0.008,0.025)
    d += 0.0100*g(x,z,0,0.378,0.012,0.011)
    for side in (-1,1):
        d += 0.0032*g(x,z,side*0.011,0.373,0.007,0.0055)
        d -= 0.0018*g(x,z,side*0.0065,0.369,0.003,0.0025)
    # Philtrum, separate lips and chin plane.
    d -= 0.0012*g(x,z,0,0.365,0.005,0.006)
    d += 0.0034*g(x,z,0,0.359,0.020,0.0037)
    d -= 0.0028*g(x,z,0,0.355,0.022,0.0020)
    d += 0.0030*g(x,z,0,0.350,0.018,0.0037)
    d -= 0.0014*g(x,z,0,0.343,0.020,0.0035)
    d += 0.0032*g(x,z,0,0.330,0.025,0.012)
    v.co.y += d * mask

mesh.update()
for poly in mesh.polygons:
    poly.use_smooth = True

obj["stage"] = "sf3d-face-only-sculpt-v1"
obj["preservation"] = "Body, clothing and silhouette inherited from original SF3D; only front facial patch modified"
obj["style"] = "Stylized facial anatomy only"
bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)

# Export the full working mesh. Do not globally decimate: even a high face budget can alter
# the SF3D body and garment silhouette, which must remain byte-for-byte positional outside face.
review = obj.copy()
review.data = obj.data.copy()
review.name = "Field_Commander_FaceSculpt_Review"
bpy.context.scene.collection.objects.link(review)
obj.hide_viewport = True
obj.hide_render = True
bpy.ops.object.select_all(action="DESELECT")
review.select_set(True)
bpy.context.view_layer.objects.active = review
review.data.materials.clear()
mat = bpy.data.materials.new("Face_Sculpt_Gray")
mat.diffuse_color = (0.48,0.50,0.54,1)
mat.roughness = 0.68
review.data.materials.append(mat)
bpy.ops.export_scene.gltf(filepath=OUT_GLB, export_format="GLB", use_selection=True)
print({"working_vertices":len(obj.data.vertices),"working_faces":len(obj.data.polygons),
       "review_faces":len(review.data.polygons),"blend":OUT_BLEND,"glb":OUT_GLB})
