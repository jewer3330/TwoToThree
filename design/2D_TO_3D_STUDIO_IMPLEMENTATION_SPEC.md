# 2D→3D Studio 网站落地说明

> 文档类型：产品逻辑、UI 规范与技术实施说明  
> 当前版本：v1.0  
> 适用阶段：内部单机/局域网 MVP  
> 设计稿目录：[`design/`](./README.md)

---

## 1. 项目目标

将当前本地 2D→3D 工作流包装为可追踪、可检查、可返工的网页生产工作台。

用户可以：

1. 创建转换任务并上传正面、侧面、背面等参考素材；
2. 在转换前查看自动素材检查结果和近似风险；
3. 确认系统选择的生成路线、质量目标和交付内容；
4. 查看后台几何生成、Blender 渲染及网页优化进度；
5. 在浏览器中多角度检查 GLB；
6. 确认交付，或针对具体视角、区域和部件提交返工。

MVP 的“转换完成”定义为：

- 输出 GLB 可以正确解析；
- 模型可在 Three.js 中稳定加载；
- 正面、左 3/4、侧面和背面均能正常渲染；
- 模型没有明显平面坍塌或缺失主体；
- 几何、文件和生成参数有完整记录；
- 用户完成最终人工验收。

MVP 不承诺自动完成高精度 Blender 雕刻、准确隐藏面恢复、自动骨骼或任意类别的统一重建。

---

## 2. 当前工作流映射

### 2.1 默认路线

```text
上传素材
→ 素材技术检查
→ 用户确认生成方案
→ Hunyuan3D 2.1 生成几何 GLB
→ GLB 完整性检查
→ Blender 标准化与四视图渲染
→ 自动/人工视觉检查
→ 可选分件与局部修正
→ 可选参考图投射与材质处理
→ 网页资产优化
→ Three.js 预览与验收
```

### 2.2 后端降级路线

```text
Hunyuan3D 失败或资源不足
→ Stable Fast 3D
→ 仍失败时使用 TripoSR
→ 三条路线均失败则任务进入 failed 或 needs_input
```

降级必须记录真实后端，禁止以备用模型输出冒充 Hunyuan3D 输出。

### 2.3 自动与人工边界

可以自动执行：

- 文件接收、命名、哈希和归档；
- 解码、尺寸、重复素材、主体完整性等基础检查；
- 模型推理；
- GLB 文件头、解析、包围盒和几何统计；
- Blender 后台导入、标准化、四视图渲染和导出；
- Three.js 预览资产发布；
- 任务状态、日志、版本及产物记录。

必须保留人工判断：

- 多张图片是否确实属于同一角色；
- 大轮廓、服装层次和身份特征是否可接受；
- 隐藏区域推断是否合理；
- Blender 局部修形和真实分件边界；
- 最终交付验收。

---

## 3. 用户角色

### 3.1 制作用户

- 创建和管理自己的任务；
- 上传、替换或补充素材；
- 确认转换方案；
- 查看任务状态、日志和中间产物；
- 预览、下载、验收或发起返工。

### 3.2 管理员/技术人员

- 查看全部任务和 GPU 队列；
- 查看推理、Blender 和存储环境；
- 手动重试、取消或转入人工处理；
- 上传人工修正版；
- 管理模型版本和任务产物。

MVP 可以不实现登录，将当前本机用户视为管理员；数据结构仍需预留 `ownerId`。

---

## 4. 信息架构

主导航：

```text
工作台
项目管理
素材管理
任务队列
模型/资产库
版本管理
渲染管理
系统设置
```

MVP 必须实现：

- 工作台；
- 创建任务；
- 任务详情；
- 任务执行监控；
- 3D 预览与验收；
- 简化版系统状态。

其余入口可以隐藏或显示“后续开放”，不要提供无功能按钮。

---

## 5. 全局 UI 设计规范

### 5.1 视觉方向

- 风格：专业、克制、工业化创作工具；
- 背景：深石墨黑；
- 面板：略亮于背景，使用细边框建立层次；
- 主强调色：青蓝到紫色；
- 成功：绿色；
- 警告/等待确认：黄色；
- 失败/阻断：红色；
- 禁用/待执行：中性灰。

