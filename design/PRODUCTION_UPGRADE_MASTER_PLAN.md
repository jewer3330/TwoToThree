# 2D→3D Studio 生产升级总规划

状态：待实施  
目标读者：后续实施 AI、开发及运维人员  
优先级：传输止损 > 登录保护 > GPU 原生直传 > 打印闭环 > 纹理精修  
硬约束：主控只有公网 IPv6；公网 IPv4 经 Cloudflare 代理；大模型不得经过 CDN、Cloudflare、DERP 或其他中转。

## 1. 现状与目标

当前综合完成度约 5/10：已有 2D→3D、GPU 调度、Blender、版本验收和打印页面骨架，但尚非可靠生产系统。

- GPU 阶段产物会在 GPU、主控、CDN/upload 中转之间反复搬运，传输失败常被表现为“没有生成模型”。
- `blender_auto_refine.py` 对每个 Mesh 分别铺满整张参考图，造成截图中的重复错贴。
- 打印模块主要是 Bambu LAN 状态读取，缺少可靠切片、下发、幂等与任务闭环。
- 用户系统暂不作为重点，只实现保护 GPU/打印操作所需的最低权限。

目标架构：

```text
浏览器 → 主控 API/数据库/资产存储
                    │
                    ├─ SSH：小命令、日志、探测
                    └─ 原生 IPv6 HTTPS：输入及最终产物直传
                                      │
                                      ▼
                                GPU2 Job Runner
                    预处理→生成→Blender→渲染→质检
                                      │
                                      └─ manifest + 最终产物一次回传

主控：验收版本→打印检查→切片/3MF→打印 Provider→打印状态机
```

原则：一次下发、计算全程驻留 GPU、一次回传。禁止用“增加超时”代替架构修复；直连失败不得静默回退中转。

## 2. P0：修复现有传输错误（1～2 天）

主要文件：`server/backends.py`

1. `_remote_exists()` 无法检查时抛出异常，禁止返回 `True`。
2. 三种 download 方法统一传输接口和错误类型。
3. 下载完成检查文件长度、SHA-256；GLB 还要验证头部及结构可解析。
4. 远端 `cleanup()` 只能在主控返回 `artifact_committed` 后执行。
5. GPU 产物默认保留 48 小时，由定时任务清理。
6. 区分 `COMPUTE_FAILED`、`TRANSFER_FAILED`、`CHECKSUM_MISMATCH`、`COMMIT_FAILED`。
7. 传输失败只重传产物，不重新运行推理。
8. 将传输状态持久化，主控重启后可以恢复。

验收：中断下载后进入 `transfer_pending`；GPU 文件仍在；恢复后续传；篡改一个字节必须触发校验错误；不重复占用 GPU。

## 3. P1：验证原生 IPv6 直连（半天）

### 3.1 必要条件

- GPU2 网络具有 IPv6 出站能力。
- 主控地址是全局单播 IPv6，不是 `fe80::/10`。
- 主控路由器 IPv6 防火墙允许指定入站端口。
- macOS 防火墙允许传输服务。
- 服务实际监听 `[::]:443` 或指定端口。

只有主控有 IPv6而 GPU2 只有 IPv4/CGNAT 时，在“不使用中转”的约束下无法互通。此时任务必须保留 GPU 产物并进入 `DIRECT_PATH_UNAVAILABLE`，等待网络条件恢复；不得走 Cloudflare upload 或 DERP。

### 3.2 DNS、TLS和测试

- 新建 `transfer6.example.com`，只配置 AAAA。
- Cloudflare 记录设为 DNS Only，禁止代理。
- 家庭 IPv6 前缀变化时用 DDNS 更新 AAAA。
- 使用 ACME DNS-01 申请 TLS 证书。
- 普通 Web 域名继续走 Cloudflare；传输域名独立。

GPU2 PowerShell：

```powershell
Resolve-DnsName transfer6.example.com -Type AAAA
Test-NetConnection transfer6.example.com -Port 443
curl.exe -6 -v https://transfer6.example.com/health
```

