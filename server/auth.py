"""Authentication boundary: Authentik/OpenID Connect 或内置简单账号密码。

三种模式由 AUTH_MODE 控制：
  disabled   — 不鉴权（AUTH_DISABLED=true，开发/内网快速调试）
  oidc       — Authentik/OpenID Connect（默认，生产正式线）
  simple     — 内置用户名/密码（env 配置，适合内网 / 无 HTTPS 阶段）
               管理员 SIMPLE_ADMIN_USER/SIMPLE_ADMIN_PASSWORD
               普通用户 SIMPLE_USER_USER/SIMPLE_USER_PASSWORD
浏览器 session 只存一份受签名保护的短时票据（用户名 + role）。
"""
from __future__ import annotations

import os
from urllib.parse import urlencode, urlparse

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

AUTH_DISABLED=os.environ.get('AUTH_DISABLED','').lower() in {'1','true','yes'}
AUTH_MODE=os.environ.get('AUTH_MODE','oidc').strip().lower()  # disabled | oidc | simple

# --- OIDC（Authentik）---
OIDC_ISSUER=os.environ.get('OIDC_ISSUER','').rstrip('/')
OIDC_CLIENT_ID=os.environ.get('OIDC_CLIENT_ID','')
OIDC_CLIENT_SECRET=os.environ.get('OIDC_CLIENT_SECRET','')
OIDC_REDIRECT_URI=os.environ.get('OIDC_REDIRECT_URI','')
OIDC_GROUPS_CLAIM=os.environ.get('OIDC_GROUPS_CLAIM','groups')
OIDC_ADMIN_GROUP=os.environ.get('OIDC_ADMIN_GROUP','studio-admins')
OIDC_USER_GROUP=os.environ.get('OIDC_USER_GROUP','studio-users')

# --- Simple（内置账号）---
SIMPLE_ADMIN_USER=os.environ.get('SIMPLE_ADMIN_USER','admin')
SIMPLE_ADMIN_PASSWORD=os.environ.get('SIMPLE_ADMIN_PASSWORD','')
SIMPLE_USER_USER=os.environ.get('SIMPLE_USER_USER','')
SIMPLE_USER_PASSWORD=os.environ.get('SIMPLE_USER_PASSWORD','')
SIMPLE_SESSION_TTL=int(os.environ.get('SIMPLE_SESSION_TTL','43200'))  # 12h

SESSION_MAX_AGE=int(os.environ.get('SESSION_MAX_AGE','28800'))

PUBLIC_PATHS={'/api/auth/login','/api/auth/callback','/api/auth/logout','/api/auth/me','/api/system/health','/api/openapi.json','/api/docs','/api/docs/oauth2-redirect'}
PUBLIC_PREFIXES=('/assets/','/favicon','/login')

oauth=OAuth()
if AUTH_MODE=='oidc' and OIDC_ISSUER and OIDC_CLIENT_ID:
    oauth.register(
        name='authentik',
        client_id=OIDC_CLIENT_ID,
        client_secret=OIDC_CLIENT_SECRET,
        server_metadata_url=f'{OIDC_ISSUER}/.well-known/openid-configuration',
        client_kwargs={'scope':'openid profile email','timeout':30},
    )

router=APIRouter(prefix='/api/auth',tags=['auth'])

