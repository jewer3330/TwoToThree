# Character reconstruction pipeline

YOYO 已验证的基线锁定、免费精雕与参考图投射流程：
[`docs/YOYO_REFERENCE_PROJECTION_WORKFLOW.md`](../docs/YOYO_REFERENCE_PROJECTION_WORKFLOW.md)

YOYO 后续默认采用真实像素的参考相机投射；禁止恢复坐标阈值分色或脱离已确认粗模的模块化重建。

完整的质量门、失败案例、命名约定和下一个模型检查清单见：

[`docs/CHARACTER_SF3D_BLENDER_PIPELINE.md`](../docs/CHARACTER_SF3D_BLENDER_PIPELINE.md)

1. `npm run model:check`
2. Accept the gated `stabilityai/stable-fast-3d` license on Hugging Face and set `HF_TOKEN` in this shell.
3. Install Visual Studio 2022 C++ build tools and Blender 4.x; put `blender` on `PATH`.
4. `npm run model:setup`
5. `npm run model:install`
6. `npm run model:generate` (SF3D first, TripoSR fallback)
7. Import `public/models/field-commander.glb` into Blender. Use the front/side/back PNGs as orthographic image planes. Fix face, fingers, crotch, garment intersections, and silhouette, then rig and optimize.
8. Export the cleaned web GLB to the same path.

`src/loadGeneratedCharacter.js` normalizes the GLB to ground level and five world units high. SF3D receives one image only; side/back images remain Blender alignment evidence.