验收：关闭 Tailscale 和原 upload 中转后，GPU2 连续 100 次健康请求成功率不低于 99%；100MB 文件上传 10 次全部 SHA-256 一致；主控日志显示 GPU2 原生 IPv6来源地址。

## 4. P2：IPv6 分块直传服务（3～5 天）

优先在主控宿主机部署轻量服务，再把已提交文件原子移动到数据卷；先避免 Docker Desktop IPv6带来的额外变量。

建议采用 tus，或实现最小 API：

```text
POST   /v1/transfers
HEAD   /v1/transfers/{id}
PATCH  /v1/transfers/{id}
POST   /v1/transfers/{id}/commit
GET    /health
```

要求：

- 8～32MB 分块，支持偏移查询和断点续传。
- 数据先写 `.part`；commit 时校验长度和 SHA-256，`fsync` 后原子改名。
- `job_id + attempt + artifact_name + sha256` 幂等。
- 每台 GPU 独立凭据，推荐 mTLS；简化版可用短时 HMAC/JWT。
- Token 绑定任务、文件名、长度、哈希和过期时间；GPU 不得指定任意路径。
- 限制文件大小、并发和总磁盘；清理过期 `.part`。
- 输入也由 GPU2 从同一 IPv6服务使用签名 URL和 Range 直接下载并校验。

禁止回退：

- 删除大文件的 GPU→Cloudflare upload→共享卷路线。
- 禁止大文件自动回退 Tailscale DERP SCP。
- SSH/SCP仅允许默认小于 1MB 的日志与诊断文件。
- 直连不可用时进入等待状态并告警。

## 5. P3：整任务驻留 GPU2（5～8 天）

新增建议：

```text
pipeline/gpu_job_runner.py
server/transfer/routes.py
server/transfer/service.py
server/transfer/models.py
server/transfer/verifier.py
```

主控只发送 `job-spec.json`、参考图、必要配置及输入 SHA-256。GPU2 在同一目录完成：输入校验→条件图→Hunyuan→Blender 清理/精修→四视图→GLB/打印检查→manifest→一次提交。

Manifest 示例：

```json
{
  "schemaVersion": 1,
  "jobId": "job_xxx",
  "attempt": 1,
  "state": "ready_to_transfer",
  "artifacts": [
    {"name": "model.glb", "kind": "glb", "size": 32500123, "sha256": "..."}
  ]
}
```

Manifest 最后生成，文件仍在写入时不得进入 `ready_to_transfer`。

状态机：

```text
queued → dispatched → input_transfer → computing → ready_to_transfer
→ transferring → verifying → committed → completed

异常：compute_failed / transfer_pending / transfer_failed /
      verification_failed / direct_path_unavailable / cancelled
```

只有 `committed` 后项目版本才能展示为可验收。验收要求：大文件严格一次下发、一次回传；任意一侧重启可恢复；中断五次仍续传同一文件；GPU committed 后仍保留 48 小时。

## 6. P4：Blender 贴图错位专项修复（3～7 天）

主要文件：

- `pipeline/blender_auto_refine.py`
- `server/main.py`
- `server/backends.py`
- `src/pages/RefinementConfigPage.tsx`
- 新增建议：`pipeline/blender_texture_projection.py`
- 新增建议：`tests/test_refinement_texture_contract.py`

### 6.1 已确认根因

当前 `front_reference_projection` 不是严格的相机投射，而是对每个 Mesh 分别计算自己的世界坐标 X/Z 包围盒，再将完整参考图映射到该 Mesh 的 0～1 UV。结果是帽子、脸、围巾、衣服、鞋子各自重复一张完整人物图，形成截图中的重影和错贴。

同时存在以下问题：

