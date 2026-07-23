import axios from "axios";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { LayoutDashboard, PlusCircle, ListChecks, NotebookPen, LogOut, ArrowLeft } from "lucide-react";
import { RequireAuth } from "../../lib/auth";
import { TRADER_TOKEN_KEY } from "../Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const TABS = [
  { to: "/journal", end: true, label: "Dashboard", Icon: LayoutDashboard },
  { to: "/journal/new", end: false, label: "New Trade", Icon: PlusCircle },
  { to: "/journal/trades", end: false, label: "Trade Log", Icon: ListChecks },
  { to: "/journal/reviews", end: false, label: "Reviews", Icon: NotebookPen },
];

const JournalLayout = () => {
  const navigate = useNavigate();

  const logout = async () => {
    try {
      await axios.post(`${API}/auth/logout`, {}, { withCredentials: true });
    } catch {
      // ignore — clearing the local token is what actually matters for the UI
    }
    localStorage.removeItem(TRADER_TOKEN_KEY);
    toast.success("Signed out.");
    navigate("/login");
  };

  return (
    <RequireAuth tokenKey={TRADER_TOKEN_KEY} loginPath="/login">
      {(user) => (
        <div className="min-h-screen bg-void grid-bg">
          <div className="border-b border-white/10 backdrop-blur-xl bg-void/70 sticky top-0 z-20">
            <div className="container-x flex items-center justify-between h-16">
              <div className="flex items-center gap-3">
                <span className="font-display font-extrabold text-white tracking-tight">Sapphire</span>
                <span className="font-mono-ui text-[10px] uppercase tracking-[0.2em] text-sapphire-light">Trading Journal</span>
              </div>
              <div className="flex items-center gap-4">
                <Link to="/" className="hidden sm:inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-white transition-colors">
                  <ArrowLeft size={14} /> Site
                </Link>
                <span className="hidden sm:block text-sm text-slate-500">{user?.email}</span>
                <button onClick={logout} className="btn-ghost !px-4 !py-2 text-sm" data-testid="journal-logout-btn">
                  <LogOut size={14} /> Logout
                </button>
              </div>
            </div>
            <div className="container-x flex items-center gap-1 pb-3">
              {TABS.map(({ to, end, label, Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    `inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-medium transition-colors ${
                      isActive ? "bg-sapphire/15 text-sapphire-light border border-sapphire/30" : "text-slate-400 hover:text-white border border-transparent"
                    }`
                  }
                  data-testid={`journal-tab-${label.toLowerCase().replace(/\s+/g, "-")}`}
                >
                  <Icon size={15} /> {label}
                </NavLink>
              ))}
            </div>
          </div>

          <div className="container-x py-8">
            <Outlet context={{ user }} />
          </div>
        </div>
      )}
    </RequireAuth>
  );
};

export default JournalLayout;
