"""Deterministic RGB visual cues for Hunyuan3D multiview conditioning.

The model has no declared depth/normal input.  Every selectable candidate therefore
remains an RGBA character image; the grayscale depth cue is diagnostic only.
"""
from __future__ import annotations
import json, math
from pathlib import Path
from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps

SELECTABLE_MODES={"original","contour","rgb_depth"}

def _metrics(image:Image.Image)->dict:
    alpha=image.getchannel("A");bbox=alpha.point(lambda v:255 if v>8 else 0).getbbox()
    if not bbox:raise ValueError("视觉增强输入没有有效前景")
    left,top,right,bottom=bbox
    return {"bbox":[left,top,right,bottom],"width":right-left,"height":bottom-top,"occupancy":round((right-left)*(bottom-top)/(image.width*image.height),5)}

def _depth_cue(image:Image.Image)->Image.Image:
    """Create a smooth center-thick/edge-thin cue, not a calibrated depth map."""
    alpha=image.getchannel("A");bbox=alpha.getbbox();cue=Image.new("L",image.size,0)
    if not bbox:return cue
    left,top,right,bottom=bbox;px=cue.load();mask=alpha.load();cx=(left+right-1)/2;cy=(top+bottom-1)/2;rx=max((right-left)/2,1);ry=max((bottom-top)/2,1)
    for y in range(top,bottom):
        for x in range(left,right):
            if mask[x,y]<=8:continue
            radial=min(1,math.sqrt(((x-cx)/rx)**2+((y-cy)/ry)**2));px[x,y]=round(72+155*(1-radial))
    return cue.filter(ImageFilter.GaussianBlur(5))

def _contour(image:Image.Image)->Image.Image:
    rgb=image.convert("RGB");gray=ImageOps.grayscale(rgb);edges=ImageOps.invert(gray.filter(ImageFilter.FIND_EDGES));edges=ImageEnhance.Contrast(edges).enhance(1.35);ink=Image.merge("RGB",(edges,edges,edges));out=ImageChops.multiply(rgb,ink);out=Image.blend(rgb,out,.16);out.putalpha(image.getchannel("A"));return out

def _rgb_depth(image:Image.Image,blend:float)->Image.Image:
    blend=max(0,min(.25,float(blend)));rgb=image.convert("RGB");cue=_depth_cue(image);shade=Image.merge("RGB",(cue,cue,cue));out=Image.blend(rgb,shade,blend);out.putalpha(image.getchannel("A"));return out

def build_candidates(images:dict[str,Image.Image],output_dir:Path,mode:str="auto",style:str="realistic",depth_blend:float=.15)->dict:
    output_dir.mkdir(parents=True,exist_ok=True);selected="original" if mode=="auto" and style=="realistic" else "contour" if mode=="auto" else mode
    if selected not in SELECTABLE_MODES:raise ValueError(f"不支持的视觉增强模式：{selected}")
    report={"schemaVersion":1,"selectedMode":selected,"style":style,"depthBlend":depth_blend,"views":{},"warnings":[]};selected_paths={}
    for role,source in images.items():
        source=source.convert("RGBA");original_metrics=_metrics(source);variants={"original":source,"contour":_contour(source),"rgb_depth":_rgb_depth(source,depth_blend)};depth=_depth_cue(source);role_dir=output_dir/role;role_dir.mkdir(exist_ok=True);records={}
        for name,candidate in variants.items():
            path=role_dir/f"{name}.png";candidate.save(path);metrics=_metrics(candidate);safe=metrics["bbox"]==original_metrics["bbox"] and candidate.getchannel("A").tobytes()==source.getchannel("A").tobytes();records[name]={"path":str(path),"selectable":True,"silhouettePreserved":safe,**metrics}
            if name==selected:
                if not safe:raise ValueError(f"{role} 的 {name} 候选改变了轮廓，拒绝送入 Hunyuan")
                selected_paths[role]=path
        depth_path=role_dir/"depth-cue-experimental.png";depth.save(depth_path);records["depthCue"]={"path":str(depth_path),"selectable":False,"reason":"Hunyuan3D-2mv 未声明支持深度条件，仅供实验观察"};report["views"][role]={"source":original_metrics,"candidates":records,"selected":str(selected_paths[role])}
    heights=[report["views"][r]["source"]["height"] for r in images];spread=(max(heights)-min(heights))/max(max(heights),1)
    report["consistency"]={"normalizedHeightSpread":round(spread,4),"passed":spread<=.12}
    if spread>.12:report["warnings"].append("三视图主体高度差超过12%，建议重新对齐；当前预处理通常会自动修正")
    (output_dir/"visual-conditioning-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return {"images":selected_paths,"report":report,"reportPath":output_dir/"visual-conditioning-report.json"}
