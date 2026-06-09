"""Authentication & authorization (PRD §F3).

Password hashing uses stdlib PBKDF2 (no native deps). Tokens are opaque random
strings stored in auth_tokens. Role-based access via require_role(...).
"""
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session

from db.database import get_session
from db.models import User, AuthToken, AuditLog

PBKDF2_ROUNDS = 200_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS)
    return dk.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    calc, _ = hash_password(password, salt)
    return secrets.compare_digest(calc, password_hash)


def create_user(db: Session, email: str, password: str, role: str,
                org_id: str | None = None, participant_id: str | None = None) -> User:
    h, salt = hash_password(password)
    u = User(email=email, password_hash=h, salt=salt, role=role,
             org_id=org_id, participant_id=participant_id)
    db.add(u)
    db.flush()
    return u


def issue_token(db: Session, user: User, days: int = 30) -> str:
    tok = secrets.token_urlsafe(32)
    db.add(AuthToken(token=tok, user_id=user.id,
                     expires_at=datetime.utcnow() + timedelta(days=days)))
    db.flush()
    return tok


def authenticate(db: Session, email: str, password: str) -> str | None:
    u = db.query(User).filter_by(email=email).first()
    if not u or not verify_password(password, u.password_hash, u.salt):
        return None
    return issue_token(db, u)


def audit(db: Session, user, action: str, target: str = ""):
    db.add(AuditLog(user_id=getattr(user, "id", None),
                    role=getattr(user, "role", ""), action=action, target=target))


# ---------- FastAPI dependencies ----------
def current_user(authorization: str = Header(default=""),
                 db: Session = Depends(get_session)) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.split(" ", 1)[1]
    row = db.get(AuthToken, token)
    if not row or (row.expires_at and row.expires_at < datetime.utcnow()):
        raise HTTPException(401, "invalid or expired token")
    user = db.get(User, row.user_id)
    if not user:
        raise HTTPException(401, "user not found")
    return user


def require_role(*roles):
    def _dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles and user.role != "sysadmin":
            raise HTTPException(403, f"requires role in {roles}")
        return user
    return _dep
