# Image-to-3D 双路径模型路由

## 决策结论

工程同时支持单图和三视图两条独立生成路径。两条路径使用不同模型，不允许把多视图任务静默降级为单图任务。

| 输入证据 | 路由 | 模型 | 实际模型输入 |
|---|---|---|---|
| 仅正面图 | `single-view` | Hunyuan3D 2.1 | `image=<front>` |
| 正面 + 左侧 + 背面 | `multi-view` | Hunyuan3D-2mv | `image={front, left, back}` |

Hunyuan3D 2.1 单图模型依靠训练先验推断隐藏面。它适合带有明暗、遮挡、透视或 3/4 角度信息的输入，但对严格正交、平涂、近似剪影的角色设定图可能生成薄片。

Hunyuan3D-2mv 是独立的 1.1B 多视图形状模型。正面、左侧和背面会共同参与几何生成；不是选取其中一张，也不是把三张图拼接成一张。

## 路由规则

1. `front` 必须存在。
2. 只有 `front` 时选择 `single-view`。
3. `front`、`side`、`back` 同时存在时选择 `multi-view`。
4. 工程资产角色 `side` 在 Hunyuan3D-2mv 推理入口映射为官方键名 `left`。
5. 三视图缺少任一必需视角时，不得伪装为完整多视图任务。
6. 多视图模型或运行环境缺失时任务必须阻断，并报告 `Hunyuan3D-2mv environment unavailable`。
7. SF3D 和 TripoSR 当前只属于单图备用后端，不得接管多视图任务。

## 强制输入预处理

两条路径的每张条件图都必须独立执行：

```text
解码图片
→ 去除白色/普通背景并生成 alpha
→ 清除 FRONT / LEFT / BACK 等视图标签
→ 按前景 alpha 包围盒裁切
→ 保留统一安全边距
→ 缩放并居中到 512×512 透明画布
→ 保存实际送模条件图作为任务产物
```

默认主体占画布比例为 88%。任务产物必须让用户能够核对模型真正收到的图片，而不是只展示原始上传图片。

## 生成后的质量门禁

GLB 生成后、渲染评审前必须执行稳健厚度检查：

- 从 GLB 的 `POSITION` accessor 读取真实顶点。
- 每个轴使用 5%–95% 分位范围，避免孤立异常顶点撑大普通包围盒。
- `thinAxisRatio = 最小稳健轴尺寸 / 最大稳健轴尺寸`。
- 对 `character` 和 `hybrid`，`thinAxisRatio < 0.08` 判定为薄片并阻断。
- 门禁通过后进入 `awaiting_geometry_confirmation`。
- 只有用户确认粗模后，才生成标准评审视图并进入 Comment 评审。

禁止使用简单挤出或整体加厚来修复薄片角色，因为这只会产生厚浮雕，无法恢复正确的头部、躯干、袖子和裙摆体积。

## 模型与运行目录

```text
.local/Hunyuan3D-2.1-model/       # 单图模型
.local/Hunyuan3D-2mv-model-v2/    # 多视图模型权重
.local/Hunyuan3D-2mv-runtime/     # 官方 Hunyuan3D-2 推理代码
pipeline/run_hunyuan_yoyo.py      # 单图推理与预处理
pipeline/run_hunyuan_multiview.py # 三视图推理与预处理
```

Hunyuan3D-2mv 官方权重来自 `tencent/Hunyuan3D-2mv` 的 `hunyuan3d-dit-v2-mv` 子目录。形状模型负责几何；纹理和 PBR 属于后续独立阶段。

## 质量等级合同

| 等级 | Hunyuan octree | 纹理 | 脸部处理 |
|---|---:|---:|---|
| 标准 `standard` | 256 | 无 | 无 |
| 高 `high` | 384 | 2048×2048 多视图投射 | 由 Base Color 保留五官 |
| 超高 `ultra` | 512 | 4096×4096 多视图投射 | 头部区域优先使用正面投射，保留眼睛、眉毛和嘴 |

高和超高质量使用实际送入模型的去背景 `front/side/back` 条件图建立投射 UV，并把纹理嵌入最终 Web GLB。超高的“脸部精修”是面部参考证据优先的外观精修，不宣称把二维眼线自动雕刻为独立眼球或眼睑几何。每张投射纹理同时作为任务产物保存，GLB 元数据记录 `geometryResolution`、`textureResolution` 和 `faceRefinement`。

## 可追溯性要求

每次任务至少记录：

- 路由：`single-view` 或 `multi-view`；
- 实际模型与版本；
- 输入资产 ID、角色和 SHA-256；
- 实际送模条件图；
- seed、steps、octree resolution；
- GLB 稳健三轴尺寸和 `thinAxisRatio`；
- 用户几何确认时间和后续评审结果。