_LOGIN_HTML_TEMPLATE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>登录 · {title}</title>
<style>
  *{{box-sizing:border-box}} body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
    background:linear-gradient(160deg,#fffaf1,#fde7ef);font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif}}
  .card{{width:360px;max-width:92vw;background:#fff;border-radius:20px;padding:36px 32px;box-shadow:0 12px 40px rgba(214,140,160,.18);text-align:center}}
  .logo{{width:52px;height:52px;border-radius:14px;background:linear-gradient(135deg,#ff9fb2,#ffb3c7);
    display:inline-flex;align-items:center;justify-content:center;color:#fff;font-size:26px;margin-bottom:14px}}
  h1{{font-size:20px;margin:0 0 6px;color:#4a3641}} p.sub{{font-size:13px;color:#9a8b92;margin:0 0 22px}}
  label{{display:block;text-align:left;font-size:12px;color:#7a6a72;margin:12px 0 4px;font-weight:600}}
  input{{width:100%;padding:11px 14px;border:1px solid #efdde3;border-radius:10px;font-size:14px;outline:none}}
  input:focus{{border-color:#ff9fb2;box-shadow:0 0 0 3px rgba(255,159,178,.18)}}
  button{{width:100%;margin-top:20px;padding:12px;border:0;border-radius:10px;cursor:pointer;color:#fff;font-size:15px;font-weight:700;
    background:linear-gradient(135deg,#f78ba6,#ffa8b8)}}
  .error{{color:#c0392b;font-size:13px;margin-top:12px;min-height:18px}}
  .foot{{font-size:11px;color:#bfb0b6;margin-top:18px}}
</style></head><body>
<form class="card" method="post" action="/api/auth/login">
  <div class="logo">✦</div>
  <h1>{title}</h1>
  <p class="sub">{slogan}</p>
  <input type="hidden" name="return_to" value="{return_to}"/>
  <label for="u">用户名</label><input id="u" name="username" autocomplete="username" autofocus required/>
  <label for="p">密码</label><input id="p" name="password" type="password" autocomplete="current-password" required/>
  <button type="submit">进入工坊</button>
  <div class="error">{error}</div>
  <div class="foot">账号由工坊管理员分配 · 如无账号请先申请</div>
</form></body></html>"""


def _simple_credentials() -> dict[str, str]:
    creds = {}
    if SIMPLE_ADMIN_USER and SIMPLE_ADMIN_PASSWORD:
        creds[SIMPLE_ADMIN_USER] = {'password': SIMPLE_ADMIN_PASSWORD, 'role': 'admin', 'name': '管理员'}
    if SIMPLE_USER_USER and SIMPLE_USER_PASSWORD:
        creds[SIMPLE_USER_USER] = {'password': SIMPLE_USER_PASSWORD, 'role': 'user', 'name': SIMPLE_USER_USER}
    return creds


def validate_config() -> None:
    if AUTH_DISABLED:
        return
    secret = os.environ.get('SESSION_SECRET', '')
    if not secret:
        raise RuntimeError('鉴权已启用但缺少 SESSION_SECRET')
    if len(secret) < 32:
        raise RuntimeError('SESSION_SECRET 至少需要 32 个字符')
    if AUTH_MODE == 'simple':
        if not _simple_credentials():
            raise RuntimeError('简单鉴权(AUTH_MODE=simple)至少需要一个账号：设置 SIMPLE_ADMIN_USER/PASSWORD 或 SIMPLE_USER_USER/PASSWORD')
        return
    missing = [name for name, value in (
        ('OIDC_ISSUER', OIDC_ISSUER), ('OIDC_CLIENT_ID', OIDC_CLIENT_ID), ('OIDC_CLIENT_SECRET', OIDC_CLIENT_SECRET),
    ) if not value]
    if missing:
        raise RuntimeError('OIDC 鉴权缺少配置: ' + ', '.join(missing))


async def prefetch_metadata() -> None:
    """Pre-fetch OIDC discovery metadata at startup so the first login isn't slow."""
    if AUTH_MODE != 'oidc':
        return
    if not (OIDC_ISSUER and OIDC_CLIENT_ID and getattr(oauth, 'authentik', None)):
        return
    try:
        await oauth.authentik.load_server_metadata()
    except Exception:
        pass  # will retry on first login request


def _safe_return_to(value: str | None) -> str:
    if not value:
        return '/'
    parsed = urlparse(value)
    return value if not parsed.scheme and not parsed.netloc and value.startswith('/') else '/'


def _groups(claims: dict) -> set[str]:
    raw = claims.get(OIDC_GROUPS_CLAIM, [])
    if isinstance(raw, str):
        raw = [raw]
    return {str(x) for x in raw}


def session_user(request: Request) -> dict | None:
    if AUTH_DISABLED:
        return {'sub': 'development', 'name': '本地开发管理员', 'email': '', 'role': 'admin', 'groups': [OIDC_ADMIN_GROUP]}
    user = request.session.get('user')
    return dict(user) if user else None


def _is_admin(user: dict) -> bool:
    return user.get('role') == 'admin'


def requires_admin(path: str, method: str) -> bool:
    # GPU 与打印机注册表包含 SSH key、IP、access code，全部仅管理员可见。
    if path.startswith('/api/gpu') or path.startswith('/api/printer'):
        return True
    # AutoDL 实例生命周期（开机/关机）与存储配置状态仅管理员可见。
    if path.startswith('/api/autodl') or path.startswith('/api/settings') or path == '/api/system/storage':
        return True
    if path.startswith('/api/print/') and method in {'DELETE'}:
        return True
    return False


def is_public(path: str) -> bool:
    if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return True
    # SPA HTML 必须可加载，实际数据、模型和 API 仍由中间件保护。
    return not path.startswith(('/api/', '/data/', '/public/'))


def _title() -> str:
    from .settings import current as cfg_current
    return cfg_current('site.name') or '2D→3D 造物坊'


@router.get('/login')
async def login_get(request: Request, return_to: str = '/'):
    target = _safe_return_to(return_to)
    if AUTH_DISABLED:
        return RedirectResponse(target)
    if AUTH_MODE != 'oidc':
        # simple / fallback：渲染内置登录页（HTML 表单）
        return HTMLResponse(_LOGIN_HTML_TEMPLATE.format(
            title=_title(), slogan='欢迎回到造物工坊，请登录', return_to=target, error=''), status_code=200)
    if not getattr(oauth, 'authentik', None):
        raise HTTPException(503, 'OIDC 尚未配置')
    request.session['return_to'] = target
    callback = OIDC_REDIRECT_URI or str(request.url_for('auth_callback'))
    try:
        return await oauth.authentik.authorize_redirect(request, callback)
    except Exception as exc:
        raise HTTPException(503, f'OIDC 服务暂时不可用，请稍后重试：{exc}') from exc


@router.post('/login')
async def login_post(request: Request, username: str = Form(''), password: str = Form(''), return_to: str = Form('/')):
    target = _safe_return_to(return_to)
    if AUTH_DISABLED:
        return RedirectResponse(target, status_code=303)
    if AUTH_MODE == 'simple':
        creds = _simple_credentials()
        account = creds.get(username)
        if not account or account['password'] != password:
            return HTMLResponse(_LOGIN_HTML_TEMPLATE.format(
                title=_title(), slogan='欢迎回到造物工坊，请登录', return_to=target,
                error='用户名或密码不正确，请重试'), status_code=401)
        request.session.clear()
        request.session['user'] = {'sub': username, 'name': account['name'], 'email': '',
                                   'role': account['role'], 'groups': ['studio-admin'] if account['role'] == 'admin' else ['studio-user']}
        return RedirectResponse(target, status_code=303)
    # OIDC 模式不接受表单 POST，引导到标准登录
    return RedirectResponse(f'/api/auth/login?return_to={urlencode({"return_to": target})}', status_code=303)


@router.get('/callback', name='auth_callback')
async def callback(request: Request):
    if AUTH_DISABLED:
        return RedirectResponse('/')
    if AUTH_MODE != 'oidc':
        return RedirectResponse('/')
    try:
        token = await oauth.authentik.authorize_access_token(request)
    except OAuthError as exc:
        if exc.error == 'mismatching_state':
            request.session.clear()
            return RedirectResponse('/api/auth/login?return_to=/')
        raise HTTPException(401, f'OIDC 登录失败: {exc.error}')
    except ValueError as exc:
        detail = getattr(exc, 'error', None) or str(exc) or 'token_validation_failed'
        raise HTTPException(401, f'OIDC 登录失败: {detail}')
    claims = token.get('userinfo') or await oauth.authentik.userinfo(token=token)
    groups = _groups(claims)
    if OIDC_ADMIN_GROUP in groups:
        role = 'admin'
    elif OIDC_USER_GROUP in groups:
        role = 'user'
    else:
        raise HTTPException(403, '账号未加入 Studio 用户组')
    return_to = _safe_return_to(request.session.get('return_to', '/'))
    request.session.clear()
    request.session['user'] = {'sub': claims['sub'], 'name': claims.get('name') or claims.get('preferred_username') or claims['sub'], 'email': claims.get('email', ''), 'role': role, 'groups': sorted(groups)}
    return RedirectResponse(return_to)


@router.get('/me')
def me(request: Request):
    user = session_user(request)
    if not user:
        return JSONResponse({'authenticated': False}, status_code=401)
    return {'authenticated': True, **user, 'adminGroup': OIDC_ADMIN_GROUP, 'userGroup': OIDC_USER_GROUP}


@router.get('/logout', name='logout')
@router.post('/logout')
def logout(request: Request, return_to: str = '/'):
    """退出登录：清除本地会话。OIDC 启用时同时 RP-initiated 登出 IdP。"""
    target = _safe_return_to(return_to)
    request.session.clear()
    if AUTH_MODE == 'oidc' and not AUTH_DISABLED and getattr(oauth, 'authentik', None):
        metadata = getattr(oauth.authentik, 'server_metadata', {}) or {}
        end = metadata.get('end_session_endpoint')
        if end:
            sep = '&' if '?' in end else '?'
            return RedirectResponse(f'{end}{sep}{urlencode({"post_logout_redirect_uri": target})}')
    return RedirectResponse(target)
