from collections.abc import Callable
from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException
from starlette.concurrency import run_in_threadpool
from jwt import PyJWKClient

from .config import Settings, get_settings
from .models import AppRole, Principal, Profile
from .supabase import SupabaseGateway, get_gateway


@lru_cache(maxsize=8)
def jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(f"{url.rstrip('/')}/auth/v1/.well-known/jwks.json", cache_jwk_set=True, lifespan=300)


def decode_access_token(token: str, settings: Settings) -> UUID:
    try:
        key = jwks_client(str(settings.supabase_url)).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.supabase_jwt_audience,
            issuer=f"{str(settings.supabase_url).rstrip('/')}/auth/v1",
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
        if claims.get("role") != "authenticated":
            raise ValueError("Unexpected token role")
        return UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=401, detail="INVALID_TOKEN") from exc


async def current_principal(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    gateway: SupabaseGateway = Depends(get_gateway),
) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
    token = authorization[7:]
    user_id = await run_in_threadpool(decode_access_token, token, settings)
    profile = await gateway.get_profile(token, user_id)
    if profile is None or profile.status != "ACTIVE" or not profile.roles:
        raise HTTPException(status_code=403, detail="PROFILE_INACTIVE_OR_MISSING")
    return Principal(user_id=user_id, token=token, profile=profile)


def require_roles(*allowed: AppRole) -> Callable:
    allowed_set = set(allowed)

    async def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.profile.roles.intersection(allowed_set):
            raise HTTPException(status_code=403, detail="FORBIDDEN_ROLE")
        return principal

    return dependency


def may_manage_foundation(profile: Profile) -> bool:
    return bool(profile.roles.intersection({AppRole.ADMIN, AppRole.TRAINING_MANAGER}))
