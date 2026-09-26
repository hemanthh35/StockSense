import hashlib
import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, ratelimit
from ..db import get_db
from ..deps import current_user
from ..mail import send_otp
from ..models import OtpCode, User
from ..security import create_token, hash_secret, password_problem, verify_secret
from ..stock import utcnow

router = APIRouter(prefix="/auth", tags=["auth"])

Pw = Field(max_length=128)


class SignupIn(BaseModel):
    login_id: str = Field(max_length=32)
    email: EmailStr
    password: str = Pw
    confirm_password: str = Pw


class LoginIn(BaseModel):
    login_id: str = Field(max_length=64)
    password: str = Pw


class ForgotIn(BaseModel):
    email: EmailStr


class ProfileIn(BaseModel):
    email: EmailStr


class ChangePasswordIn(BaseModel):
    current_password: str = Pw
    new_password: str = Pw
    confirm_password: str = Pw


class ResetIn(BaseModel):
    email: EmailStr
    otp: str = Field(max_length=12)
    new_password: str = Pw
    confirm_password: str = Pw


def user_out(u: User) -> dict:
    return {"id": u.id, "login_id": u.login_id, "email": u.email, "role": u.role, "active": u.active}


@router.post("/signup", status_code=201)
def signup(body: SignupIn, request: Request, db: Session = Depends(get_db)):
    ratelimit.check(f"signup:{ratelimit.client_ip(request)}", limit=10, window_seconds=3600)
    if not 6 <= len(body.login_id) <= 12:
        raise HTTPException(422, "Login ID must be between 6 and 12 characters")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", body.login_id):
        raise HTTPException(422, "Login ID may only contain letters, numbers, _ . -")
    if problem := password_problem(body.password):
        raise HTTPException(422, problem)
    if body.password != body.confirm_password:
        raise HTTPException(422, "Passwords do not match")
    if db.scalar(select(User).where(func.lower(User.login_id) == body.login_id.lower())):
        raise HTTPException(409, "Login ID already exists")
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "Email already registered")
    # the first person to sign up owns the system; everyone after starts as warehouse staff until an admin promotes them
    first = (db.scalar(select(func.count()).select_from(User)) or 0) == 0
    user = User(login_id=body.login_id, email=body.email.lower(), password_hash=hash_secret(body.password),
                role="admin" if first else "staff")
    db.add(user)
    db.flush()
    audit.record(db, user, "signup", "user", user.id, user.login_id, detail=f"role {user.role}")
    db.commit()
    return {"token": create_token(user.id), "user": user_out(user)}


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = ratelimit.client_ip(request)
    ratelimit.check(f"login-ip:{ip}", limit=60, window_seconds=300)
    ratelimit.check(f"login:{ip}:{body.login_id.lower()}", limit=10, window_seconds=300)
    user = db.scalar(select(User).where(func.lower(User.login_id) == body.login_id.lower()))
    if not user or not verify_secret(body.password, user.password_hash):
        raise HTTPException(401, "Invalid Login Id or Password")
    if not user.active:
        raise HTTPException(403, "This account has been deactivated. Ask an administrator.")
    return {"token": create_token(user.id), "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.put("/me")
def update_profile(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email, User.id != user.id)):
        raise HTTPException(409, "Email already registered")
    old = user.email
    user.email = email
    if old != email:
        audit.record(db, user, "update", "user", user.id, user.login_id, changes={"email": [old, email]})
    db.commit()
    return user_out(user)


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ratelimit.check(f"chpw:{user.id}", limit=10, window_seconds=900)
    if not verify_secret(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if problem := password_problem(body.new_password):
        raise HTTPException(422, problem)
    if body.new_password != body.confirm_password:
        raise HTTPException(422, "Passwords do not match")
    if verify_secret(body.new_password, user.password_hash):
        raise HTTPException(422, "Choose a password different from the current one")
    user.password_hash = hash_secret(body.new_password)
    audit.record(db, user, "password", "user", user.id, user.login_id, detail="password changed")
    db.commit()
    return {"message": "Password changed"}


def _h(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


@router.post("/forgot-password")
def forgot(body: ForgotIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    email = body.email.lower()
    ip = ratelimit.client_ip(request)
    ratelimit.check(f"forgot:{email}", limit=3, window_seconds=900)  # nobody can flood one inbox
    ratelimit.check(f"forgot-ip:{ip}", limit=10, window_seconds=900)
    user = db.scalar(select(User).where(User.email == email))
    if user and user.active:
        code = f"{secrets.randbelow(1_000_000):06d}"
        db.add(OtpCode(email=email, code_hash=_h(code), expires_at=utcnow() + timedelta(minutes=10)))
        db.commit()
        # sent after the response, so the reply takes the same time whether or not the address exists
        background.add_task(send_otp, email, code)
    # same answer either way so emails can't be enumerated
    return {"message": "If that email is registered, a 6-digit code has been sent."}


@router.post("/reset-password")
def reset(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    ip = ratelimit.client_ip(request)
    ratelimit.check(f"reset:{email}", limit=10, window_seconds=900)
    ratelimit.check(f"reset-ip:{ip}", limit=30, window_seconds=900)
    if problem := password_problem(body.new_password):
        raise HTTPException(422, problem)
    if body.new_password != body.confirm_password:
        raise HTTPException(422, "Passwords do not match")
    otp = db.scalar(
        select(OtpCode)
        .where(OtpCode.email == email, OtpCode.used.is_(False))
        .order_by(OtpCode.id.desc())
    )
    if not otp or otp.expires_at < utcnow() or otp.attempts >= 5:
        raise HTTPException(400, "Code expired or invalid - request a new one")
    if not secrets.compare_digest(otp.code_hash, _h(body.otp.strip())):
        otp.attempts += 1
        db.commit()
        raise HTTPException(400, "Incorrect code")
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        raise HTTPException(400, "Code expired or invalid - request a new one")
    user.password_hash = hash_secret(body.new_password)
    otp.used = True
    audit.record(db, user, "password", "user", user.id, user.login_id, detail="password reset with a one-time code")
    db.commit()
    return {"message": "Password updated. You can sign in now."}
