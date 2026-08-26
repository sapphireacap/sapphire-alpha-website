"""
Single source of truth for "who gets to see full Black Box detail"
(strategy rules, backtest results, live signals/performance numbers).
Everyone else sees a locked/"Coming Soon" shape from the same endpoints --
see blackbox_options_routes.py / blackbox_equity_routes.py's `_gate()`.

Deliberately just an email allowlist, not a role/flag on the user doc --
this is a single named account's early-access view, not a subscription
tier with its own signup flow.
"""
OWNER_EMAILS = {"prithvihq@gmail.com"}


def is_owner(user: dict | None) -> bool:
    if not user:
        return False
    email = (user.get("email") or "").strip().lower()
    return email in OWNER_EMAILS
