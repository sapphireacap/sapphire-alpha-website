"""Circuit breaker for Dhan's Data APIs.

When the Data APIs plan lapses (DH-902) or the access token is rejected
(DH-901), every Dhan call fails the same way -- so trying Dhan first on
every chart request just adds a guaranteed-failure round trip before the
Definedge fallback. After one such failure, skip Dhan for COOLDOWN_SECONDS,
then let a single request probe it again; once the plan is renewed it
comes back on its own. DHAN_DISABLED=1 forces it off.
"""
import os
import time

COOLDOWN_SECONDS = 1800
_down_until = 0.0


def available() -> bool:
    if os.environ.get("DHAN_DISABLED", "").strip().lower() in ("1", "true", "yes"):
        return False
    return time.monotonic() >= _down_until


def is_access_failure(err) -> bool:
    return "DH-90" in str(err) or type(err).__name__ == "DhanAuthError"


def mark_failed() -> None:
    global _down_until
    _down_until = time.monotonic() + COOLDOWN_SECONDS
