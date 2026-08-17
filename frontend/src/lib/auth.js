import { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { TRADER_TOKEN_KEY } from "../pages/Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
export const ADMIN_TOKEN_KEY = "sac_admin_token"; // matches Admin.jsx's local TOKEN_KEY, not exported there

/**
 * `{ Authorization: "Bearer <token>" }` for an axios call, or `{}` if
 * nobody's signed in. Checks both token keys, same reasoning as
 * useIsAdmin/useIsSignedIn — an admin may be signed in via /admin33
 * (ADMIN_TOKEN_KEY) or as a trader account (TRADER_TOKEN_KEY).
 *
 * Exists because the Alpha Terminal module routes require an account
 * (2026-08-17), and every tool component reading one of them needs to
 * attach a token now. Several had it stripped back on 2026-08-12, when
 * those same routes were briefly public and an unauthenticated request
 * sending "Authorization: Bearer null" was harmless-but-misleading dead
 * weight — correct at the time, and a real regression once the routes
 * were gated again without restoring this on the frontend.
 */
export const authHeaders = () => {
  const token = localStorage.getItem(TRADER_TOKEN_KEY) || localStorage.getItem(ADMIN_TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
};

let interceptorInstalled = false;

/**
 * Access tokens are short-lived (15 min). Neither the admin page nor any
 * journal page ever called /auth/refresh before this — every session,
 * admin included, silently broke after 15 minutes. Install once (from
 * App.js on mount): on a 401, figures out which localStorage key the
 * failed request's own Authorization header came from, refreshes via the
 * httpOnly cookie, retries once. Never loops on the refresh call itself,
 * since that call carries no Authorization header at all.
 */
export const installAuthInterceptor = () => {
  if (interceptorInstalled) return;
  interceptorInstalled = true;

  axios.interceptors.response.use(
    (response) => response,
    async (error) => {
      const original = error.config;
      if (!original || error.response?.status !== 401 || original._retried) {
        return Promise.reject(error);
      }
      const failedToken = (original.headers?.Authorization || "").replace(/^Bearer /, "");
      if (!failedToken) return Promise.reject(error);

      let key = null;
      if (localStorage.getItem(TRADER_TOKEN_KEY) === failedToken) key = TRADER_TOKEN_KEY;
      else if (localStorage.getItem(ADMIN_TOKEN_KEY) === failedToken) key = ADMIN_TOKEN_KEY;
      if (!key) return Promise.reject(error);

      try {
        const { data } = await axios.post(`${API}/auth/refresh`, {}, { withCredentials: true });
        localStorage.setItem(key, data.access_token);
        original._retried = true;
        original.headers.Authorization = `Bearer ${data.access_token}`;
        return axios(original);
      } catch (refreshError) {
        localStorage.removeItem(key);
        return Promise.reject(error);
      }
    }
  );
};

/**
 * Shared "check token, verify via /auth/me, gate the page" pattern —
 * previously duplicated inline in Admin.jsx. `children` can be a render
 * function receiving the /auth/me user object (setup_tags/emotion_tags
 * included), so journal pages that need those don't have to re-fetch them.
 */
export const RequireAuth = ({ tokenKey, loginPath, children }) => {
  const [authed, setAuthed] = useState(null);
  const [user, setUser] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    const token = localStorage.getItem(tokenKey);
    if (!token) { setAuthed(false); return; }
    axios.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => { setUser(r.data); setAuthed(true); })
      .catch(() => { localStorage.removeItem(tokenKey); setAuthed(false); });
  }, [tokenKey]);

  useEffect(() => {
    if (authed === false) navigate(loginPath, { replace: true });
  }, [authed, loginPath, navigate]);

  if (authed === null) {
    return (
      <div className="min-h-screen bg-void flex items-center justify-center text-slate-500">
        <Loader2 className="animate-spin" />
      </div>
    );
  }
  if (!authed) return null;
  return typeof children === "function" ? children(user) : children;
};

