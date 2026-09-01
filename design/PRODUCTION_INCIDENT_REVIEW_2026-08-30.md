# 生产升级事故复盘（2026-08-30）

## 结论

本次升级暴露了四类问题：反向代理路径未实际载入、OIDC Provider 未绑定签名证书、旧授权页 state 失效未自愈，以及全局 CSS `.ok` 选择器误伤控制台统计卡片。前三项影响登录可用性，第四项影响 GPU 与打印机页面布局。问题均已修复并补充自动化或运行时验收。

## 影响

- 用户最初只能看到二次“统一身份登录”按钮，无法直接看到账号密码页。
- 输入正确账号密码后，OIDC 回调曾返回 HTTP 500。
- 反复部署或使用旧登录标签页时曾显示 `mismatching_state` JSON。
- GPU“在线”和打印机“在线”统计卡片被压缩为约 18px 宽的竖条。
- 模型、项目和打印数据未丢失；匿名业务 API 始终保持拒绝访问。

## 根因

### 1. Authentik 路由加载竞态

Nginx Proxy Manager 的持久自定义配置刚写入宿主机时，Docker Desktop 挂载尚未在容器内可见。第一次 `nginx -t && reload` 成功，但 include 当时匹配不到文件，`/authentik/` 因而落入 Studio SPA 的默认路由。

修复：将规则保存在 NPM 持久数据卷的 `nginx/custom/server_proxy.conf`，等待挂载可见后重新加载，并额外执行一次容器重启验收，确认 `nginx -T` 中存在该 location。

### 2. OIDC Provider 缺少 signing key

自动创建 Authentik OAuth2 Provider 时配置了 Client、Flow、Scope 和回调地址，但遗漏 `signing_key`。Token 端点返回成功，JWKS 却是空数组，Authlib 解析 ID Token 时抛出 `Invalid key set format`。

修复：绑定 Authentik 默认自签名 RSA Certificate/Key Pair；验收要求 JWKS `keys` 至少为 1，不能只验证 Discovery 200。

### 3. state 失效没有恢复路径

用户保留旧 Authentik Flow 页面时，后续重新发起登录或应用重建会使浏览器返回的 state 与当前签名 Session 不一致。应用原先把 Authlib 异常直接显示成 JSON。

修复：捕获 `mismatching_state`，清理旧 Session 并自动重启登录流程；其他 Token 校验错误转换成明确的 401，不再返回裸 500。

### 4. 全局 `.ok` CSS 类冲突

素材校验区曾使用组合选择器 `.asset-row svg, .ok { width:18px }`。GPU 和打印机统计卡片也用 `.ok` 表示在线状态，因此整张卡片被强制设为 18px 宽。Grid 仍给其他卡片分配正常宽度，形成截图中的窄竖条。

修复：把选择器限定为 `.asset-row .ok`；新增静态回归测试，禁止重新出现裸 `.ok` 尺寸规则，并校验两类统计 Grid 的最小宽度。

## 为什么上线前没发现

- 只验证了 HTTP 状态和 OIDC Discovery，没有执行“JWKS 非空”和完整授权回调验收。
- Nginx 只做了一次语法检查，没有检查最终展开配置，也没有重启后复验。
- 前端构建和单元测试无法发现跨页面 CSS 类名碰撞；没有 GPU/打印机页面的视觉回归用例。
- 部署过程中多次重建应用，使旧浏览器授权页更容易触发 state 过期，但应用没有设计自愈。

## 已执行纠正措施

- 登录页自动进入 Authentik，不再增加一次无意义点击。
- 生产 OIDC 回调固定使用 HTTPS 地址。
- Provider 已绑定 RSA signing key，JWKS 非空。
- `mismatching_state` 自动重新登录。
- 浅健康检查完全脱离 GPU2 SSH；远端检查迁移到深度诊断接口。
- 修复 `.ok` 选择器作用域并增加测试。
- Authentik、NPM、Studio 配置及凭据均有生产备份或权限隔离。

## 后续门禁

后续认证变更必须同时通过：匿名 API 401、登录 302、Discovery 200、JWKS 非空、真实账号完成回调、普通用户/管理员权限差异。前端公共状态类禁止使用无命名空间的尺寸/布局规则；GPU、打印机和打印工作台纳入桌面宽度截图回归。
