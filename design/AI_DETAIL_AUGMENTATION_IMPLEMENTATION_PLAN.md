# AI 细节补充流程落地计划

> 文档类型：工程实施计划  
> 状态：待实施  
> 目标版本：v1 受控 MVP  
> 依赖：素材管理、Reference Set、本地 ComfyUI、Hunyuan3D-2mv、Blender 精修、评审页面

## 1. 目标与非目标

### 1.1 目标

在三视图素材完成上传和技术检查后，自动识别细节不足的语义区域，生成可追溯的补图计划和多视角候选组。只有用户批准的候选才能进入新的 Reference Set，并按几何、法线/置换或材质用途参与后续流程。

### 1.2 非目标

- 不承诺从不可见区域恢复真实结构。
- 不把 AI 推断图标记为原始素材。
- 不通过单纯超分辨率或网格细分宣称几何精度提高。
- v1 不自动接受候选，不进行完全无人值守的模型重生成。
- v1 不修改 Hunyuan3D-2mv 的模型结构或任意扩展其输入视角数量。
- v1 不自动完成生产级重拓扑。

## 2. 用户流程

```text
创建项目并上传素材
→ 素材校验通过
→ 进入“AI 细节规划”
→ 查看区域覆盖图和风险
→ 选择区域、模式及候选数量
→ 启动补图任务
→ 按候选组进行对比审批
→ 创建 Reference Set 新版本
→ 确认实际送入几何模型的视图
→ 生成粗模
→ 重投影差异检查
→ 创建局部精修任务
```

页面路径建议：

```text
/detail-plans/:projectId
/detail-jobs/:jobId
/detail-review/:jobId
```

面包屑统一为：

```text
首页 → 项目管理 → AI 细节规划/生成任务/候选确认
```

## 3. 页面设计

### 3.1 AI 细节规划页

左侧展示原始正、侧、背视图及切换控件；中间显示语义区域覆盖图；右侧显示当前区域的证据、建议动作、目标视角、目标用途和风险。

每个区域至少显示：

- 区域名称和稳定 ID；
- 原始可见视角；
- 遮挡及清晰度；
- 证据等级；
- 建议生成视角；
- `geometry`、`normal_displacement` 或 `material` 用途；
- 低、中、高风险；
- 是否选择生成；
- 选择保守、平衡或创作模式。

### 3.2 生成监控页

显示区域队列、当前候选组、GPU 阶段、实际 Provider、模型、seed、重绘强度、输入资产和失败原因。ComfyUI、Hunyuan 和 Blender 继续使用串行 GPU 队列。

### 3.3 候选确认页

候选必须按多视角组展示。用户可以批准整组、拒绝整组或用修改后的约束重试。界面同时显示原始裁切、生成候选和差异叠加，明确标注推断区域。

批准时需要展示：

- 哪些图片进入新 Reference Set；
- 它们的证据等级；
- 它们将影响几何、法线还是材质；
- 哪些视图会被当前 Hunyuan runner 实际消费；
- 哪些图片仅供 Blender 局部精修使用。

## 4. 区域与证据模型

### 4.1 v1 区域枚举

```text
head
face
hair
neck_collar
torso_garment
left_shoulder_sleeve
right_shoulder_sleeve
arms_hands
lower_body
back_structure
accessories
```

### 4.2 证据等级

```text
observed     原始图片直接可见，仅裁切/增强
constrained  根据两个或更多真实视角受约束推导
inferred     对遮挡或不可见区域进行模型推断
designed     用户明确允许的创造性补充
```

### 4.3 细节用途

```text
geometry             轮廓、体积、厚度、包裹关系和明显凸起
normal_displacement  浅褶皱、缝线、皮肤和布料细微起伏
material             颜色、印花、眉毛、妆容、粗糙度和光泽
```

一个细节可以有多个用途，但必须指定主用途。系统不得把仅有颜色证据的阴影自动转换为几何位移。

## 5. 数据结构

### 5.1 `detail_plans`

```text
id
project_id
source_reference_set_id
status: analyzing | awaiting_confirmation | confirmed | superseded | failed
mode: conservative | balanced | creative
analyzer_version
summary_json
created_at
confirmed_at
```

