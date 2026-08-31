"""Authentik/OpenID Connect authentication boundary.

Passwords and user lifecycle stay in the IdP.  Studio stores only a signed,
short-lived browser session containing stable OIDC claims.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

AUTH_DISABLED=os.environ.get('AUTH_DISABLED','').lower() in {'1','true','yes'}
OIDC_ISSUER=os.environ.get('OIDC_ISSUER','').rstrip('/')
OIDC_CLIENT_ID=os.environ.get('OIDC_CLIENT_ID','')
OIDC_CLIENT_SECRET=os.environ.get('OIDC_CLIENT_SECRET','')
OIDC_REDIRECT_URI=os.environ.get('OIDC_REDIRECT_URI','')
OIDC_GROUPS_CLAIM=os.environ.get('OIDC_GROUPS_CLAIM','groups')
OIDC_ADMIN_GROUP=os.environ.get('OIDC_ADMIN_GROUP','studio-admins')
OIDC_USER_GROUP=os.environ.get('OIDC_USER_GROUP','studio-users')
SESSION_MAX_AGE=int(os.environ.get('SESSION_MAX_AGE','28800'))

PUBLIC_PATHS={'/api/auth/login','/api/auth/callback','/api/auth/logout','/api/auth/me','/api/system/health','/api/openapi.json','/api/docs','/api/docs/oauth2-redirect'}
PUBLIC_PREFIXES=('/assets/','/favicon','/login')

oauth=OAuth()
if OIDC_ISSUER and OIDC_CLIENT_ID:
    oauth.register(
        name='authentik',
        client_id=OIDC_CLIENT_ID,
        client_secret=OIDC_CLIENT_SECRET,
        server_metadata_url=f'{OIDC_ISSUER}/.well-known/openid-configuration',
        client_kwargs={'scope':'openid profile email','timeout':30},
    )

router=APIRouter(prefix='/api/auth',tags=['auth'])

def validate_config() -> None:
    if AUTH_DISABLED:return
    missing=[name for name,value in (
        ('SESSION_SECRET',os.environ.get('SESSION_SECRET','')),
        ('OIDC_ISSUER',OIDC_ISSUER),('OIDC_CLIENT_ID',OIDC_CLIENT_ID),('OIDC_CLIENT_SECRET',OIDC_CLIENT_SECRET),
    ) if not value]
    if missing:raise RuntimeError('鉴权已启用但缺少配置: '+', '.join(missing))
    secret=os.environ['SESSION_SECRET']
    if len(secret)<32:raise RuntimeError('SESSION_SECRET 至少需要 32 个字符')

async def prefetch_metadata() -> None:
    """Pre-fetch OIDC discovery metadata at startup so the first login isn't slow."""
    if not (OIDC_ISSUER and OIDC_CLIENT_ID and getattr(oauth,'authentik',None)):return
    try:await oauth.authentik.load_server_metadata()
    except Exception:pass  # will retry on first login request

def _safe_return_to(value:str|None)->str:
    if not value:return '/'
    parsed=urlparse(value)
    return value if not parsed.scheme and not parsed.netloc and value.startswith('/') else '/'

def _groups(claims:dict)->set[str]:
    raw=claims.get(OIDC_GROUPS_CLAIM,[])
    if isinstance(raw,str):raw=[raw]
    return {str(x) for x in raw}

def session_user(request:Request)->dict|None:
    if AUTH_DISABLED:
        return {'sub':'development','name':'本地开发管理员','email':'','role':'admin','groups':[OIDC_ADMIN_GROUP]}
    user=request.session.get('user')
    return dict(user) if user else None

def _is_admin(user:dict)->bool:return user.get('role')=='admin'

def requires_admin(path:str,method:str)->bool:
    # GPU 与打印机注册表包含 SSH key、IP、access code，全部仅管理员可见。
    if path.startswith('/api/gpu') or path.startswith('/api/printer'):return True
    # AutoDL 实例生命周期（开机/关机）与存储配置状态仅管理员可见。
    if path.startswith('/api/autodl') or path=='/api/system/storage':return True
    if path.startswith('/api/print/') and method in {'DELETE'}:return True
    return False

def is_public(path:str)->bool:
    if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):return True
    # SPA HTML 必须可加载，实际数据、模型和 API 仍由中间件保护。
    return not path.startswith(('/api/','/data/','/public/'))

@router.get('/login')
async def login(request:Request,return_to:str='/'):
    if AUTH_DISABLED:return RedirectResponse(_safe_return_to(return_to))
    if not getattr(oauth,'authentik',None):raise HTTPException(503,'OIDC 尚未配置')
    request.session['return_to']=_safe_return_to(return_to)
    callback=OIDC_REDIRECT_URI or str(request.url_for('auth_callback'))
    try:return await oauth.authentik.authorize_redirect(request,callback)
    except Exception as exc:
        raise HTTPException(503,f'OIDC 服务暂时不可用，请稍后重试：{exc}') from exc

@router.get('/callback',name='auth_callback')
async def callback(request:Request):
    if AUTH_DISABLED:return RedirectResponse('/')
    try:token=await oauth.authentik.authorize_access_token(request)
    except OAuthError as exc:
        # A stale browser tab or a container redeploy can leave an authorization
        # response whose state no longer matches the signed session. Start a
        # fresh flow instead of exposing a JSON error page to the user.
        if exc.error=='mismatching_state':
            request.session.clear()
            return RedirectResponse('/api/auth/login?return_to=/')
        raise HTTPException(401,f'OIDC 登录失败: {exc.error}')
    except ValueError as exc:
        detail=getattr(exc,'error',None) or str(exc) or 'token_validation_failed'
        raise HTTPException(401,f'OIDC 登录失败: {detail}')
    claims=token.get('userinfo') or await oauth.authentik.userinfo(token=token)
    groups=_groups(claims)
    if OIDC_ADMIN_GROUP in groups:role='admin'
    elif OIDC_USER_GROUP in groups:role='user'
    else:raise HTTPException(403,'账号未加入 Studio 用户组')
    return_to=_safe_return_to(request.session.get('return_to','/'))
    request.session.clear()
    request.session['user']={'sub':claims['sub'],'name':claims.get('name') or claims.get('preferred_username') or claims['sub'],'email':claims.get('email',''),'role':role,'groups':sorted(groups)}
    return RedirectResponse(return_to)

@router.get('/me')
def me(request:Request):
    user=session_user(request)
    if not user:return JSONResponse({'authenticated':False},status_code=401)
    return {'authenticated':True,**user,'adminGroup':OIDC_ADMIN_GROUP,'userGroup':OIDC_USER_GROUP}

@router.post('/logout')
def logout(request:Request):
    request.session.clear()
    return {'ok':True}
