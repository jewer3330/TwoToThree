# Authentik 登录部署

Studio 使用标准 OIDC，用户名、密码、重置密码、禁用用户和 MFA 均由 Authentik 管理。业务数据库不保存密码。

## 1. 安装 Authentik

不要复制或自行维护 Authentik 的 Compose 文件。按官方文档下载固定版本的 `compose.yml`，当前基线为 `2026.8`：

```bash
mkdir -p /Volumes/ssd/servers/authentik
cd /Volumes/ssd/servers/authentik
curl -L https://goauthentik.io/version/2026.8/lifecycle/container/compose.yml -o compose.yml
openssl rand -base64 36 > postgres-password.txt
openssl rand -base64 60 > authentik-secret.txt
```

根据官方 Compose 的说明生成 `.env`，固定 `AUTHENTIK_TAG`，禁止生产环境使用 `latest`。首次启动后访问 Authentik 初始化页面创建管理员。

## 2. 创建 Studio OIDC Provider

在 Authentik 管理后台：

1. 创建 OAuth2/OpenID Provider，Client type 选择 `Confidential`。
2. Redirect URI 设置为 `https://studio.example.com/api/auth/callback`，必须精确匹配。
3. Signing Key 使用 Authentik 管理的 RSA key。
4. Scopes 至少包含 `openid profile email`。
5. 创建 Application 并绑定该 Provider。
6. 创建组 `studio-admin` 和 `studio-user`，通过 Scope Mapping 把组名放进 `groups` claim。
7. 管理员加入 `studio-admin`；普通使用者加入 `studio-user`。未加入任一组的账号会被 Studio 拒绝。

## 3. 配置 Studio

复制仓库根目录 `.env.auth.example` 的变量到生产 Compose。生成独立的 `SESSION_SECRET`：

```bash
openssl rand -base64 48
```

生产环境不得设置 `AUTH_DISABLED=true`。开发机确需绕过时必须显式设置该变量，并且服务只能监听回环地址。

启动后验证：

```bash
curl -i https://studio.example.com/api/projects       # 401
curl -i https://studio.example.com/data/example.glb   # 401
curl -i https://studio.example.com/api/system/health  # 200
```

普通用户登录后访问 `/api/gpu/*` 或 `/api/printer/*` 必须得到 403。浏览器 Cookie 为 HttpOnly、SameSite=Lax，生产环境必须使用 HTTPS。

## 4. Cloudflare 边界

`studio.example.com` 和 `auth.example.com` 可以继续走 Cloudflare HTTPS 代理；GPU 大文件直传域名不得复用这条链路。OIDC 浏览器登录流与 GPU 机器传输凭据完全分离。

## 5. 当前生产部署（2026-08-30）

- Studio：`https://3d.6.lovesun.top/`
- Authentik：`https://3d.6.lovesun.top/authentik/`（同域路径，避免新增 Cloudflare DNS 记录）
- OIDC issuer：`https://3d.6.lovesun.top/authentik/application/o/print3d-studio/`
- 回调：`https://3d.6.lovesun.top/api/auth/callback`
- 生产目录：`/Volumes/ssd/servers/authentik`
- 初始凭据：`/Volumes/ssd/servers/authentik/.bootstrap-credentials`，权限必须保持 `0600`，不得提交 Git。
- Nginx Proxy Manager 的持久路径规则：`/Volumes/ssd/servers/npm_server/data/npm/data/nginx/custom/server_proxy.conf`。

已创建 `studio-admin`、`studio-user` 两个组和一个 `studio` 普通账号。Studio 已关闭 `AUTH_DISABLED`；匿名访问业务 API 返回 401。健康检查不再访问 GPU2，远端 GPU/能力探测只允许走深度诊断接口。
