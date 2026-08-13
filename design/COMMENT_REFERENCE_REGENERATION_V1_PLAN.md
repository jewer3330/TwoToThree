# Comment 驱动的参考图修订与 Hunyuan 候选重生成 V1 计划

## 1. 背景与目标

当前系统已经具备以下闭环：

> 参考图片 → Hunyuan 基础 GLB → 基线验收并锁定 → Blender 自动精修 → 派生版本 → 质量门禁 → 版本验收

当前缺口是：用户在“模型预览与版本验收”页面发现造型、身份特征、局部结构或材质问题后，无法针对每个问题分别记录、讨论和发起修订。

V1 的目标是增加“一条问题一条 Comment”的评审机制，并允许用户为 Comments 上传修订后的设计图或辅助参考图，创建新的 Reference Set，再调用 Hunyuan 完整重新生成一个独立候选版本。

该能力必须被准确描述为：

> 根据修订参考图重新生成候选版本

不得描述为：

> 精确局部修改当前网格

Hunyuan 不保证只修改 Comment 指定区域，也不保证拓扑、UV、材质或其他已通过区域保持不变。因此，每次结果必须作为新候选版本保存，并由用户逐条复核关联 Comments。

---

## 2. 核心产品原则

### 2.1 一个 Comment 只描述一个问题

正确示例：

- `#1 双眼向前突出`
- `#2 左袖口与手腕穿插`
- `#3 背面披风颜色不正确`

不得使用一个大文本框混写多个问题。

每条 Comment 独立拥有：

- 标题
- 详细说明
- 问题类型
- 严重程度
- 模型位置或部件
- 创建时的相机视角
- 标注截图
- 辅助参考图
- 回复线程
- 处理能力判断
- 处理状态
- 关联修订任务和输出版本

### 2.2 保存 Comment 不启动任务

用户添加或回复 Comment 后，继续停留在“模型预览与版本验收”页面。只有用户主动选择一条或多条 Comments，并点击“创建修订任务”时，才进入任务确认流程。

### 2.3 原设计图和原模型永不覆盖

- 修订设计图保存为新的参考资产。
- 多张参考图组成不可变的 Reference Set 版本。
- Hunyuan 输出创建新的候选模型版本。
- 原模型、原参考图、Comments 和历史任务保留。

### 2.4 自动能力必须真实标记

Comment 应被分类为以下处理路线之一：

- `blender_automatic`：确定性的 Blender 自动处理。
- `reference_regeneration`：修订参考图后由 Hunyuan 完整重生成候选版本。
- `manual`：需要人工建模、雕刻或绘制。
- `not_configured`：当前系统未配置。

不得将 `reference_regeneration` 标记为“局部自动修复”。

### 2.5 Comment 不自动判定为已解决

即使 Hunyuan 或 Blender 任务成功，关联 Comments 也只能进入 `awaiting_review`。必须由用户逐条选择：

- 已解决
- 部分解决
- 未解决
- 产生新问题

---

## 3. 典型案例：眼睛突出

用户发现生成角色的眼球明显向前突出，希望与设计图一致。

Comment 示例：

```text
标题：双眼向前突出
类型：身份特征 / 局部形体
严重程度：重要
区域：左眼、右眼
目标：眼球不得明显超出眼睑与眉骨轮廓
限制：保持瞳孔高度、双眼间距、鼻子和整体脸宽
```

当前 Blender 通用精修无法可靠完成该修改；Hunyuan 也无法保证精确局部编辑现有模型。

推荐处理方式：

1. 保留原始正面设计图。
2. 上传或制作修订后的正面设计图。
3. 增加侧面眼部辅助图，明确眼球深度。
4. 可增加左前 3/4 辅助图，确认眼睑包覆关系。
5. 将这些图片与 Comment 关联并创建 Reference Set v2。
6. 使用 Reference Set v2 调用 Hunyuan 完整重生成候选模型。
7. 运行现有 Blender 自动精修和质量门禁。
8. 将候选版本与原版本并排比较。
9. 用户复核 Comment 是否解决。

正面图难以单独表达深度问题。对于“突出、凹陷、厚度、前后位置”等 Comment，应提示用户补充侧面或 3/4 图。

---

## 4. 页面与路由设计

### 4.1 模型预览与版本验收

现有路由：

```text
/review/:projectId
```

页面调整为三栏：

```text
版本历史 | 3D 模型与标注点 | Comments 列表/详情
```

主要能力：

- 切换模型版本。
- 在 3D 模型上点击添加 Comment 标记点。
- 创建多条独立 Comments。
- 查看、回复、编辑草稿、关闭或重新打开 Comment。
- 上传 Comment 附件和辅助参考图。
- 筛选当前版本、未解决、阻断和已解决 Comments。
- 勾选多条 Comments 创建修订任务。

保存 Comment 后不跳转页面，并保留当前模型视角。