1. 修改活动 UV，破坏源模型已有的正确 UV。
2. 清空每个对象的原材质槽，并统一替换成 `AutoRefine_PBR`。
3. 将参考图强制缩放为正方形，改变原始宽高比。
4. 没有相机内外参、角色构图区域和透明边界标定。
5. 没有深度缓冲、遮挡判断、背面剔除或法线夹角权重。
6. 单张正面图被用于侧面和背面，属于无证据填充。
7. 当前 `uvValid` 只验证数值位于 0～1，无法发现重复铺图、重叠、拉伸或语义错位。
8. 减面、清理和投射没有建立“拓扑变化后必须重新烘焙或回退”的契约。

### 6.2 P4-A：立即止血（1 天）

目标：先保证精修不再破坏已有材质，允许几何精修独立上线。

1. 默认配置将 `referenceProjection` 设为关闭或 `preserve_materials`。
2. `preserve_or_smart` 策略下：有 UV 就保持不动；没有 UV 才生成新 UV。
3. 复制并保留源材质槽、纹理、UV 层名称和纹理颜色空间。
4. 无相机标定时，参考图仅作为视觉验收输入，不连接到 Base Color。
5. 不再用灰色五通道贴图覆盖已有 PBR；只给真正无材质对象补中性材质。
6. 输出报告增加 `materialsPreserved`、`uvPreserved`、`projectionSkippedReason`。
7. 若源 GLB 原有纹理无法随导出保留，则本次精修直接失败并回退源版本，不能输出“质量通过”。

P4-A 验收：

- 使用当前角色 GLB 精修后，材质槽数量、活动 UV 名称和主要纹理哈希与源模型一致。
- 正面、侧面、背面不再出现重复整图。
- 几何清理和安全减面仍可执行。
- 页面明确显示“保留源材质；未执行参考图投射”。

### 6.3 P4-B：建立独立且可回滚的纹理阶段（1～2 天）

几何、UV、纹理必须拆成独立阶段：

```text
source.glb
→ geometry-refined.glb
→ uv-candidate.blend/glb
→ texture-baked.glb
→ texture-quality-gate
→ refined.glb 或回退 geometry-refined.glb
```

要求：

- 每阶段保存输入、输出、配置、统计和 SHA-256。
- UV/纹理失败不得让几何精修结果丢失。
- 在临时 UV 层（如 `RefineProjectionUV`）操作，不覆盖源 UV。
- 烘焙成功且门禁通过后才把候选 UV/材质设为最终版本。
- 所有 Blender 操作只作用于任务集合，禁止误导出灯光、相机或隐藏辅助对象。

### 6.4 P4-C：正确的统一正面相机投射（2～3 天）

只有用户明确启用且参考图满足条件时才执行。

1. 对所有目标 Mesh 计算一个统一的角色世界包围盒，禁止逐 Mesh 归一化。
2. 保留参考图原始宽高比；根据主体 mask 计算有效构图区域。
3. 建立正交或透视相机，并把相机参数写入配置快照。
4. 用相机投影生成临时 UV；所有 Mesh 使用同一投影矩阵和图像坐标系。
5. 用深度缓冲或射线判断可见性，只给相机首层可见表面投射。
6. 使用 `dot(normal, view_direction)` 计算权重；掠射角和背向面不采纳正面图。
7. 参考图透明区、背景区和低置信区域不参与投射。
8. 将结果烘焙到新 Base Color Atlas；Mesh 不直接各自引用整张参考图。
9. 未覆盖区域优先保留源纹理；没有源纹理时使用明确标记的中性推断色。
10. Atlas 分辨率、边距、padding、色彩空间和纹素密度写入质量报告。

建议新增投射配置：

```json
{
  "projectionMode": "preserve|front_camera|multiview",
  "cameraType": "orthographic|perspective",
  "cameraMatrix": [],
  "subjectCrop": [0, 0, 1, 1],
  "visibilityThreshold": 0.98,
  "normalAngleLimitDeg": 70,
  "preserveUncoveredSource": true,
  "atlasResolution": 2048,
  "atlasPaddingPx": 16
}
```

### 6.5 P4-D：多视图融合（后续增强，2～4 天）

正面投射稳定后再做，不得与 P4-A 同批上线。

