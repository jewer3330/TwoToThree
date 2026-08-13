import bpy
from mathutils import Vector

obj = bpy.data.objects.get("Field_Commander_SF3D")
corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
mins = [min(v[i] for v in corners) for i in range(3)]
maxs = [max(v[i] for v in corners) for i in range(3)]
print({
    "name": obj.name,
    "vertices": len(obj.data.vertices),
    "polygons": len(obj.data.polygons),
    "min": mins,
    "max": maxs,
    "dimensions": [maxs[i] - mins[i] for i in range(3)],
    "materials": [slot.material.name if slot.material else None for slot in obj.material_slots],
})
