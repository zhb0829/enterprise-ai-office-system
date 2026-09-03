"""服务内部接口的共享鉴权依赖。"""
import hmac

from fastapi import HTTPException, Request

from .config import settings


async def require_internal_token(request: Request) -> None:
    """校验 Java 与 Python 服务之间约定的 X-Internal-Token。"""
    provided = request.headers.get("X-Internal-Token", "")
    expected = settings.ai_internal_token or ""
    if not provided or not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="invalid internal token")