- 正面、左/右侧和背面分别标定相机。
- 每个纹素按可见性、法线夹角、清晰度和视图置信度加权。
- 重叠区做曝光/白平衡匹配和接缝羽化。
- 视图相互冲突时保留高置信来源并在报告中标记。
- 无证据区域不得伪装成参考图还原，应标记为保留或推断。

### 6.6 质量门禁

新增或强化以下指标：

- `sourceUvPreserved`：保留策略下必须为真。
- `sourceMaterialPreservationRate`：P4-A 应为 100%。
- `uvOutOfRangeRate`：应为 0，UDIM 模式除外。
- `uvOverlapRate`：排除允许镜像后低于阈值。
- `texelDensityVariation`：各主要部件不可相差过大。
- `projectionCoverageFront`：正面有效覆盖率。
- `backfaceProjectionRate`：应接近 0。
- `occludedProjectionRate`：应接近 0。
- `reprojectionErrorPx`：标志点或 mask 轮廓重投影误差。
- `seamColorDelta`：接缝两侧颜色差。
- `duplicateFullImageScore`：检测多个 Mesh 是否各自重复完整参考图。
- `rendersComplete`：正、侧、背、3/4 全部生成。

任何关键门禁失败：

```text
纹理候选 rejected
→ 保留 geometry-refined.glb + 源材质
→ 任务进入 awaiting_review 或 quality_failed
→ 禁止自动进入打印
```

### 6.7 自动化测试和视觉回归

至少准备四组固定资产：

1. 多 Mesh、有正确 UV/多材质角色。
2. 单 Mesh、有正确 UV角色。
3. 无 UV、无材质简单模型。
4. 有遮挡、披风、帽子和前后层叠的复杂角色。

自动测试：

- 精修前后对象数、材质槽、UV层、纹理引用和哈希契约。
- 正面图片不得在每个 Mesh 的 UV 中分别占满 0～1。
- 运行两次结果的配置、门禁和贴图哈希可复现。
- GLB重新导入 Blender 和 Three.js 均能加载纹理。
- 模拟烘焙失败时确认回退文件存在且源材质未丢失。

视觉回归：固定相机、固定灯光、固定色彩管理，输出正面、左右 3/4、侧面和背面，与批准基线做 SSIM/感知差异比较；超过阈值必须人工复核。

### 6.8 UI 与报告调整

- 精修配置页把“UV 策略”和“参考图投射”拆成两个设置。
- 默认显示“保留源 UV/材质”。
- 只有选择投射模式时才显示相机、覆盖区域、Atlas 和多视图参数。
- 监控页分别展示几何、UV、烘焙、纹理门禁状态。
- 验收页提供源材质/候选材质切换和 UV 棋盘格检查。
- 报告必须说明哪些区域来自源纹理、参考投射和自动推断。

### 6.9 P4 完成定义

- 当前截图所示重复人物贴图无法再通过质量门禁。
- 默认精修不会改变一个原本正确的材质模型。
- 开启投射时，所有 Mesh 使用同一相机空间并烘焙为 Atlas。
- 遮挡面和背面不会接收正面纹理。
- 失败可自动回退，且不影响已完成的几何精修。
- 输出可被 Blender、Three.js 和后续打印准备流程一致读取。

## 7. P5：打印闭环（2～4 周）

当前 `server/printer/bambu.py` 主要读取 LAN MQTT 状态。Bambu 云账号模式与 LAN Only/Developer Mode 是不同路线，不能要求普通用户为了本系统退出 Bambu 账号或关闭 Handy。

Provider 设计：

```text
PrinterProvider
├─ BambuCloudProvider      # 仅在获得许可明确、稳定接口后实现
├─ BambuConnectProvider    # 优先评估官方授权链路
├─ BambuLanProvider        # LAN Only / Developer Mode 专用
└─ ManualExportProvider    # 稳定兜底：完整 3MF交给 Bambu Studio
```

禁止保存或模拟登录用户的 Bambu 账号密码。若无正式云端接口，先交付“可靠切片、完整 3MF、Bambu Studio人工确认”。

打印链路：

