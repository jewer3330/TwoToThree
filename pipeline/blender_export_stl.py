from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a Blender/GLB model to STL")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--scope", choices=("all", "visible"), default="visible")
    parser.add_argument("--unit", choices=("mm", "cm", "m"), default="mm")
    parser.add_argument("--apply-modifiers", action="store_true")
    parser.add_argument("--target-height-mm", type=float)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def load_source(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(path))
    elif suffix == ".glb":
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        bpy.ops.import_scene.gltf(filepath=str(path))
    else:
        raise RuntimeError(f"Unsupported Blender export source: {suffix}")


def main() -> None:
    args = arguments()
    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    if not source.is_file():
        raise RuntimeError(f"Source file does not exist: {source}")

    load_source(source)
    meshes = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and (args.scope == "all" or not obj.hide_get())
    ]
    if not meshes:
        raise RuntimeError("No mesh objects are available for STL export")

    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    output.parent.mkdir(parents=True, exist_ok=True)

    scale = {"mm": 1000.0, "cm": 100.0, "m": 1.0}[args.unit]
    source_height = None
    if args.target_height_mm is not None:
        if args.target_height_mm <= 0:
            raise RuntimeError("Target print height must be greater than zero")
        depsgraph = bpy.context.evaluated_depsgraph_get()
        world_z = [
            (evaluated.matrix_world @ Vector(corner)).z
            for obj in meshes
            for evaluated in (obj.evaluated_get(depsgraph),)
            for corner in evaluated.bound_box
        ]
        source_height = max(world_z) - min(world_z)
        if source_height <= 1e-9:
            raise RuntimeError("Model height is zero; target print height cannot be applied")
        scale = args.target_height_mm / source_height
    if hasattr(bpy.ops.wm, "stl_export"):
        bpy.ops.wm.stl_export(
            filepath=str(output),
            export_selected_objects=True,
            apply_modifiers=args.apply_modifiers,
            global_scale=scale,
        )
    else:
        bpy.ops.export_mesh.stl(
            filepath=str(output),
            use_selection=True,
            use_mesh_modifiers=args.apply_modifiers,
            global_scale=scale,
            ascii=False,
        )
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("Blender did not create an STL file")
    target = f" targetHeightMm={args.target_height_mm:g} sourceHeight={source_height:g}" if source_height is not None else ""
    print(f"STL_EXPORT_OK path={output} bytes={output.stat().st_size} meshes={len(meshes)}{target}")


if __name__ == "__main__":
    main()
