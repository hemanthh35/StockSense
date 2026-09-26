import logging

import httpx

from .config import settings

log = logging.getLogger("stocksense.mail")
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def send_otp(email: str, code: str) -> bool:
    """Send the reset OTP through Brevo's transactional email API.
    Without a configured key the OTP is logged so the flow stays testable locally."""
    if not (settings.brevo_api_key and settings.brevo_sender_email):
        log.warning("Brevo not configured - OTP for %s is %s", email, code)
        print(f"[DEV] OTP for {email}: {code}", flush=True)
        return False
    payload = {
        "sender": {"name": settings.brevo_sender_name, "email": settings.brevo_sender_email},
        "to": [{"email": email}],
        "subject": "Your StockSense password reset code",
        "htmlContent": (
            f"<p>Your StockSense one-time code is:</p>"
            f"<h2 style='letter-spacing:4px'>{code}</h2>"
            f"<p>It expires in 10 minutes. If you didn't request this, ignore this email.</p>"
        ),
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
        print(f"[DEV] Brevo failed, OTP for {email}: {code}", flush=True)
        return False
