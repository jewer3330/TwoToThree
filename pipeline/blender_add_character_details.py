import bpy
import math
import os
from mathutils import Vector

WORKSPACE = r"C:\Users\vip\Documents\3d"
BLEND_PATH = os.path.join(WORKSPACE, "field-commander", "field-commander-sf3d-detailed.blend")

for name in ("SF3D_ORIGINAL_BACKUP", "DETAIL_GEOMETRY", "REFERENCE_IMAGES"):
    collection = bpy.data.collections.get(name)
    if collection:
        for obj in list(collection.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(collection)

source = bpy.data.objects["Field_Commander_SF3D"]
backup_collection = bpy.data.collections.new("SF3D_ORIGINAL_BACKUP")
bpy.context.scene.collection.children.link(backup_collection)
backup = source.copy()
backup.data = source.data.copy()
backup.name = "Field_Commander_SF3D_Original"
backup.hide_viewport = True
backup.hide_render = True
backup_collection.objects.link(backup)

detail_collection = bpy.data.collections.new("DETAIL_GEOMETRY")
bpy.context.scene.collection.children.link(detail_collection)
ref_collection = bpy.data.collections.new("REFERENCE_IMAGES")
bpy.context.scene.collection.children.link(ref_collection)

def move_to_collection(obj, collection):
    for old in list(obj.users_collection):
        old.objects.unlink(obj)
    collection.objects.link(obj)

def material(name, color, roughness=0.5, metallic=0.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.roughness = roughness
    mat.metallic = metallic
    return mat

skin = material("Detail_Skin", (0.42, 0.19, 0.13), 0.58)
lip = material("Detail_Lip", (0.34, 0.055, 0.045), 0.44)
dark = material("Detail_Leather", (0.065, 0.025, 0.018), 0.48)
blue = material("Detail_Blue", (0.0, 0.22, 0.48), 0.52)
metal = material("Detail_Metal", (0.42, 0.39, 0.34), 0.27, 0.72)
eye_white = material("Detail_EyeWhite", (0.72, 0.68, 0.61), 0.25)
iris = material("Detail_Iris", (0.12, 0.035, 0.018), 0.2)

def uv_sphere(name, location, scale, mat, segments=32):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=16, location=location)
    obj = bpy.context.object; obj.name = name; obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat); move_to_collection(obj, detail_collection)
    for p in obj.data.polygons: p.use_smooth = True
    return obj

def curve_tube(name, points, radius, mat, bevel_resolution=3):
    curve = bpy.data.curves.new(name + "_Curve", "CURVE")
    curve.dimensions = "3D"; curve.bevel_depth = radius; curve.bevel_resolution = bevel_resolution
    spline = curve.splines.new("BEZIER"); spline.bezier_points.add(len(points)-1)
    for bp, co in zip(spline.bezier_points, points):
        bp.co = co; bp.handle_left_type = "AUTO"; bp.handle_right_type = "AUTO"
    obj = bpy.data.objects.new(name, curve); detail_collection.objects.link(obj); obj.data.materials.append(mat)
    return obj

def cylinder(name, location, radius, depth, mat, rotation=(math.pi/2,0,0)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=radius, depth=depth, location=location, rotation=rotation)
    obj=bpy.context.object; obj.name=name; obj.data.materials.append(mat); move_to_collection(obj, detail_collection)
    for p in obj.data.polygons: p.use_smooth=True
    return obj

# Coordinate contract: Z is height, negative Y is the visible front of the imported glTF.
front_y = -0.091

# Face relief: separate low-profile anatomy that can be adjusted against the front/side references.
for side in (-1, 1):
    uv_sphere(f"EyeBall_{'L' if side < 0 else 'R'}", (side*0.027, front_y-0.002, 0.395), (0.013,0.008,0.008), eye_white)
    uv_sphere(f"Iris_{'L' if side < 0 else 'R'}", (side*0.027, front_y-0.010, 0.395), (0.005,0.002,0.005), iris, 24)
    curve_tube(f"UpperLid_{'L' if side < 0 else 'R'}", [(side*0.042,front_y-0.011,0.399),(side*0.027,front_y-0.014,0.405),(side*0.012,front_y-0.011,0.399)],0.0018,dark)
    curve_tube(f"Brow_{'L' if side < 0 else 'R'}", [(side*0.044,front_y-0.007,0.417),(side*0.028,front_y-0.010,0.422),(side*0.011,front_y-0.008,0.418)],0.0022,dark)
