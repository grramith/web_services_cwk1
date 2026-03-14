"""Auth routes: register, login, refresh, logout, get current user."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import InvalidatedToken, User
from app.schemas import TokenPair, UserCreate, UserRead
from app.auth import (
    create_token, decode_token, get_current_user,
    hash_password, is_token_blacklisted, verify_password,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/register", response_model=UserRead, status_code=201,
             summary="Register a new user account")
def register(body: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(409, "Username already taken")
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "Email already registered")
    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenPair,
             summary="Obtain access + refresh token pair")
def login(form: OAuth2PasswordRequestForm = Depends(),
          db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    return TokenPair(
        access_token=create_token(
            {"sub": str(user.id), "type": "access"},
            timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        ),
        refresh_token=create_token(
            {"sub": str(user.id), "type": "refresh"},
            timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ),
    )


@router.post("/refresh", response_model=TokenPair,
             summary="Exchange a refresh token for a new access + refresh token pair")
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    """
    Validates the refresh token, blacklists it immediately (rotation),
    and issues a fresh access + refresh token pair.
    """
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid or expired refresh token")

    jti = payload.get("jti")
    if jti and is_token_blacklisted(jti, db):
        raise HTTPException(401, "Refresh token has already been used")

    # Blacklist the used refresh token immediately (token rotation)
    if jti:
        exp = payload.get("exp")
        expires_at = (
            datetime.fromtimestamp(exp, tz=timezone.utc)
            if exp else datetime.now(timezone.utc) + timedelta(days=7)
        )
        db.add(InvalidatedToken(jti=jti, expires_at=expires_at))
        db.commit()

    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(401, "User not found")

    return TokenPair(
        access_token=create_token(
            {"sub": str(user.id), "type": "access"},
            timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        ),
        refresh_token=create_token(
            {"sub": str(user.id), "type": "refresh"},
            timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ),
    )


from fastapi.security import OAuth2PasswordBearer as _OAuth2
_raw_token = _OAuth2(tokenUrl="/api/v1/auth/login")


@router.post("/logout", status_code=200,
             summary="Invalidate the current access token")
def logout(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    token: str = Depends(_raw_token),
):
    payload = decode_token(token)
    if payload:
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti:
            expires_at = (
                datetime.fromtimestamp(exp, tz=timezone.utc)
                if exp else datetime.now(timezone.utc) + timedelta(minutes=30)
            )
            if not is_token_blacklisted(jti, db):
                db.add(InvalidatedToken(jti=jti, expires_at=expires_at))
                db.commit()
    return {"status": "logged out", "message": "Token invalidated successfully"}


@router.get("/me", response_model=UserRead,
            summary="Get the current user's profile")
def me(user: User = Depends(get_current_user)):
    return user