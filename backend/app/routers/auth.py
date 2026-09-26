import hashlib
import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..mail import send_otp
from ..models import OtpCode, User
from ..stock import utcnow
from ..security import create_token, hash_secret, password_problem, verify_secret

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupIn(BaseModel):
    login_id: str
    email: EmailStr
    password: str
    confirm_password: str


class LoginIn(BaseModel):
    login_id: str
    password: str


class ForgotIn(BaseModel):
    email: EmailStr


class ProfileIn(BaseModel):
    email: EmailStr


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class ResetIn(BaseModel):
    email: EmailStr
    otp: str
    new_password: str
    confirm_password: str


def user_out(u: User) -> dict:
    return {"id": u.id, "login_id": u.login_id, "email": u.email}


@router.post("/signup", status_code=201)
def signup(body: SignupIn, db: Session = Depends(get_db)):
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
    user = User(login_id=body.login_id, email=body.email.lower(), password_hash=hash_secret(body.password))
    db.add(user)
    db.commit()
    return {"token": create_token(user.id), "user": user_out(user)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.login_id) == body.login_id.lower()))
    if not user or not verify_secret(body.password, user.password_hash):
        raise HTTPException(401, "Invalid Login Id or Password")
    return {"token": create_token(user.id), "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.put("/me")
def update_profile(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email, User.id != user.id)):
        raise HTTPException(409, "Email already registered")
    user.email = email
    db.commit()
    return user_out(user)


@router.post("/change-password")
def change_password(body: ChangePasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_secret(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if problem := password_problem(body.new_password):
        raise HTTPException(422, problem)
    if body.new_password != body.confirm_password:
        raise HTTPException(422, "Passwords do not match")
    if verify_secret(body.new_password, user.password_hash):
        raise HTTPException(422, "Choose a password different from the current one")
    user.password_hash = hash_secret(body.new_password)
    db.commit()
    return {"message": "Password changed"}


def _h(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


@router.post("/forgot-password")
def forgot(body: ForgotIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    user = db.scalar(select(User).where(User.email == email))
    if user:
        code = f"{secrets.randbelow(1_000_000):06d}"
        db.add(OtpCode(email=email, code_hash=_h(code), expires_at=utcnow() + timedelta(minutes=10)))
        db.commit()
        send_otp(email, code)
    # same answer either way so emails can't be enumerated
    return {"message": "If that email is registered, a 6-digit code has been sent."}


@router.post("/reset-password")
def reset(body: ResetIn, db: Session = Depends(get_db)):
    if problem := password_problem(body.new_password):
        raise HTTPException(422, problem)
    if body.new_password != body.confirm_password:
        raise HTTPException(422, "Passwords do not match")
    email = body.email.lower()
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
    db.commit()
    return {"message": "Password updated. You can sign in now."}