```text
已验收版本→网格检查→打印机/喷嘴/材料/AMS→摆盘→切片
→ 时间耗材预估→预览确认→提交→状态告警→成品归档
```

状态机：

```text
draft → validating → slicing → awaiting_confirmation → submitting
→ queued → printing → completed / failed / paused / cancelled
```

必须固化模型版本和 SHA-256、切片器版本、配置快照、设备和材料信息。提交必须幂等；超时先查询状态，禁止直接重发。

## 8. P6（安全插队）：简单用户管理与登录保护（3～5 天）

当前服务属于“裸奔”状态：项目、素材、模型文件、GPU 调度、打印机和打印任务 API 都没有身份校验。P6 不自研密码、用户目录、重置密码或 MFA；接入成熟身份提供方并只在本项目维护业务权限映射。

### 8.1 技术选型

默认采用自托管 **Authentik + OpenID Connect（OIDC）**：

- Authentik 管理用户名、密码、密码哈希、登录策略、会话、用户禁用、密码重置和未来 MFA。
- 2D→3D Studio 作为 OIDC Relying Party，只信任固定 Issuer。
- 使用 Authorization Code Flow + PKCE，禁止 implicit flow。
- OIDC 集成使用成熟 Python 库，例如 Authlib；禁止手写 OAuth/OIDC、JWT 签名验证或 JWKS 缓存。
- Authentik 自带管理后台，项目不重复开发用户增删改和密码重置页面。

备选：团队规模明显扩大、已有 Java/企业 IAM 运维能力时可替换为 Keycloak。两者都使用标准 OIDC，业务代码不得绑定 Authentik 私有 API。Cloudflare Access可以作为公网外围第二道保护，但不能代替应用内 OIDC 鉴权和业务授权。

部署建议：

```text
auth.example.com      → Authentik（Cloudflare 代理可用）
studio.example.com    → 2D→3D Studio（Cloudflare 代理可用）
transfer6.example.com → GPU IPv6直传（DNS Only，独立机器认证）
```

Authentik、Studio和数据库分别备份；升级前固定镜像版本并阅读迁移说明，禁止生产环境自动拉取 `latest`。

### 8.2 首版范围

首版支持：

- 用户名 + 密码在 Authentik 登录；
- Authentik 管理员创建、禁用、启用用户及重置密码；
- 用户在 Authentik 账户页修改密码；
- Studio 使用服务端 OIDC 会话和安全 Cookie；
- 所有业务 API 默认需要登录；
- GPU、打印机和系统设置只允许管理员；
- 重要操作审计；
- 暂不开放自助注册；暂不做组织、多租户或计费。

角色只保留两种：

```text
admin：用户、GPU、打印机、系统配置和全部项目
user：项目、模型、精修和自己发起的打印任务
```

角色来源优先使用 Authentik Group Claim：`studio-admins` 映射为 `admin`，`studio-users` 映射为 `user`。应用数据库只保存稳定的 OIDC `sub`，不得以可修改的用户名作为主键。若首版暂时无法完成项目级归属，普通用户可以先共享项目，但 GPU/打印机管理必须仅管理员可见，并明确这是过渡状态。

### 8.3 应用数据库

不保存密码。仅增加应用身份映射、应用会话和审计：

```sql
app_users(
  id TEXT PRIMARY KEY,
  oidc_issuer TEXT NOT NULL,
  oidc_subject TEXT NOT NULL,
  username TEXT NOT NULL,
  display_name TEXT,
  role TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_login_at TEXT,
  UNIQUE(oidc_issuer, oidc_subject)
)

app_sessions(
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_users(id),
  token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  revoked_at TEXT
)

audit_logs(
  id TEXT PRIMARY KEY,
  actor_user_id TEXT REFERENCES users(id),
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  result TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
)
```

OIDC Token 如果必须服务端保存，必须加密且仅短期保存；优先只保存本应用随机 Session ID。后续预留 `projects.owner_user_id`，不得在未设计迁移策略前强制修改已有项目。

### 8.4 Authentik 配置基线