### 5.2 页面骨架

```text
┌──────────────────────────────────────────────────────┐
│ 顶栏：项目、搜索、环境状态、用户                     │
├──────────┬────────────────────────────┬──────────────┤
│ 主导航   │ 主内容/3D 视口             │ 状态/检查面板 │
│ 或阶段轴 │                            │              │
├──────────┴────────────────────────────┴──────────────┤
│ 可选底部操作栏：返回、保存、继续、验收               │
└──────────────────────────────────────────────────────┘
```

### 5.3 通用组件

- `AppShell`：全局侧栏和顶栏；
- `ProjectCard`：任务缩略图、阶段、状态和快捷操作；
- `StatusBadge`：状态徽标；
- `StageStepper`：阶段进度，不表示虚假线性百分比；
- `UploadSlot`：带素材角色的上传槽；
- `ValidationRow`：检查项、结果、证据和展开详情；
- `RiskNotice`：风险和近似说明；
- `PipelineDiagram`：转换路线；
- `RenderCard`：固定视角渲染结果；
- `LogViewer`：等宽字体、自动滚动和复制；
- `AssetCard`：文件、尺寸、哈希和下载；
- `ModelViewport`：Three.js 预览；
- `PartTree`：部件层级；
- `MetricBar`：可信度/匹配度显示；
- `DecisionPanel`：通过、有条件通过、不通过。

### 5.4 响应式要求

- 第一版优先支持 1440×900 及以上桌面屏幕；
- 1280px 宽度下允许右侧面板收起；
- 小于 1024px 显示“建议使用桌面端”，不要求完成移动端 3D 制作体验；
- 页面操作栏在滚动时保持可见；
- 3D 视口最低高度 560px。

---

## 6. 页面一：工作台/任务首页

设计参考：[`01-dashboard.png`](./01-dashboard.png)

### 6.1 页面目标

让用户快速判断哪些任务正在处理、等待输入、失败或已经完成，并进入对应下一步。

### 6.2 页面内容

- 顶部：搜索、系统健康、GPU/CPU/内存/存储摘要；
- 任务筛选：全部、处理中、等待中、已完成、异常；
- 显示模式：卡片/列表；
- 排序：更新时间、创建时间、状态；
- 任务卡片：
  - 缩略图；
  - 项目名称；
  - 实际生成后端；
  - 当前阶段；
  - 已通过阶段数；
  - 当前状态；
  - 更新时间；
  - 下一步按钮。

### 6.3 交互逻辑

- “新建项目”进入创建任务页；
- 点击卡片进入任务详情；
- `needs_input` 显示“补充素材”；
- `awaiting_confirmation` 显示“确认方案”；
- 处理中显示“查看进度”；
- `ready_for_review` 显示“开始验收”；
- `completed` 显示“查看结果”；
- `failed` 显示“查看错误”，不直接自动重试。

### 6.4 数据接口

```http
GET /api/projects?status=&query=&sort=&page=
GET /api/system/health
POST /api/projects
```

---

## 7. 页面二：创建任务与素材上传

设计参考：[`02-create-upload.png`](./02-create-upload.png)

### 7.1 页面目标

收集足够且具有明确语义的输入，不依靠文件名猜测正面、侧面或背面。

### 7.2 表单字段

必填：

- 项目名称；
- 正面主参考图；
- 主体类型：角色、物体、混合；
- 最终用途：网页展示、游戏、动画、英雄渲染；
- 质量等级：标准、高、超高。

推荐：

- 侧面；
- 背面；
- 左 3/4；
- 右 3/4。

高级素材：

- Base Color；
- Roughness；
- Normal；
- Metalness；
- Mask；
- 已有 GLB/Blend。

其他选项：

- 是否要求分件；
- 是否需要骨骼；
- 必须保持不变的特征；
- 补充说明。

### 7.3 文件规则

- 图片：PNG、JPG、JPEG、WebP；
- 单张不超过 20 MB；
- 最短边低于 256px 时阻断；256–1023px 有条件通过；推荐 1024px 以上，理想为 2048px；
- 正面图必须包含一个完整主体；
- 禁止将三视图拼图直接作为主输入；
- PBR 通道必须独立上传，禁止将 Base Color 自动复用为 Roughness、Normal 或 AO。