### 4.2 Comment 编辑器

每条 Comment 的表单字段：

- 标题：必填，简短描述单一问题。
- 详细说明：必填。
- 问题类型：轮廓、比例、身份特征、几何、穿插、缺失结构、贴图、颜色、材质、UV、其他。
- 严重程度：阻断、重要、一般、备注。
- 部件：整体、头部、面部、左眼、右眼、头发、躯干、手部、腿部、服装、配件、材质、其他。
- 模型标记：对象名称、三维坐标、法线。
- 相机快照：位置、旋转、目标点、缩放。
- 当前视角截图。
- 附件和辅助参考图。
- 推荐处理路线。

### 4.3 修订任务确认页

建议新路由：

```text
/revisions/new/:versionId
```

展示：

- 源模型版本。
- 已选择的 Comments。
- 每条 Comment 的处理路线和能力状态。
- 已选择的参考图片。
- 即将创建的 Reference Set 新版本。
- Hunyuan 完整重生成风险说明。
- Blender 后处理配置。
- 本次不会处理的 Comments。
- 源版本不会被覆盖的说明。

用户确认后才启动任务。

### 4.4 修订任务监控与复核页

建议新路由：

```text
/revisions/:revisionId
```

展示：

- Reference Set 构建状态。
- Hunyuan 真实生成阶段和日志。
- Blender 自动精修阶段和日志。
- 质量门禁。
- 源版本与候选版本。
- 关联 Comments 和各自状态。
- 前后模型对比。
- 四视图对比。
- 产物下载。

任务完成后在同一页面逐条复核 Comments。

---

## 5. Comment 生命周期

```text
draft
→ open
→ planned
→ processing
→ awaiting_review
→ resolved
→ closed
```

其他状态转换：

```text
open → needs_manual
open → not_configured
awaiting_review → partially_resolved
awaiting_review → unresolved
resolved → reopened
```

规则：

- 草稿可编辑或删除。
- 已提交 Comment 保留历史，不物理删除。
- 一次修订任务可关联多条 Comments。
- 一条 Comment 可跨多轮修订任务。
- 未选中的 Comments 保持原状态。
- 任务成功只将关联 Comments 更新为 `awaiting_review`。

---

## 6. Reference Set 版本化

Reference Set 是一次 Hunyuan 生成所使用的完整参考证据集合。

示例：

```text
Reference Set v1
- 原始正面图

Reference Set v2
- 原始正面图（保留）
- 修订正面图
- 新增侧面眼部辅助图
- 新增左前 3/4 辅助图
- Comment #12：双眼向前突出
```

每个 Reference Set 应记录：

- 项目 ID
- 版本号
- 父 Reference Set
- 图片资产和明确视角角色
- 关联 Comments
- 创建者与创建时间
- 一致性检查结果
- 是否已锁定

Reference Set 一旦用于生成任务即锁定。后续修改必须创建新版本。

---

## 7. Hunyuan 使用边界

### 7.1 可以做

- 根据修订后的完整参考图集合重新生成候选模型。
- 将 Comment 整理为生成约束和验收依据。
- 生成后进入现有 Blender 精修与质量门禁流程。

### 7.2 不保证

- 只修改指定局部。
- 未选中的区域保持不变。
- 拓扑连续。
- UV 和材质连续。
- 身份特征一定改善。
- 每条 Comment 自动解决。

### 7.3 禁止的虚假状态

- 不得将 Hunyuan 完整重生成显示为“局部修改成功”。
- 不得在未进行人工复核时将 Comment 标记为 `resolved`。
- 不得使用模拟产物代替真实 Hunyuan 和 Blender 执行结果。

---

## 8. 数据模型建议

### 8.1 `version_comments`

```text
id
project_id
version_id
number
title
description
category
severity
status
recommended_route
mesh_name
position_json
normal_json
camera_snapshot_json
screenshot_path
created_at
updated_at
closed_at
```

### 8.2 `comment_replies`

```text
id
comment_id
author_type
body
attachments_json
created_at
```

### 8.3 `reference_sets`

```text
id
project_id
number
parent_reference_set_id
status
consistency_report
created_at
locked_at
```

### 8.4 `reference_set_assets`

```text
id
reference_set_id
asset_id
view_role
purpose
source_comment_id
created_at
```

### 8.5 `revision_requests`

```text
id
project_id
source_version_id
output_version_id
reference_set_id
status
route
config_snapshot
created_at
started_at
completed_at
error_summary
```

### 8.6 `revision_comment_links`

```text
id
revision_request_id
comment_id
source_version_id
output_version_id
result_status
result_notes
created_at
reviewed_at
```

---

## 9. API 建议

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

### Reference Sets

```text
POST   /api/projects/{projectId}/reference-sets
GET    /api/projects/{projectId}/reference-sets
GET    /api/reference-sets/{referenceSetId}
POST   /api/reference-sets/{referenceSetId}/assets
POST   /api/reference-sets/{referenceSetId}/validate
POST   /api/reference-sets/{referenceSetId}/lock
```

