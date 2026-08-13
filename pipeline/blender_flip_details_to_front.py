import bpy

details=bpy.data.collections.get("DETAIL_GEOMETRY")
if not details:
    raise RuntimeError("DETAIL_GEOMETRY collection not found")

for obj in details.objects:
    # Mesh details store placement in object transforms.
    obj.location.y *= -1
    # Curve guides store their coordinates directly in spline data.
    if obj.type == "CURVE":
        for spline in obj.data.splines:
            for point in spline.bezier_points:
                point.co.y *= -1
                point.handle_left.y *= -1
                point.handle_right.y *= -1
            for point in spline.points:
                point.co.y *= -1

details["front_axis"]="+Y"
details["correction"]="Mirrored all detail geometry from -Y back side to +Y front side."
bpy.ops.wm.save_as_mainfile(filepath=r"C:\Users\vip\Documents\3d\field-commander\field-commander-sf3d-detailed.blend")
print({"flipped_objects":len(details.objects),"front_axis":"+Y"})