### 5.2 `detail_regions`

```text
id
detail_plan_id
region_key
mask_asset_id
visible_views_json
coverage_score
clarity_score
consistency_score
evidence_level
target_usage
risk_level
recommended_views_json
constraints_json
selected
```

### 5.3 `detail_generation_jobs`

```text
id
detail_plan_id
status: queued | generating | awaiting_approval | completed | failed | cancelled
provider
model
workflow_version
seed
parameters_json
started_at
finished_at
error_code
error_message
```

### 5.4 `detail_candidate_groups`

```text
id
job_id
region_id
group_index
status: draft | approved | rejected
evidence_level
target_usage
consistency_metrics_json
reviewed_at
review_note
```

每个候选图片继续作为普通资产保存，并通过关系表关联候选组、目标视角、相机参数、源图、蒙版和哈希。批准操作创建新的 Reference Set 和资产关系，不覆盖任何原始文件。

## 6. API 草案

```text
POST /api/projects/{projectId}/detail-plans
GET  /api/detail-plans/{planId}
PATCH /api/detail-plans/{planId}/regions/{regionId}
POST /api/detail-plans/{planId}/confirm

POST /api/detail-plans/{planId}/jobs
GET  /api/detail-jobs/{jobId}
POST /api/detail-jobs/{jobId}/cancel
POST /api/detail-jobs/{jobId}/retry

POST /api/detail-candidate-groups/{groupId}/approve
POST /api/detail-candidate-groups/{groupId}/reject
POST /api/detail-candidate-groups/{groupId}/regenerate
```

`approve` 的响应必须返回新 Reference Set ID、实际新增资产、证据等级和后续可消费阶段。审批和 Reference Set 创建必须在同一事务中完成。

## 7. 生成实现

### 7.1 区域分析

v1 采用可解释的组合策略：人体/服装语义分割、关键点检测、原始图清晰度统计和跨视图规则。大模型可以生成文字建议，但不能单独决定区域边界或证据等级。

### 7.2 候选生成

沿用本地 `ComfyUI Local API`。输入包括：

- 原始完整视图及区域裁切；
- 区域蒙版；
- 角色身份与服装保持约束；
- 目标相机方向；
- 固定 seed；
- 模式对应的重绘强度；
- 负面约束；
- 模型和工作流版本。

建议初始参数：

| 模式 | Denoise 建议 | 行为 |
|---|---:|---|
| 保守 | 0.15–0.25 | 最大限度保持原图 |
| 平衡 | 0.20–0.35 | 补充有限视角和遮挡细节 |
| 创作 | 0.35–0.55 | 允许明显结构推断，必须高风险标记 |

每个区域默认生成 2 个候选组，上限 4 组。显存不足时降低分辨率或串行生成，不静默更换模型。

### 7.3 一致性检查

自动门禁至少包括：

- 人脸身份特征相似度；
- 关键点和轮廓跨视图一致性；
- 服装主色和装饰数量一致性；
- 左右结构是否发生无依据变化；
- 输出是否超出蒙版；
- 是否出现额外肢体、五官或配件；
- 目标相机方向是否符合计划。

自动检查只负责阻断明显错误，不代替人工批准。

## 8. 下游路由

### 8.1 几何生成

Reference Set 必须区分“已批准资产”和“当前后端实际输入”。对于 Hunyuan3D-2mv，继续使用其支持的正面、左侧、背面键。额外 45° 或局部图默认不直接送入 runner，除非后端接口明确支持。

### 8.2 Blender 局部精修

粗模生成后按固定相机渲染，与批准细节图比较。几何用途的区域可生成局部雕刻规格、约束位移、独立补片或局部重建任务。禁止为了局部细节默认执行全身细分、全局平滑或全局 Remesh。

### 8.3 法线和材质

浅表细节进入法线或置换烘焙；颜色和材质细节进入纹理投射与 PBR 生成。系统需要记录每项最终细节的来源资产和处理阶段。

## 9. 状态与调度

