import trimesh


mesh = trimesh.load("public/models/yoyo-hunyuan-shape-v1.glb", force="mesh")
parts = mesh.split(only_watertight=False)
print("mesh", len(mesh.vertices), len(mesh.faces), "components", len(parts))
rows = []
for index, part in enumerate(parts):
    bounds = part.bounds
    dims = bounds[1] - bounds[0]
    center = bounds.mean(axis=0)
    rows.append((len(part.faces), index, *center, *dims))
for row in sorted(rows, reverse=True)[:60]:
    print("%6d id=%3d c=(% .3f,% .3f,% .3f) d=(%.3f,%.3f,%.3f)" % row)