- 创建独立 OIDC Provider 和 `twotothree-studio` Application。
- Redirect URI 必须为严格匹配的生产 HTTPS 地址，禁止通配符。
- 创建 `studio-admins`、`studio-users` 两个组并映射为 groups Claim。
- 关闭公开注册和不需要的社交登录源。
- 配置密码策略、失败限速和管理员恢复流程。
- 首个管理员由 Authentik初始化流程创建，Studio 不处理 Bootstrap 密码。
- Client Secret 通过 Docker Secret或权限受限文件注入，不进 Git、不返回浏览器。
- Issuer、Client ID、Redirect URI、Scopes 明确配置；禁止运行时接受任意 Issuer。
- 为管理员预留 MFA，正式对公网开放前建议强制管理员启用 TOTP/WebAuthn。

需要记录一份可重复的部署配置或 Blueprint，但不得把真实 Secret 写入 Blueprint。

### 8.5 OIDC 登录与应用会话

- `/api/auth/login` 只负责生成 state、nonce、PKCE并重定向到 Authentik，不接收用户名密码。
- `/api/auth/callback` 使用成熟 OIDC 客户端完成 code exchange，验证 issuer、audience、签名、state、nonce和时间声明。
- 首次成功登录按 `issuer + sub` 创建 `app_users` 映射，并从可信 groups Claim计算角色。
- 角色每次登录重新同步；被移出允许组的用户禁止访问。
- Studio 生成至少 256 位随机 Session Token，数据库只保存哈希。
- 浏览器使用 `HttpOnly + Secure + SameSite=Lax` Cookie，禁止把 Token 放入 localStorage。
- 默认绝对有效期 7 天；活动会话可滑动续期，但最长不超过 30 天。
- Authentik 用户禁用或移组后，最迟在短会话/重新验证窗口内失效；管理员应能在 Studio 撤销本地会话。
- 登录、回调、退出、当前用户接口：

```text
GET  /api/auth/login
GET  /api/auth/callback
POST /api/auth/logout
GET  /api/auth/me
```

用户管理和改密跳转 Authentik 管理/账户页，不在 Studio 重复实现。Studio 可保留只读用户列表及“撤销本地会话”，但不得调用私有接口自己改密码。

### 8.6 CSRF、CORS 与反向代理

- Cookie 鉴权的所有 POST/PATCH/PUT/DELETE 都必须校验 CSRF Token或严格 Origin/Referer；推荐双提交 CSRF Token。
- CORS 禁止 `*`，只允许明确配置的控制台域名。
- 生产环境强制 HTTPS；HTTP 请求重定向或拒绝。
- 只有配置的反向代理地址才可信任 `X-Forwarded-For`，禁止用户伪造来源 IP。
- `/api/docs` 和 OpenAPI 在生产环境默认关闭或仅管理员可访问。

### 8.7 API 权限边界

默认策略是“拒绝”：除以下接口外，所有 `/api/*` 必须登录：

- `/api/auth/login`
- `/api/system/health` 的最小存活信息

管理员专属：

- `/api/gpu/*`
- `/api/printer/printers` 的新增、修改、删除和探测
- 队列暂停/恢复
- 系统设置
- 用户管理

普通用户可使用项目、素材、生成、精修、验收和允许范围内的打印任务。打印的开始、暂停、恢复、取消必须记录操作者。

静态模型和素材不能继续通过猜测 URL匿名下载。文件响应必须经过鉴权，或使用短时、一次性、绑定资源的签名 URL。GPU 的 IPv6传输接口使用独立机器凭据，不与浏览器 Session 混用。

### 8.8 前端页面

新增建议：

```text
src/pages/LoginPage.tsx
src/components/AuthGuard.tsx
src/auth.tsx
server/auth/routes.py
server/auth/service.py
server/auth/oidc.py
```

交互要求：

