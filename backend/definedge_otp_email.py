"""
Definedge OTP auto-login — reads the OTP Definedge emails on
DefinedgeService.trigger_otp() from a dedicated Gmail inbox via IMAP,
instead of a human pasting it into the admin panel each trading morning
(see Admin.jsx's DefinedgeConnect for that manual flow, which still
works and stays as the fallback if this ever misfires).

Scoped deliberately narrow: the configured mailbox is a DEDICATED inbox
for Definedge OTP mail only, not a general personal/work inbox (per
explicit setup) — this module only ever reads the newest message that
arrived at or after trigger_otp() was called, never sends mail, never
deletes/moves anything, never touches any other message in the mailbox.

IMAP, not Gmail's API, since it needs no OAuth app registration — just
an account-level App Password (requires 2FA enabled on the Google
account), the same auth model this codebase already uses for every
other machine credential (see e.g. ALPACA_API_KEY_ID's own docstring).
"""
import asyncio
import email
import imaplib
import logging
import os
import re
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

IMAP_HOST = os.environ.get("DEFINEDGE_OTP_EMAIL_IMAP_HOST", "imap.gmail.com")
EMAIL_ADDRESS = os.environ.get("DEFINEDGE_OTP_EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("DEFINEDGE_OTP_EMAIL_APP_PASSWORD")

# Email delivery isn't instant -- poll for a bit rather than checking once
# right after trigger_otp() and giving up.
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 90
# Definedge's exact OTP email copy isn't documented anywhere in this
# codebase (confirmed -- see the investigation this module came out of);
# this looks for any standalone 4-8 digit run in the subject or body,
# which covers every common OTP length without hard-coding wording that
# might not match Definedge's real template.
OTP_PATTERN = re.compile(r"\b(\d{4,8})\b")


class DefinedgeOtpEmailError(Exception):
    """Mailbox/config problems -- safe to show a caller."""


def configured() -> bool:
    return bool(EMAIL_ADDRESS and EMAIL_APP_PASSWORD)


def _decode_part(part) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _extract_body(msg) -> str:
    if msg.is_multipart():
        parts = []
        for part in msg.walk():
            disposition = str(part.get("Content-Disposition") or "")
            if part.get_content_type() in ("text/plain", "text/html") and "attachment" not in disposition:
                parts.append(_decode_part(part))
        return "\n".join(parts)
    return _decode_part(msg)


def _extract_otp(msg) -> str | None:
    subject = str(make_header(decode_header(msg.get("Subject", ""))))
    body = _extract_body(msg)
    for text in (subject, body):
        match = OTP_PATTERN.search(text)
        if match:
            return match.group(1)
    return None


def _fetch_latest_otp_sync(after: datetime) -> str:
    if not configured():
        raise DefinedgeOtpEmailError(
            "Definedge OTP mailbox is not configured (DEFINEDGE_OTP_EMAIL_ADDRESS / DEFINEDGE_OTP_EMAIL_APP_PASSWORD)."
        )
    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST)
        conn.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
    except Exception as e:  # noqa: BLE001
        raise DefinedgeOtpEmailError(f"Could not connect to the OTP mailbox: {e}") from e

    try:
        conn.select("INBOX")
        # IMAP's SINCE is date-only (no time) -- it only narrows the
        # candidate set to today onward; the real "did this arrive after
        # trigger_otp() was called" check is the per-message Date-header
        # comparison below.
        since_str = after.strftime("%d-%b-%Y")
        status, data = conn.search(None, f'(SINCE "{since_str}")')
        if status != "OK":
            raise DefinedgeOtpEmailError("IMAP search failed.")
        ids = data[0].split()
        for msg_id in reversed(ids):  # newest first
            status, msg_data = conn.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            try:
                msg_dt = parsedate_to_datetime(msg.get("Date"))
                if msg_dt.tzinfo is None:
                    msg_dt = msg_dt.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            if msg_dt < after:
                continue
            otp = _extract_otp(msg)
            if otp:
                return otp
        raise DefinedgeOtpEmailError("No OTP email has arrived yet.")
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


async def fetch_otp(after: datetime) -> str:
    """Polls the mailbox every POLL_INTERVAL_SECONDS for an OTP email
    that arrived at/after `after`, up to POLL_TIMEOUT_SECONDS. IMAP is
    blocking I/O -- runs in a thread so it doesn't stall the event loop."""
    if not configured():
        raise DefinedgeOtpEmailError(
            "Definedge OTP mailbox is not configured (DEFINEDGE_OTP_EMAIL_ADDRESS / DEFINEDGE_OTP_EMAIL_APP_PASSWORD)."
        )
    deadline = asyncio.get_event_loop().time() + POLL_TIMEOUT_SECONDS
    last_error: Exception = DefinedgeOtpEmailError("Timed out waiting for the OTP email.")
    while asyncio.get_event_loop().time() < deadline:
        try:
            return await asyncio.to_thread(_fetch_latest_otp_sync, after)
        except DefinedgeOtpEmailError as e:
            last_error = e
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    raise last_error
