"""纯 Python 多色 3MF 生成器（无第三方依赖）。

输入：部件二进制 STL 列表 + 颜色映射 {stl_name: "#RRGGBB"}
输出：多对象多色 3MF（每部件一个 object + basematerials 材质，
      triangles 带 pid 引用材质），可被 OrcaSlicer/Bambu Studio 识别为多色。

二进制 STL 格式：80 字节头 + uint32 三角形数 + 每三角形 12*float32 + 2 字节属性。
"""
from __future__ import annotations
import struct, zipfile
from pathlib import Path
from xml.sax.saxutils import escape

def parse_binary_stl(path:Path)->tuple[list[tuple[float,float,float]],list[tuple[int,int,int]]]:
    data=path.read_bytes()
    if len(data)<84:return [],[]
    count=struct.unpack_from('<I',data,80)[0]
    raw_verts=[];raw_tris=[]
    off=84
    for i in range(count):
        if off+50>len(data):break
        v0=struct.unpack_from('<fff',data,off+12)
        v1=struct.unpack_from('<fff',data,off+24)
        v2=struct.unpack_from('<fff',data,off+36)
        raw_verts.extend([v0,v1,v2]);raw_tris.append((3*i,3*i+1,3*i+2))
        off+=50
    vmap:dict[tuple[float,float,float],int]={};verts:list[tuple[float,float,float]]=[];tris=[]
    for t in raw_tris:
        tri=[]
        for idx in t:
            if idx>=len(raw_verts):break
            v=raw_verts[idx]
            q=(round(v[0],6),round(v[1],6),round(v[2],6))
            if q not in vmap:
                vmap[q]=len(verts);verts.append(q)
            tri.append(vmap[q])
        if len(tri)==3:tris.append(tuple(tri))
    return verts,tris

def build_3mf(parts:list[tuple[Path,str]], colors:dict[str,str], output:Path):
    """parts: [(stl_path, part_name)]；colors: {stl_name: '#RRGGBB'}
    采用 OrcaSlicer/Bambu 兼容格式：m:colorgroup 材质 + object 级 pid 属性。"""
    objects=[];build_items=[];materials=[]
    oid=0;mid=2  # 样例从 2 开始（偶数值），保持兼容
    for stl,name in parts:
        verts,tris=parse_binary_stl(stl)
        if not tris:continue
        obj_id=oid;mat_id=mid
        oid+=1;mid+=2
        hexc=(colors.get(stl.name) or '#9E9E9E').lstrip('#')
        if len(hexc)!=6:hexc='9E9E9E'
        materials.append(f'<m:colorgroup id="{mat_id}"><m:color color="#{hexc}FF"/></m:colorgroup>')
        verts_xml=''.join(f'<vertex x="{v[0]:.6f}" y="{v[1]:.6f}" z="{v[2]:.6f}"/>' for v in verts)
        tris_xml=' '.join(f'<triangle v1="{t[0]}" v2="{t[1]}" v3="{t[2]}"/>' for t in tris)
        objects.append(f'<object id="{obj_id}" name="{name}" type="model" pid="{mat_id}" pindex="0"><mesh><vertices>{verts_xml}</vertices><triangles>{tris_xml}</triangles></mesh></object>')
        build_items.append(f'<item objectid="{obj_id}" transform="1 0 0 0 1 0 0 0 1"/>')
    if not build_items:raise ValueError('没有可导出的部件')
    model=f'''<?xml version="1.0" encoding="utf-8"?>
<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="millimeter" xml:lang="en-US" xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">
\t<resources>
\t\t{''.join(materials)}
\t\t{''.join(objects)}
\t</resources>
\t<build>
\t\t{''.join(build_items)}
\t</build>
</model>'''
    content_types='''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'''
    rels='''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'''
    model_rels='''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'''
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',content_types)
        z.writestr('_rels/.rels',rels)
        z.writestr('3D/3dmodel.model',model)
        z.writestr('3D/_rels/3dmodel.model.rels',model_rels)
    return output
