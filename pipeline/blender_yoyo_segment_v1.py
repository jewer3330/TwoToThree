import json, math, os
from collections import Counter

import bpy
from mathutils import Vector

ROOT=r"C:\Users\vip\Documents\3d"
SOURCE=os.path.join(ROOT,"yoyo-blender","yoyo-front-projection-v1.blend")
OUT=os.path.join(ROOT,"yoyo-blender","segment-v1")
BLEND=os.path.join(ROOT,"yoyo-blender","yoyo-segment-v1.blend")
GLB=os.path.join(ROOT,"public","models","yoyo-segment-v1.glb")
REFERENCE=os.path.join(ROOT,"public","yoyo-reference.png")
os.makedirs(OUT,exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=SOURCE)
src=bpy.data.objects.get('YOYO_SCULPT_WORK')
if not src:raise RuntimeError('Projected YOYO source missing')
src.name='YOYO_PROJECTED_LOCKED';src.hide_render=True;src.hide_set(True);src.hide_select=True

img=bpy.data.images.load(REFERENCE,check_existing=True)
if not img.has_data:img.reload()
w,h=img.size;pixels=list(img.pixels)
uv=src.data.uv_layers.get('YOYO_FRONT_PROJECTION')
if not uv:raise RuntimeError('YOYO_FRONT_PROJECTION UV missing')

pts=[src.matrix_world@Vector(c) for c in src.bound_box]
lo=Vector(tuple(min(p[i] for p in pts) for i in range(3)));hi=Vector(tuple(max(p[i] for p in pts) for i in range(3)));size=hi-lo

# De-lit-ish reference palette anchors sampled/estimated from the authoritative design.
palette={
 'Head':(0.94,.69,.63),'Hood':(.075,.11,.29),'Cap':(.06,.39,.50),
 'Coat':(.82,.76,.64),'Boots':(.91,.52,.08),'Satchel':(.29,.10,.035),
 'Eyes':(.015,.015,.018),'Gold_Details':(.94,.55,.09)
}
def color_distance(a,b):
    # Slightly favor hue/chroma agreement over lighting value.
    return sum((a[i]-b[i])**2*(1.0 if i else .85) for i in range(3))
def sample_poly(poly):
    us=[];vs=[]
    for li in poly.loop_indices:
        u,v=uv.data[li].uv;us.append(u%1);vs.append(v%1)
    u=sum(us)/len(us);v=sum(vs)/len(vs)
    x=max(0,min(w-1,int(u*(w-1))));y=max(0,min(h-1,int(v*(h-1))))
    i=(y*w+x)*4
    return tuple(pixels[i:i+3])

labels=[]
normal_matrix=src.matrix_world.to_3x3()
for poly in src.data.polygons:
    p=src.matrix_world@poly.center;n=(normal_matrix@poly.normal).normalized()
    q=(p.z-lo.z)/size.z;xn=(p.x-(lo.x+hi.x)*.5)/(size.x*.5);yn=(p.y-(lo.y+hi.y)*.5)/(size.y*.5)
    c=sample_poly(poly)
    label=min(palette,key=lambda k:color_distance(c,palette[k]))
    # Structural overrides only where the single front image cannot provide evidence.
    if n.y<-.12:
        if q>.82:label='Cap'
        elif q>.50:label='Hood'
        elif q>.27:label='Coat'
        elif q>.06:label='Boots' if q<.22 else 'Head'
    # Merge tiny identity materials into their parent for first-round large parts.
    if label=='Eyes':label='Head'
    if label=='Gold_Details':
        label='Cap' if q>.83 else ('Boots' if q<.25 else 'Coat')
    # Named large-part routing.
    if label=='Head': part='Head'
    elif label=='Hood': part='Hood' if q>.61 else 'Cape'
    elif label=='Cap': part='Cap_Tail'
    elif label=='Satchel': part='Satchel'
    elif label=='Boots': part=('Leg_Boot_L' if xn<0 else 'Leg_Boot_R')
    elif label=='Coat':
        if .29<q<.53 and abs(xn)>.56:part=('Arm_L' if xn<0 else 'Arm_R')
        else:part='Body_Coat'
    else:part='Body_Coat'
    labels.append(part)

# Remove isolated misclassified islands using mesh adjacency majority voting.
edge_faces={}
for poly in src.data.polygons:
    for key in poly.edge_keys:edge_faces.setdefault(key,[]).append(poly.index)
neighbors=[set() for _ in src.data.polygons]
for faces in edge_faces.values():
    for a in faces:
        neighbors[a].update(f for f in faces if f!=a)
