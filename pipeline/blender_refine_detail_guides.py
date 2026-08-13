import bpy
import os

collection=bpy.data.collections.get("DETAIL_GEOMETRY")
for obj in collection.objects:
    if obj.type == "CURVE":
        obj.data.bevel_depth *= 0.38
    elif obj.type == "MESH":
        factor=0.58 if obj.name.startswith(("EyeBall","Iris")) else 0.48
        obj.scale *= factor

# Pull face features closer to the front surface and reduce toy-like projection.
for obj in collection.objects:
    if obj.name.startswith(("EyeBall","Iris","UpperLid","Brow","Nose","UpperLip","LowerLip")):
        obj.location.y += 0.004

# Use darker guide materials so surface placement remains readable over the texture.
for name in ("Detail_Skin","Detail_Lip","Detail_Leather","Detail_Blue","Detail_Metal","Detail_EyeWhite","Detail_Iris"):
    mat=bpy.data.materials.get(name)
    if mat:
        mat.diffuse_color=(0.055,0.035,0.025,1)
        mat.roughness=.62
        mat.metallic=0

collection["stage"]="face-and-garment-sculpt-guides-v2"
collection["limitations"]="Position guides only; convert/shrinkwrap or sculpt into a high mesh before baking."
bpy.ops.wm.save_as_mainfile(filepath=r"C:\Users\vip\Documents\3d\field-commander\field-commander-sf3d-detailed.blend")
print("DETAIL_GUIDES_REFINED")
