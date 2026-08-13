import bpy
import math
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = r"C:\Users\vip\Documents\3d"
SOURCE = ROOT + r"\field-commander\field-commander-sf3d.blend"
OUT_BLEND = ROOT + r"\field-commander\field-commander-sf3d-face-patch.blend"
OUT_GLB = ROOT + r"\public\models\field-commander-sf3d-face-patch.glb"

bpy.ops.wm.open_mainfile(filepath=SOURCE)
base = bpy.data.objects.get("Field_Commander_SF3D")
if base is None:
    raise RuntimeError("Exact SF3D source object missing")
base.name = "Field_Commander_SF3D_Exact"

# Do not edit, subdivide, smooth, remesh or recalculate the source mesh.
original_vertex_count = len(base.data.vertices)
original_face_count = len(base.data.polygons)
bvh = BVHTree.FromObject(base, bpy.context.evaluated_depsgraph_get())

def gauss(x,z,cx,cz,sx,sz):
    return math.exp(-0.5*(((x-cx)/sx)**2+((z-cz)/sz)**2))

def relief(x,z):
    d = 0.00035
    for side in (-1,1):
        # Stylized but restrained socket/lid construction.
        d -= 0.0028*gauss(x,z,side*0.027,0.400,0.020,0.010)
        d += 0.0028*gauss(x,z,side*0.027,0.406,0.020,0.0035)
        d += 0.0018*gauss(x,z,side*0.027,0.394,0.018,0.0032)
        d += 0.0018*gauss(x,z,side*0.027,0.418,0.023,0.0042)
        d += 0.0022*gauss(x,z,side*0.032,0.371,0.020,0.017)
    d += 0.0045*gauss(x,z,0,0.402,0.008,0.025)
    d += 0.0080*gauss(x,z,0,0.378,0.012,0.011)
    for side in (-1,1):
        d += 0.0025*gauss(x,z,side*0.011,0.373,0.007,0.005)
    d += 0.0028*gauss(x,z,0,0.359,0.020,0.0036)
    d -= 0.0022*gauss(x,z,0,0.355,0.022,0.0020)
    d += 0.0025*gauss(x,z,0,0.350,0.018,0.0035)
    d += 0.0022*gauss(x,z,0,0.331,0.024,0.012)
    return d

# Dense face-only surface sampled directly from the exact SF3D head.
NX, NZ = 81, 91
X0, X1 = -0.066, 0.066
Z0, Z1 = 0.310, 0.447
verts=[]
valid=[]
for j in range(NZ):
    z=Z0+(Z1-Z0)*j/(NZ-1)
    for i in range(NX):
        x=X0+(X1-X0)*i/(NX-1)
        hit, normal, _, _ = bvh.ray_cast(Vector((x,0.20,z)), Vector((0,-1,0)), 0.40)
        ok = hit is not None and normal.y > 0.12
        valid.append(ok)
        if not ok:
            verts.append((x,0,z)); continue
        # Feather to zero at patch border: no visible ledge and no body modification.
        ux=min((x-X0)/(X1-X0),(X1-x)/(X1-X0))*2
        uz=min((z-Z0)/(Z1-Z0),(Z1-z)/(Z1-Z0))*2
        feather=max(0.0,min(1.0,min(ux,uz)/0.22))
        verts.append(tuple(hit + normal*(relief(x,z)*feather)))

faces=[]
for j in range(NZ-1):
    for i in range(NX-1):
        a=j*NX+i; b=a+1; c=a+NX+1; d=a+NX
        if valid[a] and valid[b] and valid[c] and valid[d]:
            faces.append((a,b,c,d))

mesh=bpy.data.meshes.new("SF3D_Face_Sculpt_Patch_Mesh")
mesh.from_pydata(verts,[],faces)
mesh.update()
patch=bpy.data.objects.new("SF3D_Face_Sculpt_Patch",mesh)
bpy.context.scene.collection.objects.link(patch)
for poly in mesh.polygons:
    poly.use_smooth=True

# Reuse the exact source material so gray/textured review remains visually coherent.
if base.data.materials:
    patch.data.materials.append(base.data.materials[0])
patch["method"]="Dense raycast patch over untouched SF3D mesh"
patch["scope"]="Facial surface only"

assert len(base.data.vertices)==original_vertex_count
assert len(base.data.polygons)==original_face_count
bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)

bpy.ops.object.select_all(action="DESELECT")
base.hide_set(False); base.select_set(True)
patch.hide_set(False); patch.select_set(True)
bpy.context.view_layer.objects.active=base
bpy.ops.export_scene.gltf(filepath=OUT_GLB,export_format="GLB",use_selection=True)
print({"base_vertices":len(base.data.vertices),"base_faces":len(base.data.polygons),
       "patch_vertices":len(mesh.vertices),"patch_faces":len(mesh.polygons),
       "blend":OUT_BLEND,"glb":OUT_GLB})
