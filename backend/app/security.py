import re
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings

ALGO = "HS256"


def hash_secret(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_secret(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.secret_key, algorithm=ALGO)


def decode_token(token: str) -> int | None:
    try:
        return int(jwt.decode(token, settings.secret_key, algorithms=[ALGO])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def password_problem(pw: str) -> str | None:
    if len(pw) <= 8:
        return "Password must be more than 8 characters"
    if not re.search(r"[a-z]", pw):
        return "Password must contain a lowercase letter"
    if not re.search(r"[A-Z]", pw):
        return "Password must contain an uppercase letter"
    if not re.search(r"[^A-Za-z0-9]", pw):
        return "Password must contain a special character"
    return None
