import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { toast } from "sonner";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, Pencil, LogOut, Check, X, Loader2 } from "lucide-react";
import { TRADER_TOKEN_KEY } from "../../pages/Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EASE = [0.16, 1, 0.3, 1];

const errMsg = (err, fallback) => {
  const d = err?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
};

// Rendered in place of Log In / Sign Up once Navbar's useCurrentUser()
// resolves a signed-in user. No username yet (every pre-migration account)
// shows "Set Username" instead of a handle -- the passive, non-blocking
// nudge every session after the one-time migration email, per the
// 2026-08-10 decision not to hard-gate existing accounts.
const AccountMenu = ({ user, onUserChange }) => {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) { setOpen(false); setEditing(false); }
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  const startEdit = () => { setDraft(user.username || ""); setEditing(true); };

  const saveUsername = async (e) => {
    e.preventDefault();
    const clean = draft.trim().toLowerCase();
    if (!clean) return;
    setSaving(true);
    try {
      const token = localStorage.getItem(TRADER_TOKEN_KEY);
      await axios.patch(`${API}/auth/username`, { username: clean }, { headers: { Authorization: `Bearer ${token}` } });
      toast.success("Username updated.");
      setEditing(false);
      setOpen(false);
      onUserChange();
    } catch (err) {
      toast.error(errMsg(err, "Could not update username."));
    } finally {
      setSaving(false);
    }
  };

  const logout = async () => {
    try { await axios.post(`${API}/auth/logout`, {}, { withCredentials: true }); } catch { /* best-effort */ }
    localStorage.removeItem(TRADER_TOKEN_KEY);
    setOpen(false);
    onUserChange();
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={`relative flex items-center gap-1.5 text-sm rounded-full border px-4 py-2 transition-colors duration-200 ${
          user.username
            ? "border-white/15 text-slate-200 hover:text-white hover:border-white/30"
            : "border-sapphire-light/40 text-sapphire-light hover:border-sapphire-light"
        }`}
        data-testid="nav-account-btn"
        aria-expanded={open}
      >
        {user.username ? `@${user.username}` : "Set Username"}
        <ChevronDown size={13} className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.2, ease: EASE }}
            className="absolute top-full right-0 mt-3 w-64 rounded-xl border border-white/10 bg-void/95 backdrop-blur-xl p-2 shadow-2xl shadow-black/50"
            data-testid="nav-account-menu"
          >
            {editing ? (
              <form onSubmit={saveUsername} className="p-2">
                <label className="font-mono-ui text-[10px] uppercase tracking-[0.14em] text-slate-500 block mb-2">Username</label>
                <input
                  autoFocus
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-white outline-none focus:border-sapphire-light"
                  placeholder="yourusername"
                  data-testid="nav-account-username-input"
                />
                <p className="text-[11px] text-slate-600 mt-1.5">3-20 characters — lowercase letters, numbers, underscores.</p>
                <div className="flex items-center gap-2 mt-3">
                  <button
                    type="submit"
                    disabled={saving}
                    className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg bg-sapphire-light/15 text-sapphire-light text-xs font-semibold py-2 hover:bg-sapphire-light/25 transition-colors disabled:opacity-50"
                    data-testid="nav-account-username-save"
                  >
                    {saving ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />} Save
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditing(false)}
                    className="inline-flex items-center justify-center rounded-lg border border-white/10 text-slate-400 text-xs py-2 px-3 hover:text-white transition-colors"
                    data-testid="nav-account-username-cancel"
                  >
                    <X size={13} />
                  </button>
                </div>
              </form>
            ) : (
              <>
                <div className="px-3.5 py-2.5">
                  <p className="text-sm text-white font-medium truncate">{user.username ? `@${user.username}` : "No username yet"}</p>
                  <p className="text-xs text-slate-500 truncate mt-0.5">{user.email}</p>
                </div>
                {!user.username && (
                  <button
                    onClick={startEdit}
                    className="w-full flex items-center gap-3 text-left px-3.5 py-2.5 rounded-lg text-sm text-slate-300 hover:text-white hover:bg-white/5 transition-colors duration-200"
                    data-testid="nav-account-change-username"
                  >
                    <Pencil size={15} className="text-slate-500" /> Set username
                  </button>
                )}
                <button
                  onClick={logout}
                  className="w-full flex items-center gap-3 text-left px-3.5 py-2.5 rounded-lg text-sm text-slate-300 hover:text-white hover:bg-white/5 transition-colors duration-200"
                  data-testid="nav-account-logout"
                >
                  <LogOut size={15} className="text-slate-500" /> Log out
                </button>
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default AccountMenu;
