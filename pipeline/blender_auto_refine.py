# -*- coding: utf-8 -*-
"""Blender V1 automatic GLB refinement with honest quality gates."""
import argparse,json,math,sys
from pathlib import Path
import bpy,bmesh
from mathutils import Vector

VIEWS={'front':(0,-8,2.3),'left-three-quarter':(-5.6,-5.6,2.7),'side':(-8,0,2.3),'back':(0,8,2.3)}
def cli():
    raw=sys.argv[sys.argv.index('--')+1:];p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--reference-image',type=Path);return p.parse_args(raw)
def say(stage,message):print('REFINE_EVENT='+json.dumps({'stage':stage,'message':message},ensure_ascii=False),flush=True)
def percentile(values,q):
    values=sorted(values);p=(len(values)-1)*q;lo=int(math.floor(p));hi=int(math.ceil(p));return values[lo] if lo==hi else values[lo]*(hi-p)+values[hi]*(p-lo)
def stats(meshes):
    points=[o.matrix_world@v.co for o in meshes for v in o.data.vertices];lo=[min(p[i] for p in points) for i in range(3)];hi=[max(p[i] for p in points) for i in range(3)];robust_lo=[percentile([p[i] for p in points],.05) for i in range(3)];robust_hi=[percentile([p[i] for p in points],.95) for i in range(3)];robust=[robust_hi[i]-robust_lo[i] for i in range(3)];central=[p for p in points if robust_lo[0]<=p.x<=robust_hi[0] and robust_lo[2]<=p.z<=robust_hi[2]];central_depth=percentile([p.y for p in central],.95)-percentile([p.y for p in central],.05) if central else robust[1]
    return {'objects':len(meshes),'vertices':sum(len(o.data.vertices) for o in meshes),'polygons':sum(len(o.data.polygons) for o in meshes),'triangles':sum(len(p.loop_indices)-2 for o in meshes for p in o.data.polygons),'bounds':[hi[i]-lo[i] for i in range(3)],'bboxVolume':math.prod(max(hi[i]-lo[i],1e-9) for i in range(3)),'robustDimensions':robust,'robustDepth':robust[1],'centralDepth':central_depth,'thinAxisRatio':robust[1]/max(robust[0],robust[2],1e-9),'sideSilhouetteArea':robust[1]*robust[2]}
def active(o):bpy.ops.object.select_all(action='DESELECT');o.select_set(True);bpy.context.view_layer.objects.active=o
def volume_safe(candidate,baseline,cfg):
    if not cfg.get('preserveThickness',True):return True
    keep=1-float(cfg.get('maxThicknessLoss',.08));return candidate['robustDepth']>=baseline['robustDepth']*keep and candidate['centralDepth']>=baseline['centralDepth']*keep and candidate['sideSilhouetteArea']>=baseline['sideSilhouetteArea']*keep and candidate['thinAxisRatio']>=min(float(cfg.get('minThinAxisRatio',.08)),baseline['thinAxisRatio']*keep)
def restore_meshes(meshes,backups):
    for o,data in zip(meshes,backups):old=o.data;o.data=data;bpy.data.meshes.remove(old)