/**
 * Non-redirecting admin check — for greying out UI (an Alpha Terminal
 * directory card, say) rather than gating a whole page. Checks both
 * token keys since an admin may be signed in via /admin33 (ADMIN_TOKEN_KEY)
 * or as a trader account whose role happens to be "admin" (TRADER_TOKEN_KEY,
 * same precedent RequirePnfAccess's role check uses). Returns null while
 * loading, then a real boolean — never redirects, never blocks.
 */
export const useIsAdmin = () => {
  const [isAdmin, setIsAdmin] = useState(null);

  useEffect(() => {
    const token = localStorage.getItem(ADMIN_TOKEN_KEY) || localStorage.getItem(TRADER_TOKEN_KEY);
    if (!token) { setIsAdmin(false); return; }
    axios.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => setIsAdmin(r.data.role === "admin"))
      .catch(() => setIsAdmin(false));
  }, []);

  return isAdmin;
};

/**
 * Non-redirecting, non-blocking session check for chrome that should just
 * reflect whoever's signed in (the navbar's account menu) rather than gate
 * a page. `null` covers both "still loading" and "signed out" -- callers
 * that need to tell those apart don't exist yet; the navbar just falls
 * back to Log In / Sign Up either way. Returns [user, refresh] so a caller
 * can re-pull /auth/me after an action that changes it (logout, a
 * username update) without a full remount.
 */
export const useCurrentUser = () => {
  const [user, setUser] = useState(null);

  const refresh = () => {
    const token = localStorage.getItem(TRADER_TOKEN_KEY);
    if (!token) { setUser(null); return; }
    axios.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => setUser(r.data))
      .catch(() => { localStorage.removeItem(TRADER_TOKEN_KEY); setUser(null); });
  };

  useEffect(() => { refresh(); }, []);

  return [user, refresh];
};

/**
 * Non-redirecting, non-blocking "is anyone signed in?" check — the
 * Alpha Terminal counterpart to useIsAdmin, for greying out module cards
 * rather than gating a whole page.
 *
 * Returns null while resolving, then a real boolean. The null state is
 * load-bearing here: treating "still checking" as signed-out would flash
 * every gated card into its locked state on every page load, then unlock
 * them a moment later. Callers render the locked treatment only once this
 * is exactly `false`.
 *
 * Checks both token keys for the same reason useIsAdmin does — an admin
 * may be signed in via /admin33 rather than as a trader.
 */
export const useIsSignedIn = () => {
  const [signedIn, setSignedIn] = useState(null);

  useEffect(() => {
    const token = localStorage.getItem(TRADER_TOKEN_KEY) || localStorage.getItem(ADMIN_TOKEN_KEY);
    if (!token) { setSignedIn(false); return; }
    axios.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then(() => setSignedIn(true))
      .catch(() => setSignedIn(false));
  }, []);

  return signedIn;
};

/**
 * P&F Studio's gate: requires a signed-in trader with an active
 * pnf_access_until (or an admin). Anyone else is bounced to the /pnf-studio
 * marketing/subscribe page rather than /login, since that page is what
 * explains why they don't have access and what to do about it.
 */
export const RequirePnfAccess = ({ children }) => {
  const [state, setState] = useState(null); // null=loading | "ok" | "blocked"
  const [user, setUser] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    const token = localStorage.getItem(TRADER_TOKEN_KEY);
    if (!token) { setState("blocked"); return; }
    axios.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => {
        const hasAccess = r.data.role === "admin" ||
          (r.data.pnf_access_until && new Date(r.data.pnf_access_until) > new Date());
        setUser(r.data);
        setState(hasAccess ? "ok" : "blocked");
      })
      .catch(() => { localStorage.removeItem(TRADER_TOKEN_KEY); setState("blocked"); });
  }, []);

  useEffect(() => {
    if (state === "blocked") navigate("/pnf-studio", { replace: true });
  }, [state, navigate]);

  if (state === null) {
    return (
      <div className="min-h-screen bg-void flex items-center justify-center text-slate-500">
        <Loader2 className="animate-spin" />
      </div>
    );
  }
  if (state !== "ok") return null;
  return typeof children === "function" ? children(user) : children;
};
