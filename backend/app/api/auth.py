import logging
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import client_ip, enforce_rate_limit
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.services.email import send_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_TOKEN_TTL_MINUTES = 30
# CSRF protection for the OAuth redirect round-trip. In-memory and short-lived --
# same pattern as the price-history cache in services/risk.py; fine for a
# single-worker deployment, and a stolen/replayed state is only useful for the ~10
# minutes before it expires or is consumed.
OAUTH_STATE_TTL_SECONDS = 600
_oauth_states: dict[str, float] = {}

# Rate limits for the unauthenticated auth endpoints -- the ones brute-forceable
# (login) or abusable against a third party (forgot-password can spam someone
# else's inbox). Checked per-IP (stops one source hammering many targets) and,
# for login/forgot-password, also per-email (stops many sources hammering one
# target, e.g. a distributed credential-stuffing attempt against one account).
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 5 * 60
REGISTER_MAX_ATTEMPTS = 5
REGISTER_WINDOW_SECONDS = 10 * 60
FORGOT_PASSWORD_MAX_ATTEMPTS = 3
FORGOT_PASSWORD_WINDOW_SECONDS = 15 * 60
RESET_PASSWORD_MAX_ATTEMPTS = 5
RESET_PASSWORD_WINDOW_SECONDS = 10 * 60


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class MessageResponse(BaseModel):
    message: str


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"register:ip:{client_ip(request)}", REGISTER_MAX_ATTEMPTS, REGISTER_WINDOW_SECONDS)

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        logger.info("Register failed, email already registered: %s", payload.email)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        auth_provider="local",
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("Registered new user id=%d email=%s", user.id, user.email)

    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"login:ip:{client_ip(request)}", LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS)
    enforce_rate_limit(f"login:email:{payload.email.lower()}", LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS)

    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        logger.info("Login failed for email=%s", payload.email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    logger.info("Login succeeded for user id=%d email=%s", user.id, user.email)
    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token)


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"forgot:ip:{client_ip(request)}", FORGOT_PASSWORD_MAX_ATTEMPTS, FORGOT_PASSWORD_WINDOW_SECONDS)
    enforce_rate_limit(
        f"forgot:email:{payload.email.lower()}", FORGOT_PASSWORD_MAX_ATTEMPTS, FORGOT_PASSWORD_WINDOW_SECONDS
    )

    # Always return the same generic message regardless of whether the email exists,
    # is Google-only, or belongs to a local account -- otherwise this endpoint could
    # be used to enumerate registered emails.
    generic_response = MessageResponse(message="If that email is registered, a reset link has been sent.")

    user = db.query(User).filter(User.email == payload.email).first()
    if not user or user.auth_provider != "local":
        logger.info("Password reset requested for unregistered or Google-only email=%s", payload.email)
        return generic_response

    token = secrets.token_urlsafe(32)
    user.reset_token = token
    user.reset_token_expires_at = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
    db.commit()

    reset_link = f"{settings.FRONTEND_BASE_URL}/reset-password.html?token={token}"
    body = (
        f"Someone requested a password reset for your Portfolio Risk Copilot account.\n\n"
        f"Reset your password here (expires in {RESET_TOKEN_TTL_MINUTES} minutes):\n{reset_link}\n\n"
        f"If you didn't request this, you can ignore this email."
    )
    try:
        send_email(user.email, "Reset your Portfolio Risk Copilot password", body)
    except Exception:
        logger.exception("Failed to send password reset email to %s", user.email)
    logger.info("Password reset token issued for user id=%d", user.id)

    return generic_response


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"reset:ip:{client_ip(request)}", RESET_PASSWORD_MAX_ATTEMPTS, RESET_PASSWORD_WINDOW_SECONDS)

    user = db.query(User).filter(User.reset_token == payload.token).first()
    if not user or not user.reset_token_expires_at or user.reset_token_expires_at < datetime.utcnow():
        logger.info("Password reset attempted with invalid or expired token")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")

    user.hashed_password = hash_password(payload.new_password)
    user.reset_token = None
    user.reset_token_expires_at = None
    db.commit()
    logger.info("Password reset completed for user id=%d", user.id)

    return MessageResponse(message="Password has been reset. You can now log in.")


@router.get("/google/login")
def google_login():
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Google sign-in is not configured")

    state = secrets.token_urlsafe(24)
    _oauth_states[state] = time.time()

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    logger.info("Redirecting to Google OAuth consent screen")
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@router.get("/google/callback")
def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    error_redirect = f"{settings.FRONTEND_BASE_URL}/index.html?oauth_error=1"

    if error or not code or not state:
        logger.warning("Google OAuth callback missing code/state or returned an error: %s", error)
        return RedirectResponse(error_redirect)

    requested_at = _oauth_states.pop(state, None)
    if requested_at is None or time.time() - requested_at > OAUTH_STATE_TTL_SECONDS:
        logger.warning("Google OAuth callback with invalid or expired state")
        return RedirectResponse(error_redirect)

    try:
        token_response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=10.0,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]

        userinfo_response = httpx.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        userinfo_response.raise_for_status()
        info = userinfo_response.json()
    except Exception:
        logger.exception("Google OAuth token exchange or userinfo fetch failed")
        return RedirectResponse(error_redirect)

    email = info.get("email")
    google_id = info.get("sub")
    if not email or not google_id or not info.get("email_verified"):
        logger.warning("Google userinfo missing email/sub or email not verified: %s", info)
        return RedirectResponse(error_redirect)

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, hashed_password=None, auth_provider="google", google_id=google_id, role="user")
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("Created new Google-auth user id=%d", user.id)
    elif user.google_id is None:
        # An existing local-password account signing in with Google for the first
        # time, using an email Google itself has verified -- link rather than reject.
        user.google_id = google_id
        db.commit()
        logger.info("Linked existing user id=%d to Google account", user.id)

    jwt_token = create_access_token(user.id, user.role)
    # Fragment, not a query param -- fragments are never sent to the server or
    # logged anywhere server-side, which matters for a value that's a bearer token.
    return RedirectResponse(f"{settings.FRONTEND_BASE_URL}/oauth-callback.html#token={jwt_token}")
