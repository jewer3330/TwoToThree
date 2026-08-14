# Comment 驱动的参考图修订与 Hunyuan 候选重生成 V1 计划

> 本地 AI 修订参考图方案见 [`LOCAL_AI_REFERENCE_EDIT_ARCHITECTURE.md`](./LOCAL_AI_REFERENCE_EDIT_ARCHITECTURE.md)。

## 1. 背景与目标

当前系统已经具备以下闭环：

```text
参考图片 → Hunyuan 基础 GLB → 基线验收并锁定
→ Blender 自动精修 → 派生版本 → 质量门禁 → 版本验收
```

V1 增加“一条问题一条 Comment”的评审机制。用户可以为 Comment 提供修订设计图或辅助参考图，创建新的 Reference Set，再调用 Hunyuan 完整重生成独立候选版本。

该能力必须描述为“根据修订参考图重新生成候选版本”，不得描述为“精确局部修改当前网格”。Hunyuan 不保证仅修改 Comment 指定区域，也不保证拓扑、UV、材质或其他已通过区域保持不变。

## 2. 核心产品原则

### 2.1 一个 Comment 只描述一个问题

每条 Comment 独立拥有：标题、详细说明、问题类型、严重程度、模型部位、模型标注、相机快照、截图、辅助参考图、回复线程、推荐处理路线、处理状态、关联任务和输出版本。

### 2.2 保存 Comment 不启动任务

新增或回复 Comment 后停留在版本验收页并保留当前视角。只有用户主动选择 Comments 并确认后，才创建 Reference Set 和修订任务。

### 2.3 永不覆盖原始资产

- 修订图保存为新资产。
- Reference Set 是不可变版本。
- Hunyuan 输出创建独立候选版本。
- 原模型、原图、Comments 和历史任务永久保留。

### 2.4 自动能力必须真实标记

处理路线：

- `blender_automatic`：确定性的 Blender 自动处理。
- `reference_regeneration`：修订参考图后由 Hunyuan 完整重生成。
- `manual`：需要人工建模、雕刻或绘制。
- `not_configured`：系统当前未配置。

不得把 `reference_regeneration` 标记为局部自动修复。

### 2.5 任务成功不等于 Comment 已解决

Hunyuan 或 Blender 成功后，关联 Comments 只能进入 `awaiting_review`。用户逐条选择：已解决、部分解决、未解决或产生新问题。

## 3. 深度问题的特殊规则

突出、凹陷、厚度和前后位置难以通过正面图表达。此类 Comment 应要求侧面或 3/4 视觉证据。

例如“眼睛轻微凹陷”需要明确：

- 眼球最高点不得明显超过面部轮廓。
- 眼睑对眼球形成浅包裹关系。
- 保持瞳孔高度、双眼间距、鼻子和整体脸宽。
- 不得误解为闭眼、删除眼球或黑洞眼窝。

没有新视觉证据时，不得仅使用原始图片重新随机生成。第一阶段由本地 ComfyUI 生成可审核的修订侧面或 3/4 图，用户批准后才能进入 Reference Set。

## 4. 页面与路由

### 4.1 模型预览与版本验收

```text
/review/:projectId
```

三栏布局：

```text
版本历史 | 3D 模型与标注点 | Comments 列表/详情
```

支持版本切换、模型表面编号标注、独立 Comment、回复、关闭/重开、附件、筛选和多选创建修订任务。

### 4.2 修订任务确认

```text
/revisions/new/:versionId
```

展示源版本、所选 Comments、处理路线、参考图片、即将创建的 Reference Set、真实输入图片、Hunyuan 风险、Blender 配置、未处理 Comments 和“不覆盖源版本”说明。

### 4.3 修订监控与复核

```text
/revisions/:revisionId
```

展示 Reference Set、真实生成日志、Blender 阶段、质量门禁、源/候选模型对比、四视图、产物下载和逐条 Comment 复核。

## 5. Comment 生命周期

```text
draft → open → planned → processing → awaiting_review
→ resolved | partially_resolved | unresolved | closed
```

其他转换：

```text
open → needs_manual | not_configured
resolved → reopened
closed → open
```

草稿可删除；已提交 Comment 保留历史。一次任务可关联多条 Comments，一条 Comment 可跨多轮任务。未选中 Comments 保持原状态。

## 6. Reference Set

Reference Set 是一次生成任务使用的完整参考证据集合，记录项目、版本号、父版本、图片资产、视角角色、关联 Comments、创建时间、一致性检查和锁定状态。

Reference Set 用于任务后立即锁定；后续修改必须创建新版本。只有已批准的 AI 修订图或用户上传图可以成为修订证据。

