import json, math, os
import bpy
from mathutils import Vector

ROOT=r"C:\Users\vip\Documents\3d"
OUT=os.path.join(ROOT,"yoyo-blender","modular-v1")
BLEND=os.path.join(ROOT,"yoyo-blender","yoyo-modular-v1.blend")
GLB=os.path.join(ROOT,"public","models","yoyo-modular-v1.glb")
os.makedirs(OUT,exist_ok=True)
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
for c in list(bpy.data.collections):
    if c.name != 'Collection': bpy.data.collections.remove(c)
parts=bpy.data.collections.new('YOYO_MODULAR_PARTS');bpy.context.scene.collection.children.link(parts)

def material(name,color,rough=.65):
    m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.roughness=rough;return m
M={
 'clay':material('Clay',(0.48,.52,.58)), 'skin':material('Skin',(.92,.62,.55),.5),
 'dark':material('Cape',(.055,.09,.28),.7), 'teal':material('Cap',(.03,.38,.52),.55),
 'cream':material('Coat',(.82,.76,.62),.72), 'gold':material('Gold',(.92,.49,.06),.35),
 'brown':material('Leather',(.25,.075,.025),.58), 'black':material('Eye',(.005,.006,.009),.12)
}
def own(o,name,mat):
    o.name=name
    for c in list(o.users_collection):c.objects.unlink(o)
    parts.objects.link(o);o.data.materials.append(mat)
    if o.type=='MESH':
        for p in o.data.polygons:p.use_smooth=True
    o['part_id']=name;o['explodable']=True;return o
def sphere(name,p,s,mat=M['clay'],seg=48,rings=32):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg,ring_count=rings,location=p);o=own(bpy.context.object,name,mat);o.scale=s;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);return o
def cube(name,p,s,mat,bev=.03):
    bpy.ops.mesh.primitive_cube_add(location=p);o=own(bpy.context.object,name,mat);o.scale=s;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);b=o.modifiers.new('Soft edges','BEVEL');b.width=bev;b.segments=4;return o
def curve(name,pts,r,mat,cyclic=False):
    d=bpy.data.curves.new(name+'_curve','CURVE');d.dimensions='3D';d.bevel_depth=r;d.bevel_resolution=4
    s=d.splines.new('BEZIER');s.bezier_points.add(len(pts)-1)
    for b,p in zip(s.bezier_points,pts):b.co=p;b.handle_left_type=b.handle_right_type='AUTO'
    s.use_cyclic_u=cyclic;o=bpy.data.objects.new(name,d);parts.objects.link(o);o.data.materials.append(mat);o['part_id']=name;o['explodable']=True;return o
def cone(name,p,r1,r2,depth,mat,rot=(0,0,0)):
    bpy.ops.mesh.primitive_cone_add(vertices=48,radius1=r1,radius2=r2,depth=depth,location=p,rotation=rot);return own(bpy.context.object,name,mat)

# Feet and legs (ground at z=0).
for side in (-1,1):
    tag='L' if side<0 else 'R'
    sphere(f'{tag}_Leg',(side*.18,0,.52),(.115,.12,.30),M['skin'])
    sphere(f'{tag}_Boot',(side*.19,.035,.25),(.205,.26,.20),M['gold'])
    sphere(f'{tag}_Sole',(side*.19,.055,.095),(.215,.275,.065),M['brown'])
    curve(f'{tag}_Boot_Cuff',[(side*.30,-.02,.43),(side*.19,.11,.47),(side*.08,-.02,.43)],.035,M['gold'])

# A-line coat: lathed convex profile, distinct from cape and limbs.
prof=[(.57,-.72),(.62,-.62),(.58,-.32),(.50,.05),(.43,.35),(.38,.55)]
bpy.ops.mesh.primitive_grid_add(x_subdivisions=2,y_subdivisions=2) # disposable context stabilizer
bpy.data.objects.remove(bpy.context.object,do_unlink=True)
verts=[Vector((r,z)) for r,z in prof]
g=bpy.data.curves.new('CoatProfile','CURVE');g.dimensions='2D';sp=g.splines.new('POLY');sp.points.add(len(verts)-1)
for pt,v in zip(sp.points,verts):pt.co=(v.x,v.y,0,1)
# Native lathe gives a clean closed shell.
mesh=bpy.data.meshes.new('CoatMesh');coat=bpy.data.objects.new('Coat',mesh);parts.objects.link(coat)
vs=[];fs=[];N=64
for i in range(N):
    a=2*math.pi*i/N
    for r,z in prof:vs.append((r*math.cos(a),r*.72*math.sin(a),z+1.33))
P=len(prof)
for i in range(N):
    ni=(i+1)%N
    for j in range(P-1):fs.append((i*P+j,ni*P+j,ni*P+j+1,i*P+j+1))
mesh.from_pydata(vs,[],fs);mesh.materials.append(M['cream']);coat['part_id']='Coat';coat['explodable']=True

# Arms, palms, simple separated fingers.
for side in (-1,1):
    tag='L' if side<0 else 'R'
    arm=cone(f'{tag}_Sleeve',(side*.49,.0,1.42),.18,.13,.58,M['cream'],rot=(0,side*.14,side*.16))
    palm=sphere(f'{tag}_Palm',(side*.65,.08,1.19),(.13,.12,.12),M['skin'])
    for i in range(4):
        sphere(f'{tag}_Finger_{i+1}',(side*(.69+i*.025),.14,1.14-i*.006),(.025,.052,.045),M['skin'],24,16)

