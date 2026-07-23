import { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { TRADER_TOKEN_KEY } from "../pages/Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
export const ADMIN_TOKEN_KEY = "sac_admin_token"; // matches Admin.jsx's local TOKEN_KEY, not exported there

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
