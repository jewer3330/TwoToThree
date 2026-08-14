# 本地 AI 修订参考图架构

## 决策

第一阶段采用纯本地方案：`ComfyUI Local API + Stable Diffusion 1.5 Inpainting + 局部蒙版 + 低重绘强度 + 用户批准门禁`。

Cloudflare Workers AI 需要身份验证，不作为第一阶段依赖，仅保留为未来可选 Provider。

## 标准流程

```text
Comment
→ 判断所需视角与局部区域
→ 本地 AI 生成修订参考图草稿
→ 用户批准或拒绝
→ 批准图片进入新的不可变 Reference Set
→ Hunyuan 候选重生成
→ Blender 自动精修与技术质量门禁
→ 用户逐条复核 Comment
```

对于突出、凹陷、厚度、前后位置和包裹关系等问题，没有新视觉证据时禁止启动参考图重生成。

## 本地运行基线

- GPU：NVIDIA GeForce RTX 4060 Ti 8GB。
- ComfyUI 安装在 `.local/ComfyUI`，使用独立虚拟环境。
- 服务仅监听 `127.0.0.1:8188`。
- ComfyUI、Hunyuan 和 Blender 共用串行 GPU 队列。
- 服务、模型或工作流不可用时标记 `not_configured`，不得使用模拟图片。

```text
.local/ComfyUI/
.local/ComfyUI/.venv/
.local/ComfyUI/models/checkpoints/
.local/ComfyUI/models/controlnet/
pipeline/workflows/comment-reference-inpaint-v1.json
server/image_backends.py
```

## 生成规则

输入包括原始目标视角图、单条 Comment、局部蒙版、身份保持约束、负面约束、固定 seed、模型版本、工作流版本和参数快照。

眼部轻微凹陷参数基线：

```text
denoise / strength: 0.20–0.35
steps: 20–28
候选数量: 2–4
蒙版: 仅眼球、眼睑及少量眼眶
```

状态流：

```text
generating → awaiting_approval → approved | rejected | failed
```

未经批准的 AI 修订图不得加入 Reference Set，也不得启动 Hunyuan。批准操作创建新图片资产，不覆盖源图。

## 数据模型与 API

新增 `reference_asset_drafts`，记录项目、Comment、源/输出资产、视角、Provider、模型、工作流版本、Prompt、负面 Prompt、蒙版、seed、参数、状态及审核时间。

Provider：`comfyui_local | cloudflare_workers_ai | not_configured`。V1 默认 Provider 为 `comfyui_local`。

```text
POST /api/comments/{commentId}/reference-drafts/plan
POST /api/comments/{commentId}/reference-drafts
GET  /api/reference-drafts/{draftId}
POST /api/reference-drafts/{draftId}/cancel
POST /api/reference-drafts/{draftId}/retry
POST /api/reference-drafts/{draftId}/approve
POST /api/reference-drafts/{draftId}/reject
```

## Hunyuan 边界

当前 runner 仅接受一个 `--image`，尚未真正消费多视图 Reference Set。完成多视图适配前：

- 确认页展示真正作为 Hunyuan 输入的图片。
- 使用批准后的 3/4 图时标明“单图候选重生成”。
- 不得把“保存多张、实际只用一张”描述为多视图约束生成。
- 没有已批准的新视觉证据时阻断 `reference_regeneration`。

## GPU 调度与验收

GPU 队列按 `image_reference_edit → hunyuan_generation → blender_refinement → render_review` 串行执行。任务结束后必须释放模型和显存。

验收覆盖：修订图生成、参数可追溯、原图不覆盖、逐张批准/拒绝、未批准图片不能进入 Reference Set、无新证据时阻断任务、GPU 不并发争用，以及一次完整本地烟测。