# Head and facial details. Front is -Y to match the review camera convention below.
head=sphere('Mantou_Head',(0,-.01,2.32),(.72,.54,.54),M['skin'],64,48)
for side in (-1,1):
    sphere(('L' if side<0 else 'R')+'_Ear',(side*.68,-.01,2.25),(.14,.12,.16),M['skin'])
    sphere(('L' if side<0 else 'R')+'_Eye',(side*.23,-.515,2.36),(.075,.035,.145),M['black'])
    for j,dx in enumerate((-.055,0,.055),1):sphere(f'{"L" if side<0 else "R"}_Freckle_{j}',(side*.36+dx,-.527,2.20),(.016,.009,.016),M['gold'],20,12)

# Hood rim and shoulder cape as separate thick volumes.
curve('Hood_Rim',[(-.64,-.31,2.56),(-.71,-.45,2.30),(-.60,-.47,2.02),(0,-.49,1.92),(.60,-.47,2.02),(.71,-.45,2.30),(.64,-.31,2.56)],.085,M['dark'])
sphere('Rear_Hood',(0,.20,2.37),(.77,.52,.66),M['dark'])
capePts=[(-.64,-.15,1.90),(-.72,-.28,1.72),(-.48,-.37,1.57),(0,-.40,1.50),(.48,-.37,1.57),(.72,-.28,1.72),(.64,-.15,1.90)]
curve('Cape_Front_Edge',capePts,.11,M['dark'])
sphere('Cape_Shoulder',(0,.08,1.72),(.76,.45,.31),M['dark'])

# Cap dome, bent tail, pom and star.
sphere('Teal_Cap',(0,.02,2.79),(.60,.47,.28),M['teal'])
curve('Cap_Tail',[(.15,.06,2.94),(.43,.08,2.98),(.58,.08,2.78),(.58,.06,2.56)],.13,M['teal'])
sphere('Cap_Pom',(.58,.05,2.50),(.15,.14,.15),M['cream'])
star=[]
for i in range(10):
    a=i*math.pi/5-math.pi/2;r=.19 if i%2==0 else .085;star.append((math.cos(a)*r,-.49,3.10+math.sin(a)*r))
curve('Star_Finial',star,.045,M['gold'],True)

# Clasp, strap and satchel.
cres=[]
for i in range(17):
    a=math.radians(55+i*250/16);cres.append((math.cos(a)*.095,-.51,1.86+math.sin(a)*.095))
curve('Crescent_Clasp',cres,.025,M['gold'])
curve('Satchel_Strap',[(-.06,-.48,1.83),(.08,-.50,1.55),(.30,-.48,1.20),(.48,-.39,.92)],.025,M['brown'])
cube('Satchel_Body',(.52,-.35,.94),(.22,.10,.20),M['brown'],.07)
cube('Satchel_Flap',(.52,-.47,1.06),(.23,.045,.09),M['brown'],.05)
sphere('Satchel_Stud',(.52,-.525,1.02),(.035,.018,.035),M['gold'],24,16)

# Scene and four-view render.
scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=720;scene.render.resolution_y=960;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG';scene.world.color=(.025,.028,.035)
bpy.ops.mesh.primitive_plane_add(size=8,location=(0,0,.02));floor=bpy.context.object;floor.name='REVIEW_FLOOR';floor.data.materials.append(material('Floor',(.17,.16,.15),.9))
for name,loc,energy,size in [('Key',(4,-5,6),1000,4),('Fill',(-4,-3,4),650,5),('Rim',(0,4,5),850,4)]:
    d=bpy.data.lights.new(name,'AREA');d.energy=energy;d.shape='DISK';d.size=size;o=bpy.data.objects.new(name,d);scene.collection.objects.link(o);o.location=loc;o.rotation_euler=((Vector((0,0,1.6))-o.location).to_track_quat('-Z','Y').to_euler())
cd=bpy.data.cameras.new('Review_Camera');cam=bpy.data.objects.new('Review_Camera',cd);scene.collection.objects.link(cam);scene.camera=cam;cd.type='ORTHO';cd.ortho_scale=3.65;target=Vector((0,0,1.58))
views={'front':(0,-1,.05),'three-quarter':(.72,-1,.10),'side':(1,0,.05),'back':(0,1,.05)}
for name,d in views.items():cam.location=target+Vector(d).normalized()*7;cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();scene.render.filepath=os.path.join(OUT,f'yoyo-modular-{name}.png');bpy.ops.render.render(write_still=True)

bpy.ops.wm.save_as_mainfile(filepath=BLEND)
bpy.ops.object.select_all(action='DESELECT')
for o in parts.objects:o.select_set(True)
bpy.context.view_layer.objects.active=head
bpy.ops.export_scene.gltf(filepath=GLB,export_format='GLB',use_selection=True,export_apply=True,export_yup=True)
report={'blend':BLEND,'glb':GLB,'parts':len(parts.objects),'part_names':sorted(o.name for o in parts.objects),'pass':'modular-blockout-v1','decision':'refine-code','still_missing':'Cape lower drape, exact hand pose, coat collar/hem, back folds, texture projection and final proportions.'}
with open(os.path.join(OUT,'report.json'),'w',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
print(json.dumps(report,ensure_ascii=False))