### 7.4 上传行为

1. 选择文件后立即计算客户端摘要信息；
2. 上传到任务临时目录；
3. 服务端重新计算 SHA-256；
4. 返回尺寸、格式、色彩空间和文件 ID；
5. 用户替换文件时保留旧文件记录但标记为未采用；
6. 自动保存草稿；
7. 点击“检查素材”后锁定当前上传版本并创建检查作业。

### 7.5 数据接口

```http
POST /api/projects
PATCH /api/projects/:projectId
POST /api/projects/:projectId/assets/init-upload
POST /api/projects/:projectId/assets/complete-upload
DELETE /api/projects/:projectId/assets/:assetId
POST /api/projects/:projectId/validate
```

---

## 8. 页面三：素材检查

设计参考：[`03-material-validation.png`](./03-material-validation.png)

### 8.1 检查项

- 文件可解码；
- 分辨率合格；
- 主体完整且未裁断；
- 仅有一个主要主体；
- 背景是否适合提取；
- 素材是否重复；
- 各图片的视角角色是否合理；
- 多视角主体是否一致；
- 正、侧、背覆盖率；
- 关键区域是否缺失。

### 8.2 检查结果

- `pass`：通过，可以继续；
- `conditional`：有条件通过，用户接受风险后继续；
- `request_input`：必须补充/替换素材；
- `reject`：素材不适合作为当前工作流输入。

### 8.3 风险展示规则

警告必须包含：

- 缺少什么证据；
- 哪些区域受影响；
- 系统将怎样近似；
- 可能产生什么视觉偏差。

示例：

> 背面覆盖不足。披风厚度、背包背面和后脑结构将按低置信度推断，可能导致侧后方轮廓与原设计不一致。

禁止只显示笼统的“图片质量较差”。

### 8.4 用户动作

- 返回补充素材；
- 接受近似并继续；
- 对阻断项只能补充素材，不能强行继续；
- 接受近似时写入用户确认记录。

### 8.5 数据接口

```http
GET /api/projects/:projectId/validation
POST /api/projects/:projectId/validation/accept-risks
POST /api/projects/:projectId/validate
```

---

## 9. 页面四：转换方案确认

设计参考：[`04-plan-confirmation.png`](./04-plan-confirmation.png)

### 9.1 页面目标

在消耗 GPU 资源前，让用户明确知道将运行什么路线、输出什么以及哪些区域只能近似。

### 9.2 显示内容

- 推荐主后端；
- 备用后端；
- 转换阶段图；
- 几何质量等级；
- 纹理分辨率；
- 目标三角面预算；
- 是否分件；
- 是否参考图投射；
- 是否需要骨骼；
- 输出列表；
- 必须保持一致的身份特征；
- 已知限制和近似；
- 高级参数。

### 9.3 默认参数建议

```json
{
  "primaryBackend": "hunyuan3d",
  "fallbackBackends": ["sf3d", "triposr"],
  "geometryQuality": "standard",
  "textureResolution": 2048,
  "targetTriangleRange": [60000, 120000],
  "segmentationRequired": false,
  "rigRequired": false,
  "preserveBaseline": true,
  "renderViews": ["front", "left-three-quarter", "side", "back"]
}
```

参数应根据设备显存和最终用途调整。RTX 4060 Ti 8GB 环境默认采用已验证的显存兼容设置。

### 9.4 确认逻辑

点击“确认并开始转换”后：

1. 保存不可变的 `jobConfig` 快照；
2. 记录素材 ID、哈希、后端、随机种子和模型版本；
3. 创建首个模型版本；
4. 将任务状态设置为 `queued`；
5. 进入执行监控页。

配置确认后不允许原地修改；修改必须创建新版本或新作业。

### 9.5 数据接口

```http
GET /api/projects/:projectId/plan
PATCH /api/projects/:projectId/plan
POST /api/projects/:projectId/jobs
```

---

## 10. 页面五：任务执行监控

