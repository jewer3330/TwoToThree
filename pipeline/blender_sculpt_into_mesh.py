import bpy
import math
import os

BLEND=r"C:\Users\vip\Documents\3d\field-commander\field-commander-sf3d-sculpted.blend"
source=bpy.data.objects.get("Field_Commander_SF3D")
if not source: raise RuntimeError("Source mesh missing")

old=bpy.data.objects.get("Field_Commander_Sculpted")
if old: bpy.data.objects.remove(old,do_unlink=True)

sculpt=source.copy();sculpt.data=source.data.copy();sculpt.name="Field_Commander_Sculpted"
bpy.context.scene.collection.objects.link(sculpt)
bpy.context.view_layer.objects.active=sculpt;sculpt.select_set(True);source.select_set(False)

# Build enough continuous topology for actual vertex sculpting.
sub=sculpt.modifiers.new("Sculpt_Subdivision","SUBSURF");sub.subdivision_type='SIMPLE';sub.levels=2;sub.render_levels=2
bpy.ops.object.modifier_apply(modifier=sub.name)

def g2(x,z,cx,cz,sx,sz):
    return math.exp(-0.5*(((x-cx)/sx)**2+((z-cz)/sz)**2))

def seg_dist(x,z,x1,z1,x2,z2):
    dx=x2-x1;dz=z2-z1;den=dx*dx+dz*dz
    if den==0:return math.hypot(x-x1,z-z1)
    t=max(0,min(1,((x-x1)*dx+(z-z1)*dz)/den))
    return math.hypot(x-(x1+t*dx),z-(z1+t*dz))

for v in sculpt.data.vertices:
    x,y,z=v.co
    if y < 0: continue
    disp=0.0
    # Eye sockets inset; upper/lower lids add restrained relief.
    for side in (-1,1):
        cx=side*.027
        disp-=.0042*g2(x,z,cx,.395,.020,.013)
        disp+=.0030*g2(x,z,cx,.402,.020,.0045)
        disp+=.0017*g2(x,z,cx,.388,.018,.0045)
        disp+=.0018*g2(x,z,cx,.421,.025,.004)
    # Nose bridge, tip and wings.
    disp+=.0040*g2(x,z,0,.398,.008,.025)
    disp+=.0085*g2(x,z,0,.377,.012,.012)
    disp+=.0028*g2(x,z,-.010,.372,.009,.006)
    disp+=.0028*g2(x,z,.010,.372,.009,.006)
    # Philtrum and lips; mouth crease is inset between lip volumes.
    disp+=.0025*g2(x,z,0,.360,.019,.004)
    disp-=.0018*g2(x,z,0,.356,.022,.0025)
    disp+=.0022*g2(x,z,0,.351,.018,.004)
    # Subtle chin volume.
    disp+=.0020*g2(x,z,0,.335,.025,.012)

    # Square neckline raised piping following a polyline.
    neckline=[(-.105,.292),(-.086,.255),(0,.244),(.086,.255),(.105,.292)]
    d=min(seg_dist(x,z,*a,*b) for a,b in zip(neckline,neckline[1:]))
    disp+=.0027*math.exp(-0.5*(d/.0035)**2)

    # Corset vertical boning sculpted into the cloth shell.
    for bx in (-.085,-.060,-.035,.035,.060,.085):
        top=(bx,.238);bottom=(bx*.82,.095)
        d=seg_dist(x,z,*top,*bottom)
        disp+=.0021*math.exp(-0.5*(d/.0027)**2)

    # Cross lacing and eyelet dimples.
    for i,lz in enumerate((.225,.204,.183,.162,.141,.120)):
        d=seg_dist(x,z,-.019,lz,.019,lz-.010)
        disp+=.0018*math.exp(-0.5*(d/.0022)**2)
        for side in (-1,1):
            disp-=.0010*g2(x,z,side*.019,lz,.0034,.0034)

    # Collar fastener relief.
    for bz in (.326,.315,.304):
        disp+=.0019*g2(x,z,0,bz,.004,.004)

    # Only move the actual front shell; fade displacement near side-facing normals.
    weight=max(0.0,min(1.0,v.normal.y*2.0))
    v.co.y += disp*weight

sculpt.data.update()
for p in sculpt.data.polygons:p.use_smooth=True

# Preserve source and guides, but remove them from working/render visibility.
source.hide_viewport=True;source.hide_render=True
details=bpy.data.collections.get("DETAIL_GEOMETRY")
if details:
    details.hide_viewport=True;details.hide_render=True

sculpt["sculpt_stage"]="embedded-face-and-corset-v1"
sculpt["source_backup"]="Field_Commander_SF3D"
sculpt["limitations"]="Vertex-field sculpt from front reference; side/back facial anatomy still requires manual brush review."
bpy.context.view_layer.objects.active=sculpt
sculpt.select_set(True)
bpy.ops.wm.save_as_mainfile(filepath=BLEND)
print({"vertices":len(sculpt.data.vertices),"polygons":len(sculpt.data.polygons),"saved":BLEND})
