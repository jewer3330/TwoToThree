import os
import shutil
import sys

import bpy

WORKSPACE = r"C:\Users\vip\Documents\3d"
ADDON_SOURCE = os.path.join(WORKSPACE, ".local", "blender-mcp-server", "addon")
ADDON_TARGET = os.path.join(bpy.utils.user_resource("SCRIPTS"), "addons", "blender_mcp_bridge")
GLB_PATH = os.path.join(WORKSPACE, "public", "models", "field-commander.glb")
BLEND_PATH = os.path.join(WORKSPACE, "field-commander", "field-commander-sf3d.blend")

if os.path.isdir(ADDON_TARGET):
    shutil.rmtree(ADDON_TARGET)
shutil.copytree(ADDON_SOURCE, ADDON_TARGET)

if ADDON_TARGET not in sys.path:
    sys.path.insert(0, os.path.dirname(ADDON_TARGET))

bpy.ops.preferences.addon_enable(module="blender_mcp_bridge")
prefs = bpy.context.preferences.addons["blender_mcp_bridge"].preferences
prefs.safe_mode = True
prefs.allow_inline_code = True
prefs.approved_script_roots = WORKSPACE
bpy.ops.wm.save_userpref()

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=GLB_PATH)

for obj in bpy.context.scene.objects:
    if obj.type == "MESH":
        obj.name = "Field_Commander_SF3D"
        obj.data.name = "Field_Commander_SF3D_Mesh"
        for polygon in obj.data.polygons:
            polygon.use_smooth = True

bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
print(f"BLENDER_MCP_READY={BLEND_PATH}")