设计参考：[`05-task-monitor.png`](./05-task-monitor.png)

### 10.1 页面布局

- 左侧：任务阶段时间线；
- 中间：当前阶段的四视图或中间产物；
- 右侧：当前阶段、耗时、GPU、显存、实时日志和输出文件；
- 底部：已通过阶段数。

### 10.2 标准阶段

```text
intake             素材接收
analysis           主体分析
geometry           几何生成
glb_validation     GLB 检查
multi_view_render  四视图渲染
visual_review      视觉评审
manual_refine      分件/人工修正（可选）
materials          材质处理（可选）
web_optimization   网页优化
```

### 10.3 阶段状态

- `pending`；
- `queued`；
- `running`；
- `passed`；
- `warning`；
- `failed`；
- `skipped`；
- `cancelled`。

页面显示“已通过 4/9 个阶段”，禁止根据耗时虚构整体百分比。

### 10.4 实时更新

MVP 推荐使用 SSE：

```http
GET /api/jobs/:jobId/events
```

事件类型：

```text
job.status
stage.started
stage.progress
stage.log
stage.output
stage.warning
stage.failed
stage.completed
job.completed
```

前端断线重连后使用最后事件 ID 续传；页面刷新后从 API 获取完整快照。

### 10.5 错误处理

- 显示用户可读错误摘要；
- 保留完整技术日志供管理员展开；
- 明确失败发生在哪一阶段；
- 明确是否可以重试；
- 重试必须创建新的 `attempt`；
- 后端降级时产生警告事件并记录实际模型；
- 取消任务不删除已生成产物。

### 10.6 数据接口

```http
GET /api/jobs/:jobId
GET /api/jobs/:jobId/stages
GET /api/jobs/:jobId/events
POST /api/jobs/:jobId/retry
POST /api/jobs/:jobId/cancel
GET /api/jobs/:jobId/artifacts
```

---

## 11. 页面六：3D 预览与验收

设计参考：[`06-preview-acceptance.png`](./06-preview-acceptance.png)

### 11.1 3D 视口功能

- OrbitControls 旋转、平移和缩放；
- 正面、侧面、背面、3/4 固定视角；
- 自动旋转；
- 彩色/灰模；
- 线框；
- 参考图叠加；
- 爆炸视图；
- 点击模型选择部件；
- 部件高亮；
- 截图；
- 背景和灯光环境切换。

### 11.2 真实性要求

- GLB 加载失败时必须显示明确错误；
- 禁止静默回退到占位模型；
- 页面必须显示当前真实文件名、版本和哈希；
- GLB 响应必须是正确 MIME 类型并包含 `glTF` 文件头；
- 基线版和修正版使用同一归一化、相机、灯光和色彩管理设置。

### 11.3 左侧面板

- 版本列表；
- 当前版本标识；
- 部件树；
- 部件显示/隐藏；
- 命名部件数量；
- 可选版本 A/B 切换。

### 11.4 右侧验收面板

- 轮廓匹配；
- 比例一致性；
- 正面可信度；
- 侧面可信度；
- 背面可信度；
- 顶点、面、三角面数量；
- 材质和贴图数量；
- 最大贴图尺寸；
- 文件大小；
- 已知差异；
- 近似区域和置信度。

自动分数只提供证据，不替代用户最终决定。

### 11.5 验收动作

#### 确认交付

- 状态变为 `completed`；
- 锁定当前交付版本；
- 生成交付清单；
- 允许下载 GLB、贴图、四视图和报告。

#### 有条件通过

- 用户必须填写备注；
- 状态可变为 `completed_with_notes`；
- 已知差异进入交付报告。

#### 标记问题并返工

返工单至少包含：

- 当前模型版本；
- 视角；
- 截图；
- 框选区域坐标；
- 可选部件 ID；
- 问题类别；
- 文字说明；
- 优先级。

返工创建新版本，禁止覆盖已验收或基线文件。

### 11.6 数据接口

```http
GET /api/projects/:projectId/versions
GET /api/versions/:versionId
GET /api/versions/:versionId/model
GET /api/versions/:versionId/parts
GET /api/versions/:versionId/quality-report
POST /api/versions/:versionId/accept
POST /api/versions/:versionId/accept-with-notes
POST /api/versions/:versionId/revisions
```

