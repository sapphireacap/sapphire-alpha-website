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
EMAIL_ADDRESS = (os.environ.get("DEFINEDGE_OTP_EMAIL_ADDRESS") or "").strip() or None
# Google DISPLAYS an app password as four space-separated groups
# ("abcd efgh ijkl mnop") but the actual secret is the 16 characters with
# no spaces -- pasting it exactly as shown is an easy and completely
# invisible way to get [AUTHENTICATIONFAILED] back from IMAP. Spaces are
# stripped here so both forms work. (Safe for this specific credential:
# Google app passwords are 16 lowercase letters and never contain a real
# space; this is not a general-purpose password transform.)
EMAIL_APP_PASSWORD = (os.environ.get("DEFINEDGE_OTP_EMAIL_APP_PASSWORD") or "").replace(" ", "").strip() or None

# Email delivery isn't instant -- poll for a bit rather than checking once
# right after trigger_otp() and giving up.
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 90
# Definedge's real template (confirmed live, 2026-08-10): "Please use OTP
# code XXXXXX to login to Definedge Securities Application...". Anchored
# on "OTP code" specifically -- a bare \d{4,8} match was tried first and
# confirmed live to grab a FALSE positive (a "2026" from a LibreOffice-
# generated <meta> timestamp sitting earlier in the HTML part than the
# real OTP paragraph), so phrase-anchoring is required, not optional.
# The bare-digit pattern stays as a fallback only, in case Definedge ever
# changes this wording without changing the underlying OTP concept.
OTP_PHRASE_PATTERN = re.compile(r"otp\s*(?:code)?\s*(?:is|:|-)?\s*(\d{4,8})", re.IGNORECASE)
OTP_FALLBACK_PATTERN = re.compile(r"\b(\d{4,8})\b")


class DefinedgeOtpEmailError(Exception):
    """Mailbox/config problems -- safe to show a caller."""


class DefinedgeOtpMailboxAuthError(DefinedgeOtpEmailError):
    """The mailbox rejected our credentials. Unlike every other failure in
    here this one is PERMANENT -- no amount of polling fixes a revoked or
    mistyped app password -- so fetch_otp() gives up on it immediately
    instead of burning the full POLL_TIMEOUT_SECONDS. Confirmed live
    2026-08-12: a dead app password spent 91s retrying
    [AUTHENTICATIONFAILED] before reporting anything."""


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
    texts = (subject, body)

    # Phrase-anchored first, across both subject and body -- the only
    # reliable match given the false-positive risk from HTML head/meta
    # content (see OTP_PHRASE_PATTERN's comment).
    for text in texts:
        match = OTP_PHRASE_PATTERN.search(text)
        if match:
            return match.group(1)

    # Fallback: bare digit run, but only within the HTML/text BODY's tag
    # stripped down to visible text, not the raw markup -- reduces (does
    # not eliminate) the odds of matching a metadata timestamp instead of
    # the real code.
    visible = re.sub(r"<[^>]+>", " ", body)
    match = OTP_FALLBACK_PATTERN.search(visible)
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
    except Exception as e:  # noqa: BLE001
        raise DefinedgeOtpEmailError(f"Could not reach the OTP mailbox host: {e}") from e

    try:
        conn.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
    except imaplib.IMAP4.error as e:
        # Wrong/revoked app password, 2FA turned off, IMAP disabled on the
        # account -- all permanent, all reported here as IMAP4.error.
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
        raise DefinedgeOtpMailboxAuthError(
            f"The OTP mailbox rejected our credentials ({e}). The Gmail App Password for "
            f"{EMAIL_ADDRESS} is most likely revoked or wrong -- generate a new one and update "
            f"DEFINEDGE_OTP_EMAIL_APP_PASSWORD."
        ) from e
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
    blocking I/O -- runs in a thread so it doesn't stall the event loop.

    Retries are for the ONE thing that legitimately needs waiting out: the
    mail not having landed yet. A credential rejection is raised straight
    through instead (see DefinedgeOtpMailboxAuthError)."""
    if not configured():
        raise DefinedgeOtpEmailError(
            "Definedge OTP mailbox is not configured (DEFINEDGE_OTP_EMAIL_ADDRESS / DEFINEDGE_OTP_EMAIL_APP_PASSWORD)."
        )
    deadline = asyncio.get_event_loop().time() + POLL_TIMEOUT_SECONDS
    last_error: Exception = DefinedgeOtpEmailError("Timed out waiting for the OTP email.")
    while asyncio.get_event_loop().time() < deadline:
        try:
            return await asyncio.to_thread(_fetch_latest_otp_sync, after)
        except DefinedgeOtpMailboxAuthError:
            raise
        except DefinedgeOtpEmailError as e:
            last_error = e
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    raise last_error