## 7. Hunyuan 使用边界

可以：根据完整参考证据重新生成候选模型，并在生成后进入 Blender 与质量门禁。

不保证：仅修改局部、其他区域不变、拓扑连续、UV/材质连续、身份一定改善或 Comment 自动解决。

当前 runner 只接受单个 `--image`。完成多视图适配前，页面必须明确展示真正输入 Hunyuan 的单张图片，不得宣称已执行多视图约束生成。

## 8. 数据模型

核心表：

- `version_comments`
- `comment_replies`
- `comment_attachments`
- `reference_sets`
- `reference_set_assets`
- `revision_requests`
- `revision_comment_links`
- `reference_asset_drafts`（本地 AI 修订图）

所有 JSON 快照必须保存生成或评审当时的真实参数，不得只保存可变配置引用。

## 9. API

### Comments

```text
POST   /api/versions/{versionId}/comments
GET    /api/versions/{versionId}/comments
GET    /api/comments/{commentId}
PATCH  /api/comments/{commentId}
POST   /api/comments/{commentId}/replies
POST   /api/comments/{commentId}/close
POST   /api/comments/{commentId}/reopen
POST   /api/comments/{commentId}/attachments
```

### AI 修订参考图

```text
POST /api/comments/{commentId}/reference-drafts/plan
POST /api/comments/{commentId}/reference-drafts
GET  /api/reference-drafts/{draftId}
POST /api/reference-drafts/{draftId}/cancel
POST /api/reference-drafts/{draftId}/retry
POST /api/reference-drafts/{draftId}/approve
POST /api/reference-drafts/{draftId}/reject
```

### Reference Sets 与修订任务

```text
POST /api/projects/{projectId}/reference-sets
GET  /api/projects/{projectId}/reference-sets
GET  /api/reference-sets/{referenceSetId}
POST /api/reference-sets/{referenceSetId}/validate
POST /api/reference-sets/{referenceSetId}/lock

POST /api/revisions/plan
POST /api/revisions
GET  /api/revisions/{revisionId}
POST /api/revisions/{revisionId}/cancel
POST /api/revisions/{revisionId}/retry
POST /api/revisions/{revisionId}/comments/{commentId}/review
```

## 10. V1 实施范围

V1 必须完成：

1. 创建多条独立 Comments。
2. 保存模型标注、相机快照和截图。
3. 独立回复、附件、关闭和重开。
4. 多选 Comments 创建修订计划。
5. 不可覆盖的 Reference Set 版本。
6. 本地 AI 修订侧面/3/4 图生成与用户审批。
7. 无已批准新证据时阻断参考图重生成。
8. 真实 Hunyuan 独立候选版本。
9. 真实 Blender 精修、四视图和质量门禁。
10. 源/候选模型与四视图对比。
11. 逐条 Comment 人工复核。
12. 原模型、原图和历史 Comments 保持不变。
13. ComfyUI、Hunyuan 和 Blender 串行使用 GPU。

V1 暂不包含浏览器内复杂绘制、Hunyuan 精确局部网格编辑、自动身份相似度判定、任意自然语言转 Blender 雕刻、专业重拓扑或动画修复。

## 11. 验收标准

1. 连续创建至少三条独立 Comments。
2. 保存后停留在验收页并保留视角。
3. 点击 Comment 可定位模型标注。
4. Comment 可独立回复、关闭和重开。
5. 深度问题可生成并审批 AI 修订侧面/3/4 图。
6. 未批准图片不能进入 Reference Set。
7. 没有新证据时不能启动参考图重生成。
8. Reference Set 不覆盖原图并在任务启动时锁定。
9. 后端真实执行 Hunyuan 和 Blender。
10. 新模型创建独立版本并记录完整关系。
11. 任务成功后 Comments 仅进入 `awaiting_review`。
12. 用户可逐条复核四种结果。
13. GPU 工作负载不并发争用。
14. 自动化测试覆盖成功、失败、取消、版本化和复核。
15. 使用真实项目完成一次完整本地烟测。
16. 前端构建和后端测试全部通过。

## 12. 推荐实施顺序

### 阶段 A：Comment 基础闭环

数据表、API、列表详情、回复、3D 标注、截图、状态和筛选。

### 阶段 B：本地 AI 修订参考图

ComfyUI、局部蒙版、候选生成、审批、参数追溯和 GPU 调度。

### 阶段 C：Reference Set

视角管理、版本化、验证、锁定及 Comment/资产关联。

### 阶段 D：候选重生成

确认页、真实 Hunyuan、版本派生、Blender 和质量门禁。

### 阶段 E：逐条复核

源/候选对比、视角恢复、逐条结果和未解决项进入下一轮。