---

## 12. 任务状态机

### 12.1 项目/任务状态

```text
draft
uploading
validating
needs_input
awaiting_confirmation
queued
generating_geometry
validating_glb
rendering_review
quality_failed
awaiting_manual_refine
processing_materials
optimizing_web
ready_for_review
revision_requested
completed
completed_with_notes
failed
cancelled
```

### 12.2 主要流转

```text
draft
→ uploading
→ validating
→ needs_input → uploading
→ awaiting_confirmation
→ queued
→ generating_geometry
→ validating_glb
→ rendering_review
→ awaiting_manual_refine（可选）
→ processing_materials（可选）
→ optimizing_web
→ ready_for_review
→ completed / completed_with_notes
```

返工流转：

```text
ready_for_review
→ revision_requested
→ queued 或 awaiting_manual_refine
→ 新版本 ready_for_review
```

异常流转：

```text
任意执行阶段
→ failed
→ retry 创建新 attempt
```

状态变更只能由服务端执行，前端不能直接写最终状态。

---

## 13. 数据模型建议

### 13.1 Project

```ts
interface Project {
  id: string;
  slug: string;
  name: string;
  ownerId?: string;
  subjectType: 'character' | 'object' | 'hybrid';
  intendedUse: 'web' | 'game' | 'animation' | 'hero-render';
  status: ProjectStatus;
  thumbnailArtifactId?: string;
  createdAt: string;
  updatedAt: string;
}
```

### 13.2 Asset

```ts
interface Asset {
  id: string;
  projectId: string;
  role:
    | 'front'
    | 'side'
    | 'back'
    | 'left-three-quarter'
    | 'right-three-quarter'
    | 'base-color'
    | 'roughness'
    | 'normal'
    | 'metalness'
    | 'mask'
    | 'existing-model';
  originalName: string;
  storagePath: string;
  mimeType: string;
  byteSize: number;
  width?: number;
  height?: number;
  sha256: string;
  active: boolean;
  createdAt: string;
}
```

### 13.3 Job

```ts
interface Job {
  id: string;
  projectId: string;
  versionId: string;
  status: string;
  configSnapshot: JobConfig;
  requestedBackend: string;
  actualBackend?: string;
  modelVersion?: string;
  seed?: number;
  currentStage?: string;
  attempt: number;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  errorCode?: string;
  errorSummary?: string;
}
```

### 13.4 Artifact

```ts
interface Artifact {
  id: string;
  jobId: string;
  versionId: string;
  type: 'glb' | 'blend' | 'texture' | 'render' | 'report' | 'log' | 'comparison';
  label: string;
  storagePath: string;
  mimeType: string;
  byteSize: number;
  sha256: string;
  metadata: Record<string, unknown>;
  createdAt: string;
}
```

### 13.5 ValidationResult

```ts
interface ValidationResult {
  id: string;
  projectId: string;
  assetSnapshot: string[];
  verdict: 'pass' | 'conditional' | 'request_input' | 'reject';
  checks: Array<{
    code: string;
    label: string;
    status: 'pass' | 'warning' | 'fail';
    evidence: string;
    affectedRegions?: string[];
  }>;
  risks: Array<{
    code: string;
    message: string;
    consequence: string;
  }>;
  acceptedAt?: string;
}
```

---

## 14. 文件与版本目录

每个任务必须使用唯一 slug，禁止复用 YOYO 或 Field Commander 的文件名。

```text
data/
  projects/
    <project-id>/
      project.json
      assets/
        original/
        active/
      validation/
      versions/
        v001/
          job-config.json
          assessment.json
          detail-inventory.json
          object-sculpt-spec.json
          source/
          models/
            baseline.glb
            web.glb
          blender/
            baseline.blend
            working.blend
          textures/
          renders/
            front.png
            left-three-quarter.png
            side.png
            back.png
          reports/
          logs/
        v002/
```

规则：

