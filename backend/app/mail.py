import logging

import httpx

from .config import settings

log = logging.getLogger("stocksense.mail")
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def configured() -> bool:
    return bool(settings.brevo_api_key and settings.brevo_sender_email)


def send_email(to: str | list[str], subject: str, html: str) -> bool:
    """Send through Brevo's transactional API. Returns True only if Brevo accepted it.
    Without configuration (or on failure) it returns False so callers can fall back to logging."""
    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        return False
    if not configured():
        log.warning("Brevo not configured - not sending %r to %s", subject, recipients)
        return False
    payload = {
        "sender": {"name": settings.brevo_sender_name, "email": settings.brevo_sender_email},
        "to": [{"email": r} for r in recipients],
        "subject": subject,
        "htmlContent": html,
    }
    try:
        r = httpx.post(
            BREVO_URL,
            json=payload,
            headers={"api-key": settings.brevo_api_key, "accept": "application/json"},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except httpx.HTTPError as e:
        log.error("Brevo send failed: %s", e)
        return False


def send_otp(email: str, code: str) -> bool:
    """Email the reset code. Without Brevo (or if it fails) the code is printed so development never blocks."""
    html = (
        "<p>Your StockSense one-time code is:</p>"
        f"<h2 style='letter-spacing:4px'>{code}</h2>"
        "<p>It expires in 10 minutes. If you didn't request this, ignore this email.</p>"
    )
    if send_email(email, "Your StockSense password reset code", html):
        return True
    print(f"[DEV] OTP for {email}: {code}", flush=True)
    return False