### Revision Requests

```text
POST   /api/revisions/plan
POST   /api/revisions
GET    /api/revisions/{revisionId}
POST   /api/revisions/{revisionId}/cancel
POST   /api/revisions/{revisionId}/retry
POST   /api/revisions/{revisionId}/comments/{commentId}/review
```

---

## 10. V1 实施范围

V1 必须完成：

1. 在版本验收页创建多条独立 Comments。
2. 每条 Comment 具有类型、严重程度、描述和独立状态。
3. 在 3D 模型表面添加编号标记点。
4. 保存 Comment 创建时的相机快照和截图。
5. Comment 支持独立回复线程。
6. Comment 支持上传修订设计图和辅助参考图。
7. 支持选择多条 Comments 创建修订计划。
8. 创建不可覆盖的 Reference Set 新版本。
9. 对参考图片的视角角色和最低完整性进行检查。
10. 使用新的 Reference Set 真实调用 Hunyuan，生成独立候选版本。
11. 候选版本真实执行现有 Blender 自动精修和质量门禁。
12. 展示源模型与候选模型、源四视图与候选四视图对比。
13. 每条关联 Comment 独立复核为已解决、部分解决、未解决或产生新问题。
14. 未经用户复核，不得自动关闭 Comment。
15. 原模型、原参考图和历史 Comments 保持不变。

V1 暂不包含：

- AI 自动修改原始设计图。
- 浏览器内复杂涂抹、箭头和自由绘制工具。
- Hunyuan 精确局部网格编辑。
- 自动身份相似度判定。
- 自动把自然语言转换为任意 Blender 局部雕刻操作。
- 专业级局部重拓扑、骨骼和动画修复。

---

## 11. V1 验收标准

1. 用户可以在一个版本上连续创建至少三条独立 Comments，而不是写入一个总意见框。
2. 保存 Comment 后停留在版本验收页面，并保留当前视角。
3. 点击 Comment 可恢复对应相机视角并定位模型标记。
4. 每条 Comment 可独立回复、关闭和重新打开。
5. 用户可为 Comment 上传修订正面图、侧面图或 3/4 辅助图。
6. 用户可选择部分 Comments 创建修订任务，未选择项不受影响。
7. 修订确认页准确区分 Blender 自动、参考图重生成、人工和未配置能力。
8. Reference Set 创建新版本且不会覆盖原始图片。
9. 后端真实调用 Hunyuan 生成新的候选 GLB。
10. 候选 GLB 进入真实 Blender 自动精修、四视图渲染和质量门禁。
11. 新模型创建独立版本，并记录源版本、Reference Set、修订任务和 Comments 关系。
12. 页面可以并排查看源版本和候选版本。
13. 任务成功后 Comments 进入 `awaiting_review`，不会自动显示为已解决。
14. 用户可以逐条选择已解决、部分解决、未解决或产生新问题。
15. 自动化测试覆盖 Comment 创建、回复、选择、Reference Set 版本化、任务成功、失败、取消和逐条复核。
16. 使用真实项目完成至少一次“修改参考图 → Hunyuan 重生成 → Blender 精修 → Comment 复核”的本地冒烟测试。
17. 前端构建和后端测试全部通过。

---

## 12. 推荐实施顺序

### 阶段 A：Comment 基础闭环

- 数据表和 API。
- Comments 列表、详情和回复。
- 3D 标记点、相机快照和截图。
- 状态流转和筛选。

### 阶段 B：Reference Set

- 修订图上传。
- 视角角色管理。
- Reference Set 版本化、验证和锁定。
- Comment 与参考资产关联。

### 阶段 C：Hunyuan 候选重生成

- 修订计划确认页。
- 真实 Hunyuan 后台任务。
- 候选版本派生关系。
- 接入现有 Blender 自动精修与门禁。

### 阶段 D：逐条复核

- 源版本与候选版本对比。
- Comment 视角恢复。
- 逐条解决状态和回复。
- 未解决项进入下一轮修订。

---

## 13. 下一次对话可直接使用的执行指令

> 按 `design/COMMENT_REFERENCE_REGENERATION_V1_PLAN.md` 落地 Comment 驱动的参考图修订与 Hunyuan 候选重生成 V1。一个 Comment 只能描述一个问题；保存 Comment 后留在版本验收页；只有用户选择 Comments 并确认后才创建 Reference Set 和修订任务。Hunyuan 必须真实执行并生成独立候选版本，不得宣称精确局部修改，不得覆盖源版本、源参考图或历史 Comment。候选版本必须继续执行真实 Blender 自动精修和质量门禁，完成后由用户逐条复核 Comment。持续执行至验收标准完成，无法通过代码、环境检查或安全本地替代方案解决的实际阻断必须准确说明。