- 基线 GLB 和 Blend 只读；
- 每次返工创建新版本；
- 每次重试创建新 attempt；
- 数据库保存逻辑路径，文件服务负责解析真实路径；
- 所有重要产物保存 SHA-256；
- 禁止通过用户输入直接拼接磁盘路径。

---

## 15. 系统架构建议

### 15.1 技术栈

- 前端：React + TypeScript + Vite；
- UI：CSS Modules 或 Tailwind CSS；
- 3D：Three.js 或 React Three Fiber；
- API：FastAPI；
- 数据库：MVP 使用 SQLite，生产版 PostgreSQL；
- 队列：Redis + RQ/Celery；
- 推理 Worker：Python；
- Blender Worker：Blender background CLI；
- 实时更新：SSE；
- 文件存储：MVP 本地磁盘，生产版 S3 兼容对象存储。

### 15.2 服务划分

```text
Web Frontend
    ↓ HTTP/SSE
API Service
    ├─ Database
    ├─ Local/Object Storage
    └─ Job Queue
          ├─ GPU Worker
          ├─ Blender Worker
          ├─ Quality Worker
          └─ Preview/Packaging Worker
```

### 15.3 并发原则

- RTX 4060 Ti 8GB 默认同一时间只运行一个 GPU 推理任务；
- Blender 渲染任务是否并发需根据显存/内存测试决定；
- 队列任务必须声明资源类型：`gpu`、`blender`、`cpu`；
- GPU Worker 任务完成后主动释放模型和 CUDA 缓存；
- 大文件上传不占用 GPU Worker。

---

## 16. 现有脚本工程化要求

在接入网页前，需要完成以下整理：

1. 将 `pipeline/config.json` 改为每个 Job 独立的配置快照；
2. 移除 YOYO 固定输入输出路径；
3. 所有脚本支持参数传入 `projectId`、`versionId`、输入和输出目录；
4. 所有阶段输出结构化 JSON 报告；
5. 进度信息以 JSON Lines 写入 stdout 或事件文件；
6. 区分用户错误、环境错误、资源不足和模型错误；
7. 统一 UTF-8 编码并修复现有中文乱码；
8. 禁止脚本覆盖 baseline；
9. 记录后端、模型版本、权重摘要、随机种子和命令参数；
10. 脚本退出码必须可靠：`0` 成功，非 `0` 失败；
11. 中途失败时保留日志和可诊断产物；
12. Blender 脚本必须支持无 UI 后台运行。

推荐统一阶段报告：

```json
{
  "schemaVersion": 1,
  "stage": "multi_view_render",
  "status": "passed",
  "startedAt": "2026-08-13T10:00:00+08:00",
  "completedAt": "2026-08-13T10:03:20+08:00",
  "inputs": [],
  "outputs": [],
  "metrics": {},
  "warnings": [],
  "error": null,
  "nextAction": "visual_review"
}
```

---

## 17. 安全与稳定性

- 上传文件必须按 MIME 和实际文件内容双重验证；
- 文件名只作为展示信息，不作为磁盘路径；
- 阻止路径穿越和任意命令参数注入；
- 后端命令使用参数数组，不拼接用户文本；
- 限制图片、模型及压缩包大小；
- GLB 预览从专用文件服务读取；
- 日志中隐藏 Hugging Face Token 和其他密钥；
- 取消任务先发送终止信号，再由 Worker 清理自身子进程；
- 禁止自动删除原始素材和基线；
- 生产版需要身份认证、权限、审计日志和备份策略。

---

## 18. 性能目标

MVP 建议目标：

- 工作台首屏数据响应小于 1 秒；
- 任务状态事件延迟小于 2 秒；
- 20 MB 图片上传有明确进度；
- GLB 预览首屏模型建议小于 20 MB；
- 网页模型建议 60k–120k 三角面，按用途调整；
- 贴图默认 2K，必要时使用 4K；
- 预览桌面设备稳定达到 30 FPS 以上；
- 3D 视口加载失败在 10 秒内给出明确错误。

---

## 19. MVP 开发范围

### 19.1 必须交付

