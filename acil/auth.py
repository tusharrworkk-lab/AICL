import hashlib
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from acil.db import get_db
from acil.models import ApiKey

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="ACILBearerAuth")


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    api_key_id: UUID


def hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def authenticate_api_key(raw_key: str, db: Session) -> TenantContext:
    api_key = db.scalar(
        select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw_key), ApiKey.active.is_(True))
    )
    if api_key is None:
        raise ValueError("Invalid API key")
    return TenantContext(api_key.tenant_id, api_key.id)


def require_tenant(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    db: Session = Depends(get_db),
) -> TenantContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer API key required"
        )
    try:
        return authenticate_api_key(credentials.credentials, db)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
