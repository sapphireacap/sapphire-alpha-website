"""Global pause for market-data VENDOR requests (Definedge and Dhan).

While the data provider is being changed (Fyers is being added), the site must not
send requests to either vendor: no logins, no REST data calls, no instrument-master
downloads, no WebSocket connections. This is the one switch every vendor chokepoint
checks, so nothing slips through:

  Definedge  definedge_service._session_key / trigger_otp / verify_otp /
             _get_all_master / ws_credentials, and the definedge_stream loop
  Dhan       dhan_auth.get_access_token / login (every Dhan REST call and the
             WebSocket take their token from here), dhan_health.available(),
             and the dhan_master CSV download

DEFAULT: PAUSED. To resume vendor traffic set VENDOR_APIS_PAUSED=0 in the Render
environment (a redeploy applies it). Each chokepoint raises its own existing error
type (DefinedgeError / DhanAuthError / DhanMasterError) with MESSAGE, so callers'
current error handling applies unchanged, and nothing here touches Yahoo, NSE or
any other non-vendor source.
"""
import os

MESSAGE = "Market-data vendor requests are paused while the data provider is being changed."
_OFF_VALUES = ("0", "false", "no", "off")


def paused() -> bool:
    return os.environ.get("VENDOR_APIS_PAUSED", "1").strip().lower() not in _OFF_VALUES