for _ in range(4):
    new=labels[:]
    for i,ns in enumerate(neighbors):
        if not ns:continue
        votes=Counter(labels[j] for j in ns)
        winner,count=votes.most_common(1)[0]
        if count>=max(3,math.ceil(len(ns)*.72)):new[i]=winner
    labels=new

seg=bpy.data.collections.get('YOYO_SEGMENTS') or bpy.data.collections.new('YOYO_SEGMENTS');bpy.context.scene.collection.children.link(seg)
materials={}
colors={'Head':(.94,.66,.59,1),'Hood':(.055,.08,.25,1),'Cape':(.065,.09,.28,1),'Cap_Tail':(.035,.38,.50,1),'Body_Coat':(.82,.76,.63,1),'Arm_L':(.80,.74,.62,1),'Arm_R':(.80,.74,.62,1),'Leg_Boot_L':(.91,.51,.07,1),'Leg_Boot_R':(.91,.51,.07,1),'Satchel':(.27,.075,.025,1)}
def make_mat(name):
    m=bpy.data.materials.new('SEG_'+name);m.diffuse_color=colors[name];m.use_nodes=True;b=m.node_tree.nodes.get('Principled BSDF');b.inputs['Base Color'].default_value=colors[name];b.inputs['Roughness'].default_value=.58;return m
for name in colors:materials[name]=make_mat(name)

def extract(name,face_ids):
    used=set();faces=[]
    for fi in face_ids:
        poly=src.data.polygons[fi];face=[]
        for vi in poly.vertices:used.add(vi);face.append(vi)
        faces.append(face)
    mapping={old:i for i,old in enumerate(sorted(used))}
    verts=[src.data.vertices[i].co.copy() for i in sorted(used)]
    remapped=[[mapping[i] for i in f] for f in faces]
    mesh=bpy.data.meshes.new(name+'_Mesh');mesh.from_pydata(verts,[],remapped);mesh.materials.append(materials[name]);mesh.update()
    obj=bpy.data.objects.new(name,mesh);seg.objects.link(obj);obj.matrix_world=src.matrix_world.copy();obj['segment_id']=name;obj['source']='YOYO_PROJECTED_LOCKED';obj['boundary_status']='automatic-reference-projection-v1; requires visual approval'
    for p in mesh.polygons:p.use_smooth=True
    return obj

groups={name:[] for name in colors}
for i,label in enumerate(labels):groups[label].append(i)
objects=[extract(name,ids) for name,ids in groups.items() if ids]
home_positions={o.name:o.location.copy() for o in objects}

# Review render: assembled and restrained exploded view.
scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=720;scene.render.resolution_y=960;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
cam=bpy.data.objects.get('YOYO_REFERENCE_CAMERA');scene.camera=cam;target=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z+size.z*.51));cam.data.ortho_scale=size.z*1.12
def render(name,direction,explode=False):
    for o in objects:
        o.location=home_positions[o.name]
        if explode:
            c=Vector((0,0,0))
            for v in o.bound_box:c+=o.matrix_world@Vector(v)
            c/=8;delta=(c-target)
            if delta.length:delta.normalize()
            o.location=home_positions[o.name]+delta*.035
    cam.location=target+Vector(direction).normalized()*max(size)*3;cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();scene.render.filepath=os.path.join(OUT,name+'.png');bpy.ops.render.render(write_still=True)
render('assembled-front',(0,1,.03));render('assembled-three-quarter',(.55,1,.08));render('exploded-front',(0,1,.03),True);render('exploded-three-quarter',(.55,1,.08),True)
for o in objects:o.location=home_positions[o.name]
bpy.ops.wm.save_as_mainfile(filepath=BLEND)
bpy.ops.object.select_all(action='DESELECT')
for o in objects:o.select_set(True)
bpy.context.view_layer.objects.active=objects[0]
bpy.ops.export_scene.gltf(filepath=GLB,export_format='GLB',use_selection=True,export_apply=True,export_yup=True)
report={'blend':BLEND,'glb':GLB,'source':SOURCE,'geometry_source_unchanged':True,'segments':{k:len(v) for k,v in groups.items()},'objects':[o.name for o in objects],'pass':'automatic-reference-segmentation-v1','decision':'refine-code','still_missing':'Boundary cleanup at hood/face, cape/coat, sleeves/hands, cap/star/pom; eye and accessory subparts intentionally deferred.'}
with open(os.path.join(OUT,'report.json'),'w',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
print(json.dumps(report,ensure_ascii=False))