- 登录页只有“使用统一身份登录”按钮并跳转 Authentik，不收集密码。
- 未登录保存原目标路径，经 OIDC 登录后返回；return URL必须限制为站内路径。
- 顶栏显示用户名、角色、账户设置（Authentik）和退出。
- 非管理员不显示 GPU、打印机管理入口；后端仍必须再次鉴权。
- Session 过期时清除前端用户状态并跳转登录，不能无限弹错误。
- Authentik 不可用时显示明确故障页，不得提供临时后门或默认密码。

### 8.9 凭据保护

- 现有 GPU SSH 密钥路径、打印机 Access Code和未来厂商 Token 不得返回浏览器。
- 服务端敏感值使用主密钥加密保存；主密钥来自系统 Keychain、Docker Secret或权限受限文件，不进入 Git。
- `gpu_hosts.json` 和 `printers.json` 迁移到数据库时对敏感字段加密；迁移成功并验证后再删除旧明文。
- API 返回打印机时将 Access Code 固定脱敏为 `configured: true/false`。

### 8.10 审计

至少记录：

- 登录成功、失败、退出；
- 创建、禁用和重置用户；
- 注册、修改和删除 GPU/打印机；
- 创建、开始、暂停、恢复和取消打印；
- 删除项目或版本；
- 修改系统级配置。

审计日志不记录密码、Session Token、Access Code、SSH 私钥或完整厂商 Token。普通用户不可删除审计日志。

### 8.11 测试与验收

自动化测试至少覆盖：

1. 匿名请求业务 API 返回 401。
2. 普通用户访问 GPU/基础设施管理返回 403。
3. OIDC state、nonce、PKCE、issuer和audience校验生效。
4. 篡改、过期或错误 Issuer Token 被拒绝。
5. Session Cookie 包含 HttpOnly、Secure、SameSite。
6. 缺少或错误 CSRF 的写请求被拒绝。
7. Authentik禁用用户/移出组后无法继续建立新 Session。
8. groups Claim只能映射预定义角色，不能注入任意管理员角色。
9. Cookie、OIDC Token、Client Secret和敏感凭据不出现在日志/API响应。
10. 模型和素材匿名 URL 不能直接读取。
11. IPv6 GPU机器凭据无法调用浏览器管理 API。
12. Authentik暂时不可用时已有短期 Session按策略工作，到期后拒绝，绝不启用旁路登录。

P6 完成定义：公网打开控制台首先进入 Authentik OIDC登录；用户名密码完全由成熟 IdP处理；Studio 数据库无密码字段；没有有效 Session无法读取项目、模型、GPU或打印机；普通用户无法修改基础设施；管理员通过 Authentik管理用户，通过 Studio审计业务操作。

## 9. 监控和目标指标

GPU 控制台增加：IPv6直连状态、当前地址族、是否代理/中转、吞吐、偏移、剩余大小、校验状态、远端保留期限，并分别统计生成失败和传输失败。

指标：

- 100MB 直传成功率 ≥99%。
- 校验后产物损坏率为 0。
- 网络中断不重新推理。
- 大文件不经过 Cloudflare、CDN 或 DERP。
- 每任务只有一次输入和一次最终回传。
- 主控校验并原子提交后才显示完成。

## 10. 实施顺序和交付规则

实施顺序调整为：P0 → P6 → P1 → P2 → P3 → P4 → P5。P0 先避免远端产物丢失，随后立即用 P6 封住公网 API，再继续网络、纹理和打印建设。每阶段独立提交，先补测试，不破坏现有数据；新链路稳定前不删除旧代码，但旧中转必须默认关闭。每次交付报告改动文件、命令、测试结果、兼容性和剩余风险。物理网络前提不满足时必须停止并报告，不得自行引入中转。

## 11. 可直接交给实施 AI 的第一条提示词

> 阅读 `design/PRODUCTION_UPGRADE_MASTER_PLAN.md` 全文，只实施 P0。检查工作区已有改动，修复 `server/backends.py` 的远端存在性误判、过早清理、缺少长度/SHA-256校验和错误分类问题，增加自动化测试。不得新增 CDN、Cloudflare upload 或 DERP 回退；不得开始 P1以后工作。完成后报告改动文件、测试命令、结果、兼容性和遗留风险。