- 六个页面的可用前端；
- 本地项目和任务数据库；
- 分角色素材上传；
- 基础素材检查；
- 转换方案确认；
- 单 GPU 作业队列；
- Hunyuan3D 主路线；
- SF3D/TripoSR 备用路线；
- GLB 完整性检查；
- Blender 四视图自动渲染；
- 实时阶段状态和日志；
- Three.js GLB 预览；
- 固定视角、灰模和自动旋转；
- 模型统计和产物下载；
- 验收、备注和文字返工；
- 文件版本隔离。

### 19.2 可延期

- 多租户和计费；
- 云 GPU 调度；
- 全自动精细分件；
- 自动 Blender 雕刻；
- 自动骨骼和动画；
- 截图框选返工；
- 部件级爆炸视图；
- 自动 PBR 烘焙；
- 多人实时协作；
- 移动端制作界面。

---

## 20. 开发顺序与工期

### 第 1 周：基础工程和流水线整理

- 建立前后端项目结构；
- 设计数据库；
- 建立任务目录；
- 将现有脚本参数化；
- 统一报告和错误结构；
- 修复编码问题；
- 验证 Hunyuan、SF3D、TripoSR 和 Blender 环境。

### 第 2 周：创建任务与作业队列

- 完成工作台；
- 完成上传和草稿；
- 完成素材检查；
- 完成方案确认；
- 接入 Redis/Worker；
- 建立 SSE 事件流。

### 第 3 周：生成、检查和渲染

- 接入 Hunyuan3D；
- 接入备用后端；
- 实现 GLB 检查；
- 接入 Blender 四视图；
- 完成任务监控、日志、重试和取消。

### 第 4 周：预览验收与整体测试

- 完成 Three.js 预览；
- 完成视角、灰模和模型统计；
- 完成版本和下载；
- 完成验收与返工；
- 执行端到端测试；
- 完成局域网部署说明。

该工期建立在“单机/局域网、单用户优先、角色主流程、交付可验收 GLB”的范围内。

---

## 21. 验收标准

### 21.1 创建与上传

- 可创建唯一项目；
- 可为每个视角独立上传或替换素材；
- 刷新页面后草稿不丢失；
- 相同文件可以检测为重复素材；
- 非法格式和超限文件被明确拒绝。

### 21.2 素材检查

- 每项结果包含状态和证据；
- 阻断项不能强行进入生成；
- 有条件通过必须记录用户确认；
- 修改素材后旧检查结果自动失效。

### 21.3 后台执行

- 用户关闭页面不会终止任务；
- 刷新后可以恢复最新状态；
- 日志持续可见；
- 失败阶段明确；
- 重试不会覆盖上一次产物；
- 实际使用的生成后端可追踪。

### 21.4 预览

- GLB 可以真实加载；
- 加载失败不显示占位模型；
- 固定视角正确；
- 彩色和灰模切换可用；
- 模型统计来自当前文件；
- 当前版本、文件名和哈希一致。

### 21.5 验收与返工

- 用户可以通过、有条件通过或发起返工；
- 返工关联具体模型版本；
- 已完成版本不可被覆盖；
- 下载包包含模型、预览图和报告。

---

## 22. 开工前必须确认的产品决定

第一版默认按以下范围实施：

- 部署：当前 Windows 工作站或局域网；
- 用户：单用户/管理员；
- 支持对象：先支持单个完整角色；
- 主输入：正面必填，侧面和背面推荐；
- 主后端：Hunyuan3D 2.1；
- 输出：可验收网页 GLB、四视图和报告；
- 精修：保留人工 Blender 环节；
- 骨骼：第一版不作为完成条件；
- 分件：可选人工阶段，不承诺全自动；
- 数据：全部保存在本地任务目录。

若改为公网、多用户、对象与角色全类别、自动分件、自动骨骼或云 GPU，需重新评估架构和工期。

---

## 23. 最终交付物

MVP 完成时应包含：

- 前端网站；
- FastAPI 服务；
- 数据库迁移；
- GPU/Blender Worker；
- 作业队列；
- 统一任务配置和阶段报告；
- 本地文件存储结构；
- Three.js 模型验收页；
- 安装、环境检查、启动和故障排查文档；
- 至少一个完整示例任务；
- 自动化测试和人工验收清单。
