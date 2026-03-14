"""JWT authentication, password hashing, FastAPI dependencies."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import InvalidatedToken, User

pwd_context   = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(payload: dict, expires: timedelta) -> str:
    """Create a signed JWT with a unique JTI claim for blacklisting support."""
    return jwt.encode(
        {
            **payload,
            "jti": uuid.uuid4().hex,
            "exp": datetime.now(timezone.utc) + expires,
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY,
                          algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


def is_token_blacklisted(jti: str, db: Session) -> bool:
    return db.query(InvalidatedToken).filter(
        InvalidatedToken.jti == jti).first() is not None


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(401, "Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    jti = payload.get("jti")
    if jti and is_token_blacklisted(jti, db):
        raise HTTPException(401, "Token has been invalidated — please log in again",
                            headers={"WWW-Authenticate": "Bearer"})
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(401, "User not found")
    return user