uv_sphere("NoseTip", (0,front_y-0.014,0.378), (0.008,0.009,0.009), skin)
curve_tube("NoseBridge", [(0,front_y-0.004,0.412),(0,front_y-0.010,0.392),(0,front_y-0.014,0.378)],0.0025,skin)
curve_tube("UpperLip", [(-0.018,front_y-0.012,0.358),(0,front_y-0.017,0.361),(0.018,front_y-0.012,0.358)],0.0023,lip)
curve_tube("LowerLip", [(-0.016,front_y-0.011,0.354),(0,front_y-0.015,0.350),(0.016,front_y-0.011,0.354)],0.0020,lip)

# Garment relief: corset boning, neckline piping, front lacing and metal eyelets.
curve_tube("SquareNeckline", [(-0.105,front_y-0.005,0.292),(-0.086,front_y-0.012,0.255),(0,front_y-0.015,0.244),(0.086,front_y-0.012,0.255),(0.105,front_y-0.005,0.292)],0.0042,blue)
for i,x in enumerate((-0.085,-0.060,-0.035,0.035,0.060,0.085)):
    curve_tube(f"CorsetBone_{i+1}", [(x,front_y-0.010,0.238),(x*0.82,front_y-0.014,0.095)],0.0027,dark)
for i,z in enumerate((0.225,0.204,0.183,0.162,0.141,0.120)):
    for side in (-1,1):
        cylinder(f"Eyelet_{i}_{side}",(side*0.019,front_y-0.017,z),0.0031,0.0024,metal)
    curve_tube(f"CorsetLace_{i}",[(-0.019,front_y-0.020,z),(0.019,front_y-0.021,z-0.010)],0.0016,blue,2)

# Collar buttons and sleeve seam accents.
for i,z in enumerate((0.326,0.315,0.304)):
    uv_sphere(f"CollarButton_{i+1}",(0,front_y-0.014,z),(0.004,0.0025,0.004),metal,20)
for side in (-1,1):
    curve_tube(f"SleeveFold_{side}_1",[(side*0.112,front_y-0.008,0.279),(side*0.132,front_y-0.014,0.263),(side*0.142,front_y-0.009,0.244)],0.0025,blue)
    curve_tube(f"SleeveFold_{side}_2",[(side*0.118,front_y-0.006,0.255),(side*0.139,front_y-0.012,0.238),(side*0.145,front_y-0.006,0.220)],0.0022,dark)

# Non-rendering reference images for Blender alignment.
def reference_empty(name, path, location, rotation, scale):
    img = bpy.data.images.load(path, check_existing=True)
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "IMAGE"; obj.data = img
    obj.location = location; obj.rotation_euler = rotation; obj.empty_display_size = scale
    obj.color[3] = 0.35; obj.hide_render = True; ref_collection.objects.link(obj)
    return obj

reference_empty("REF_FRONT", os.path.join(WORKSPACE,"field-commander","front.png"),(0,0.13,0),(math.pi/2,0,0),0.96)
reference_empty("REF_SIDE", os.path.join(WORKSPACE,"field-commander","side.png"),(0.22,0,0),(math.pi/2,0,math.pi/2),0.96)
reference_empty("REF_BACK", os.path.join(WORKSPACE,"field-commander","back.png"),(0,-0.13,0),(math.pi/2,0,math.pi),0.96)

detail_collection["stage"] = "face-and-garment-relief-v1"
detail_collection["limitations"] = "Separate detail geometry; not yet shrinkwrapped, retopologized, or baked."
bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
print({"detail_objects":len(detail_collection.objects),"reference_objects":len(ref_collection.objects),"saved":BLEND_PATH})
