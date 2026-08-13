# YOYO：Hunyuan3D 几何优先工作流

状态：Hunyuan3D 2.1 首轮几何已通过视觉验收  
更新时间：2026-08-12  
目标：以设计图一致性为首要指标，尽量一次生成可用的角色几何，再进行分件、分色与最终装配。

## 当前推荐流程

```text
干净的单角色参考图
→ Hunyuan3D 2.1 生成高质量几何 GLB
→ Blender 四视图验收并锁定几何基线
→ Blender 按真实结构分件与修正局部拓扑
→ 参考图投射 Base Color，并人工校正侧面/背面
→ 分离 Roughness / Normal / Metalness
→ Blender 最终装配、减面、UV 与 GLB 导出
→ 网页预览验收
```

Stable Fast 3D 不再是 YOYO 的强制第一步。它保留为快速草模和 Hunyuan3D 不可用时的兜底方案。

## 已通过的 Hunyuan3D 几何基线

- 输入：`public/yoyo-reference.png`
- 模型：Tencent Hunyuan3D 2.1 Shape
- 推理脚本：`pipeline/run_hunyuan_yoyo.py`
- GLB：`public/models/yoyo-hunyuan-shape-v1.glb`
- Blender：`yoyo-blender/yoyo-hunyuan-shape-v1.blend`
- 四视图：`yoyo-blender/hunyuan-v1/`
- 随机种子：`20260812`
- 扩散步数：30
- 体积解码分辨率：256
- 顶点：167,718
- 面：335,484
- GLB 大小：约 6.04 MB
- 包围尺寸：1.3115923 × 0.8890660 × 1.9868238

视觉验收结论：相较 SF3D 粗模，整体比例、兜帽、帽尾、披肩、衣摆、手指、靴子、斜挎带和包袋结构均明显提升。该版本成为后续分件与细化的首选几何基线；旧基线继续保留，不覆盖。

## 本地环境与权重

- Python 环境：`.local/hunyuan-bootstrap/`
- Hunyuan 源码：`.local/Hunyuan3D-2.1-space/hy3dshape/`
- 权重目录：`.local/Hunyuan3D-2.1-model/`
- DiT：7,366,389,768 字节
- VAE：655,648,152 字节
- 下载镜像：`https://hf-mirror.com/tencent/Hunyuan3D-2.1`

每次迁移或重新下载后必须核对权重的精确字节数，不能只检查文件是否存在。

## RTX 4060 Ti 8GB 的必要设置

官方自定义 Pipeline 在本机需要以下兼容处理，已写入推理脚本：

1. 模型先以 FP16 装载到 CPU，避免启用 offload 前显存溢出。
2. 手工补充 `conditioner`、`model`、`vae` 的 `components` 映射。
3. 调用 `enable_model_cpu_offload()`。
4. 安装 offload hooks 后，将 Pipeline 的逻辑设备标记为 CUDA，确保 latent 与 scheduler 张量位于同一设备。
5. CUDA 随机生成器使用固定种子，保证对比可复现。

本次体积解码时显存约 1.9 GB，CPU offload 工作正常。

## 推理与预览命令

```powershell
& .\.local\hunyuan-bootstrap\Scripts\python.exe `
  .\pipeline\run_hunyuan_yoyo.py `
  --steps 30 `
  --resolution 256

& .\.local\Blender52\blender.exe `
  --background `
  --python .\pipeline\blender_hunyuan_preview.py
```

首轮先使用 256 / 30 判断设计一致性。只有通过四视图验收后，才考虑更高分辨率或更多步数，避免在错误轮廓上浪费时间。

## 后续分件原则

分件必须服从已经通过的整体轮廓，不允许为了方便切割而大幅重建角色。优先分离：

- 星星
- 帽体、帽尾与绒球
- 兜帽外层与内帽沿
- 脸部
- 双眼
- 披肩左右片与月牙扣
- 外套/裙摆
- 左右手与袖口
- 左右腿与靴子
- 背带
- 包体、包盖、扣件

先在复制件上操作，原始 Hunyuan 网格保留为隐藏、锁定、不可选择的基线。切缝必须沿服装接缝或遮挡区，不能用世界坐标阈值自动切出水平色带。

## 分色与贴图原则

1. 正面参考图用于相机投射 Base Color。
2. 投射仅覆盖相机可见且法线朝向可信的表面。
3. 侧面和背面属于推断区域，需人工延展和修补。
4. 眼睛、雀斑、月牙扣、背带、包袋、靴子等边界优先成为独立材质或独立对象。
5. Base Color、Roughness、Normal、Metalness 分开制作。
6. 禁止把一张正面图强行拉伸到侧面和背面。

## Stable Fast 3D 备选路线

当 Hunyuan3D 权重不可用、显存/内存不足或只需要几分钟内确认大轮廓时，可使用：

```text
参考图 → Stable Fast 3D → Blender 体素连续化 → 四视图验收
```

历史资产继续保留：

- `public/models/yoyo-sf3d.glb`
- `yoyo-blender/yoyo-volume-v2.blend`
- `yoyo-blender/yoyo-front-projection-v1.blend`
- `public/models/yoyo-front-projection-v1.glb`

这条路线不再作为当前 YOYO 的首选，因为单图粗模在服装层次、手部、包袋和帽兜细节上明显弱于 Hunyuan3D。

## 每轮验收要求

每轮至少输出正面、三分之四、侧面和背面，并记录：

- 是否改变通过验收的整体比例和轮廓；
- 是否出现粘连、孔洞、薄片、悬浮件或错误融合；
- 分件边界是否沿真实结构；
- 正面投射与侧背面推断的范围；
- 顶点、面数、材质数、纹理尺寸和 GLB 大小；
- 与设计图仍不一致的具体部位；
- 唯一的下一步动作。

正面好看不能掩盖侧面和背面问题。任何全局平滑、Voxel Remesh、自动减面或重拓扑，都必须在副本上执行并重新通过四视图验收。