def main():
    a=cli();cfg=json.loads(a.config.read_text(encoding='utf-8'));a.output_dir.mkdir(parents=True,exist_ok=True)
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False);bpy.ops.import_scene.gltf(filepath=str(a.input));meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    if not meshes:raise RuntimeError('输入 GLB 不包含网格')
    before=stats(meshes);say('geometryRepair','读取源模型并采集处理前统计')
    for o in meshes:
        active(o);bpy.ops.object.transform_apply(location=False,rotation=True,scale=True);bm=bmesh.new();bm.from_mesh(o.data);bmesh.ops.remove_doubles(bm,verts=bm.verts,dist=0.00001);loose=[v for v in bm.verts if not v.link_edges];bmesh.ops.delete(bm,geom=loose,context='VERTS');deg=[f for f in bm.faces if f.calc_area()<1e-12];bmesh.ops.delete(bm,geom=deg,context='FACES');bmesh.ops.recalc_face_normals(bm,faces=bm.faces);bm.to_mesh(o.data);bm.free();o.data.update()
    after_cleanup=stats(meshes);say('geometryRepair','完成变换、重复点、松散几何、退化面和法线清理')
    target=cfg.get('targetTriangleRange',[0,10**9]);max_triangles=int(target[1])
    optimization={'passes':[],'rolledBack':False,'reason':None}
    if after_cleanup['triangles']>max_triangles and max_triangles>0:
        max_drop=float(cfg.get('maxDecimationPerPass',.2))
        for pass_no in range(1,13):
            current=stats(meshes)
            if current['triangles']<=max_triangles:break
            ratio=max(1-max_drop,min(1.0,max_triangles/current['triangles']*.98));backups=[o.data.copy() for o in meshes]
            for o in meshes:
                active(o);modifier=o.modifiers.new(f'AutoRefine_Web_Decimate_{pass_no}','DECIMATE');modifier.decimate_type='COLLAPSE';modifier.ratio=ratio;modifier.use_collapse_triangulate=True;bpy.ops.object.modifier_apply(modifier=modifier.name);o.data.validate(clean_customdata=True);bm=bmesh.new();bm.from_mesh(o.data);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);bm.to_mesh(o.data);bm.free();o.data.update()
            candidate=stats(meshes);safe=volume_safe(candidate,after_cleanup,cfg);optimization['passes'].append({'pass':pass_no,'ratio':ratio,'triangles':candidate['triangles'],'volumeSafe':safe,'robustDepth':candidate['robustDepth'],'centralDepth':candidate['centralDepth']})
            if not safe:
                restore_meshes(meshes,backups);optimization['rolledBack']=True;optimization['reason']='厚度或侧面轮廓超过允许损失，已回滚本轮并停止减面';say('webOptimization',optimization['reason']);break
            for data in backups:bpy.data.meshes.remove(data)
            say('webOptimization',f'分步减面第 {pass_no} 轮：{current["triangles"]} → {candidate["triangles"]}，厚度门禁通过')
    uv_source='preserved';uv_ok=True
    for o in meshes:
        if not o.data.uv_layers or not o.data.uv_layers.active or len(o.data.uv_layers.active.data)==0:
            uv_source='smart_project';active(o);bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT');bpy.ops.uv.smart_project(angle_limit=math.radians(66),island_margin=float(cfg.get('uvIslandMargin',0.03)));bpy.ops.object.mode_set(mode='OBJECT')
        layer=o.data.uv_layers.active
        uv_ok=uv_ok and bool(layer) and all(-1e-5<=x<=1.00001 for d in layer.data for x in d.uv)
    say('uvUnwrap',f'UV 策略完成：{uv_source}')
    texture_mode=str(cfg.get('textureMode','preserve_source'))
    calibration=cfg.get('projectionCalibration')
    projection_allowed=texture_mode=='calibrated_projection' and bool(calibration) and bool(a.reference_image and a.reference_image.exists())
    if texture_mode=='calibrated_projection' and not projection_allowed:
        raise RuntimeError('请求参考图投射但缺少 projectionCalibration；拒绝生成错位贴图')
    neutral_count=0
    for o in meshes:
        # P4-A：已有材质和纹理永远保留。只有真正无材质的网格补中性材质。
        if not any(slot.material for slot in o.material_slots):
            mat=bpy.data.materials.new('AutoRefine_Neutral');mat.use_nodes=True
            bsdf=mat.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Base Color'].default_value=(.5,.5,.5,1);bsdf.inputs['Roughness'].default_value=.65
            o.data.materials.append(mat);neutral_count+=1
    if projection_allowed:
        # 标定投射在 P4-C 独立实现；P4-A 只建立 fail-closed 门禁，禁止伪投射。
        raise RuntimeError('calibrated_projection 尚未实现 P4-C 相机求解；当前版本拒绝执行')
    say('pbrMaterials',f'保留源材质；仅为 {neutral_count} 个无材质网格补中性材质。参考图只用于视觉验收，未连接 Base Color')
    refined=a.output_dir/'refined.glb';bpy.ops.object.select_all(action='DESELECT');[o.select_set(True) for o in meshes];bpy.ops.export_scene.gltf(filepath=str(refined),export_format='GLB',use_selection=True,export_apply=True,export_yup=True,export_materials='EXPORT')
    scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=512;scene.render.resolution_y=512;scene.render.resolution_percentage=100;scene.world.color=(.02,.025,.035);bpy.ops.object.light_add(type='AREA',location=(4,-4,7));bpy.context.object.data.energy=1100;bpy.context.object.data.size=5;bpy.ops.object.camera_add();cam=bpy.context.object;scene.camera=cam;camera_target=Vector((0,0,2))
    for name,pos in VIEWS.items():cam.location=pos;cam.rotation_euler=(camera_target-cam.location).to_track_quat('-Z','Y').to_euler();scene.render.filepath=str(a.output_dir/f'{name}.png');bpy.ops.render.render(write_still=True)
    final=stats(meshes);size_mb=refined.stat().st_size/1048576;bounds_change=max(abs(final['bounds'][i]-before['bounds'][i])/max(before['bounds'][i],1e-9) for i in range(3));safe=volume_safe(final,after_cleanup,cfg);gates={'glbValid':refined.exists() and refined.stat().st_size>12,'meshValid':final['triangles']>0,'triangleBudget':target[0]<=final['triangles']<=target[1],'uvValid':uv_ok,'materialSafe':all(any(slot.material for slot in o.material_slots) for o in meshes),'sizeBudget':size_mb<=cfg.get('maxWebGlbMB',20),'boundsSafe':bounds_change<=.15,'volumeSafe':safe,'robustThicknessSafe':safe,'sideSilhouetteSafe':safe,'rendersComplete':all((a.output_dir/f'{n}.png').exists() for n in VIEWS)}
    report={'schemaVersion':3,'status':'passed' if all(gates.values()) else 'failed','blenderVersion':bpy.app.version_string,'source':str(a.input),'output':str(refined),'before':before,'afterCleanup':after_cleanup,'after':final,'optimization':optimization,'thickness':{'before':after_cleanup['robustDepth'],'after':final['robustDepth'],'retention':final['robustDepth']/max(after_cleanup['robustDepth'],1e-9),'centralRetention':final['centralDepth']/max(after_cleanup['centralDepth'],1e-9),'sideSilhouetteRetention':final['sideSilhouetteArea']/max(after_cleanup['sideSilhouetteArea'],1e-9)},'uv':{'source':uv_source,'valid':uv_ok},'materials':{'mode':'preserve_source','sourceMaterialsPreserved':True,'neutralMaterialsAdded':neutral_count,'baseColorSource':'source_material','referenceProjectionApplied':False,'note':'参考图仅用于视觉验收'},'gates':gates,'fileSizeMB':round(size_mb,3),'config':cfg}
    (a.output_dir/'quality-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');say('qualityGate',f'质量门禁：{report["status"]}')
if __name__=='__main__':main()
