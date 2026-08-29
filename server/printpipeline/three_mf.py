"""纯 Python 多色 3MF 生成器（无第三方依赖）。

输入：部件二进制 STL 列表 + 颜色映射 {stl_name: "#RRGGBB"}
输出：多对象多色 3MF（每部件一个 build item + basematerials 材质），
     可被 Bambu Studio / OrcaSlicer 识别为多色分区。

二进制 STL 格式：80 字节头 + uint32 三角形数 + 每三角形 12*float32 + 2 字节属性。
"""
from __future__ import annotations
import struct, zipfile
from pathlib import Path
from xml.sax.saxutils import escape

def parse_binary_stl(path:Path)->tuple[list[tuple[float,float,float]],list[tuple[int,int,int]]]:
    data=path.read_bytes()
    count=struct.unpack_from('<I',data,80)[0]
    raw_verts=[];raw_tris=[]
    off=84
    for i in range(count):
        # normal(12) + v0(12) + v1(12) + v2(12) + attr(2)
        v0=struct.unpack_from('<fff',data,off+12)
        v1=struct.unpack_from('<fff',data,off+24)
        v2=struct.unpack_from('<fff',data,off+36)
        raw_verts.extend([v0,v1,v2]);raw_tris.append((3*i,3*i+1,3*i+2))
        off+=50
    # 顶点去重（字典）
    vmap:dict[tuple[float,float,float],int]={};verts:list[tuple[float,float,float]]=[];tris=[]
    for t in raw_tris:
        tri=[]
        for idx in t:
            v=raw_verts[idx]
            # 浮点量化去重
            q=(round(v[0],6),round(v[1],6),round(v[2],6))
            if q not in vmap:
                vmap[q]=len(verts);verts.append(q)
            tri.append(vmap[q])
        tris.append(tuple(tri))
    return verts,tris

def _xml_escape(s:str)->str:return escape(s)

def build_3mf(parts:list[tuple[Path,str]], colors:dict[str,str], output:Path):
    """parts: [(stl_path, part_name)]；colors: {stl_name: '#RRGGBB'}"""
    mesh_defs=[]      # <mesh> XML 片段
    build_items=[]    # <item> 片段
    materials=[]      # <basematerials> 片段
    mat_id=0
    obj_id=0
    for stl,name in parts:
        verts,tris=parse_binary_stl(stl)
        if not tris:continue
        oid=f'O{obj_id}';mid=f'M{mat_id}'
        obj_id+=1;mat_id+=1
        # 材质
        hexc=colors.get(stl.name,'9E9E9E').lstrip('#')
        r,g,b=int(hexc[0:2],16),int(hexc[2:4],16),int(hexc[4:6],16)
        materials.append(f'''<basematerials id="{mid}"><base name="color_{stl.stem}" displaycolor="#{hexc}" type="supplemental"><color><srgb r="{r}" g="{g}" b="{b}"/></color><p2>#FFFF00</p2><p3>0.1</p3><p4>0.5</p4></base></basematerials>''')
        # 顶点/三角
        verts_xml=' '.join(f'{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}' for v in verts)
        tris_xml=' '.join(f'{t[0]} {t[1]} {t[2]}' for t in tris)
        mesh_defs.append(f'''<object id="{oid}" type="model"><mesh><vertices>{verts_xml}</vertices><triangles>{tris_xml}</triangles></mesh><components><component objectid="{oid}"><materialid="{mid}" /></components></object>''')
        build_items.append(f'<item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1" />')
    if not build_items:raise ValueError('没有可导出的部件')
    model=f'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">
<resources>{''.join(mesh_defs)}{''.join(materials)}</resources>
<build>{''.join(build_items)}</build>
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