```text
asset_validation
→ detail_analysis
→ detail_generation
→ detail_approval
→ hunyuan_generation
→ geometry_confirmation
→ blender_refinement
→ render_review
```

GPU 阶段严格串行：

```text
image_detail_generation → hunyuan_generation → blender_refinement → render_review
```

CPU 区域分析和文件检查可以并行，但不得与数据库审批事务解耦。

## 10. 验收标准

### 10.1 功能验收

- 三视图校验通过后可以创建细节计划。
- 系统能输出固定区域、覆盖度、用途和风险。
- 用户可以取消区域或调整模式。
- 每个候选可追溯到源图、蒙版、模型、seed 和参数。
- 只能按候选组批准，不产生跨组视图拼接。
- 未批准候选不能进入 Reference Set 或下游任务。
- 批准后原始 Reference Set 保持不变，并创建新版本。
- 界面准确展示 Hunyuan 实际消费的视图。
- 失败、取消和重试不会留下可被误用的半成品。

### 10.2 质量验收

- 原始三视图与候选组可并排比较。
- 面部候选没有明显身份漂移、五官增减或左右矛盾。
- 衣服候选没有无依据改变主色、层数和配件数量。
- 几何用途候选不依赖单一视图中的光影判断凹凸。
- 生成后的粗模仍需通过薄片、破面、粘连和多角度视觉门禁。
- 细节提升以固定相机 A/B 对比验证，不以图片分辨率或模型面数作为成功指标。

### 10.3 可追溯性验收

- 原始资产、候选资产和批准资产的哈希完整。
- Reference Set 版本链可查询和回退。
- 每次审批记录用户、时间和说明。
- 生成参数、模型版本和工作流版本可复现。
- 最终几何、法线和材质可以追溯到对应证据资产。

## 11. 分阶段实施

### Phase 1：数据与静态规划

1. 增加数据库表和迁移。
2. 增加区域枚举、证据等级和用途类型。
3. 实现基于规则的细节计划生成。
4. 完成规划页和确认交互。
5. 使用固定测试数据验证 Reference Set 不可变性。

完成条件：无需调用生成模型即可走通计划创建、编辑和确认。

### Phase 2：本地候选生成

1. 建立 ComfyUI 区域工作流。
2. 实现生成任务、串行 GPU 调度和进度记录。
3. 保存候选组、蒙版、参数和预览图。
4. 实现失败、取消和重试。

完成条件：至少面部、衣领和肩袖三个区域可生成真实候选组，不使用模拟结果。

### Phase 3：审批与 Reference Set

1. 实现候选对比页面。
2. 实现整组批准/拒绝。
3. 审批事务中创建新 Reference Set。
4. 阻止未批准资产进入下游。

完成条件：完整通过原始素材到新 Reference Set 的审计测试。

### Phase 4：几何与精修接入

1. 显示 Hunyuan 实际输入映射。
2. 生成粗模并保存固定相机渲染。
3. 建立批准细节图与模型渲染的区域差异任务。
4. 将差异转成 Blender 局部精修规格。

完成条件：一个真实项目完成“补图—批准—粗模—局部精修—A/B 评审”闭环。

### Phase 5：质量评估与参数固化

1. 建立包含清晰、模糊、遮挡和视图冲突的测试集。
2. 比较关闭/开启细节补充时的轮廓、关键点、身份和结构结果。
3. 固化各区域默认蒙版范围和模式参数。
4. 记录失败模式和请求用户补图的阈值。

完成条件：证明该流程在目标样本上提高可验收细节，同时没有显著增加身份漂移和结构幻觉。

## 12. 首个验证样本建议

使用当前最高精度人物模型对应的原始三视图作为首个样本，优先验证：

1. 面部正面与左右 45° 候选组；
2. 颈部和衣领结构；
3. 左右肩袖分层及粘连关系；
4. 发髻侧后方体积；
5. 胸前服装结构。

每个区域分别对比原始粗模和启用补图后的结果。若补图提高了局部视觉丰富度但降低人物相似度、轮廓一致性或结构可信度，则该区域判定为失败，不进入默认流程。
