import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useOutletContext } from "react-router-dom";
import { Loader2, X, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { TRADER_TOKEN_KEY } from "../Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const authHeaders = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem(TRADER_TOKEN_KEY)}` } });
const errMsg = (err, fallback) => {
  const d = err?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
};

const field = "w-full bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-sapphire-light transition-colors";
const selectCls = field + " [color-scheme:dark]";

const fmtDate = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }); }
  catch { return iso; }
};

const RIcon = ({ r }) => {
  if (r === null || r === undefined) return <Minus size={13} className="text-slate-500" />;
  if (r > 0) return <TrendingUp size={13} className="text-emerald-400" />;
  if (r < 0) return <TrendingDown size={13} className="text-red-400" />;
  return <Minus size={13} className="text-slate-400" />;
};

const TradeLog = () => {
  const { user } = useOutletContext();
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ setup_tag: "", strategy_family: "", status: "", date_from: "", date_to: "" });
  const [emotionFilter, setEmotionFilter] = useState("");
  const [selected, setSelected] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
      const { data } = await axios.get(`${API}/journal/trades`, { ...authHeaders(), params });
      setTrades(data.trades);
    } catch (err) {
      toast.error(errMsg(err, "Failed to load trades."));
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => { load(); }, [load]);

  const visible = emotionFilter ? trades.filter((t) => t.pre_trade_emotion === emotionFilter) : trades;

  return (
    <div data-testid="trade-log">
      <h1 className="font-display text-2xl font-bold text-white mb-6">Trade Log</h1>

      <div className="glass rounded-2xl p-5 mb-6 grid grid-cols-2 md:grid-cols-5 gap-3">
        <select value={filters.setup_tag} onChange={(e) => setFilters((f) => ({ ...f, setup_tag: e.target.value }))} style={{ colorScheme: "dark" }} className={selectCls}>
          <option value="" className="bg-surface">All Setups</option>
          {(user?.setup_tags || []).map((t) => <option key={t} value={t} className="bg-surface">{t}</option>)}
        </select>
        <select value={filters.strategy_family} onChange={(e) => setFilters((f) => ({ ...f, strategy_family: e.target.value }))} style={{ colorScheme: "dark" }} className={selectCls}>
          <option value="" className="bg-surface">All Strategies</option>
          {["straddle_sell", "iron_condor", "directional_ce", "directional_pe", "futures", "other"].map((t) => <option key={t} value={t} className="bg-surface">{t.replace(/_/g, " ")}</option>)}
        </select>
        <select value={emotionFilter} onChange={(e) => setEmotionFilter(e.target.value)} style={{ colorScheme: "dark" }} className={selectCls}>
          <option value="" className="bg-surface">All Emotions</option>
          {(user?.emotion_tags || []).map((t) => <option key={t} value={t} className="bg-surface">{t}</option>)}
        </select>
        <input type="date" value={filters.date_from} onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))} className={field} />
        <input type="date" value={filters.date_to} onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))} className={field} />
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-24 text-slate-500 gap-3"><Loader2 className="animate-spin" size={18} /> Loading…</div>
      ) : visible.length === 0 ? (
        <div className="glass rounded-2xl py-20 text-center text-slate-500">No trades match these filters.</div>
      ) : (
        <div className="glass rounded-2xl overflow-hidden">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-white/10">
                {["Entry", "Instrument", "Strategy", "Setup", "Status", "R"].map((h) => (
                  <th key={h} className="px-5 py-4 font-mono-ui text-[11px] uppercase tracking-[0.14em] text-slate-500 font-semibold whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((t) => (
                <tr key={t.id} onClick={() => setSelected(t)} className="border-b border-white/[0.05] last:border-0 hover:bg-sapphire/[0.06] cursor-pointer transition-colors" data-testid={`trade-row-${t.id}`}>
                  <td className="px-5 py-4 text-sm text-slate-300 whitespace-nowrap">{fmtDate(t.entry_time)}</td>
                  <td className="px-5 py-4 text-sm text-white font-medium">{t.instrument}</td>
                  <td className="px-5 py-4 text-sm text-slate-300">{t.strategy_family?.replace(/_/g, " ")}</td>
                  <td className="px-5 py-4 text-sm text-slate-400">{t.setup_tag || "—"}</td>
                  <td className="px-5 py-4">
                    <span className={`inline-flex rounded-full border px-2.5 py-0.5 text-[11px] uppercase tracking-wider ${t.status === "open" ? "border-amber-400/25 bg-amber-400/10 text-amber-300" : "border-white/15 text-slate-400"}`}>
                      {t.status}
                    </span>
                  </td>
                  <td className="px-5 py-4">
                    <span className="inline-flex items-center gap-1.5 text-sm font-mono-ui">
                      <RIcon r={t.r_multiple} />
                      {t.r_multiple !== null && t.r_multiple !== undefined ? Number(t.r_multiple).toFixed(2) + "R" : "—"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && <TradeDetailModal trade={selected} onClose={() => setSelected(null)} onUpdated={(t) => { setSelected(null); load(); }} />}
    </div>
  );
};

const TradeDetailModal = ({ trade, onClose, onUpdated }) => {
  const [exitTime, setExitTime] = useState(() => {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  });
  const [exitPrices, setExitPrices] = useState(() => Object.fromEntries(trade.legs.map((l) => [l.leg_id, ""])));
  const [saving, setSaving] = useState(false);

  const closeTrade = async () => {
    setSaving(true);
    try {
      const legs = trade.legs.map((l) => ({ ...l, exit_price: Number(exitPrices[l.leg_id]), exit_time: exitTime }));
      if (legs.some((l) => !exitPrices[l.leg_id])) {
        toast.error("Enter an exit price for every leg.");
        setSaving(false);
        return;
      }
      await axios.put(`${API}/journal/trades/${trade.id}`, { status: "closed", exit_time: exitTime, legs }, authHeaders());
      toast.success("Trade closed.");
      onUpdated();
    } catch (err) {
      toast.error(errMsg(err, "Failed to close trade."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div className="glass rounded-2xl p-6 md:p-8 w-full max-w-2xl max-h-[85vh] overflow-y-auto relative" onClick={(e) => e.stopPropagation()} data-testid="trade-detail-modal">
        <button onClick={onClose} className="absolute top-5 right-5 text-slate-500 hover:text-white"><X size={18} /></button>
        <h2 className="font-display text-xl font-bold text-white mb-1">{trade.instrument} · {trade.strategy_family?.replace(/_/g, " ")}</h2>
        <p className="text-xs text-slate-500 mb-6">{fmtDate(trade.entry_time)}</p>

        <div className="grid grid-cols-2 gap-4 mb-6 text-sm">
          <div><span className="text-slate-500">Position Size:</span> <span className="text-white">₹{Number(trade.position_size).toLocaleString("en-IN")}</span></div>
          <div><span className="text-slate-500">Initial Risk:</span> <span className="text-white">₹{Number(trade.initial_risk).toLocaleString("en-IN")}</span></div>
          {trade.setup_tag && <div><span className="text-slate-500">Setup:</span> <span className="text-white">{trade.setup_tag}</span></div>}
          {trade.pre_trade_emotion && <div><span className="text-slate-500">Emotion:</span> <span className="text-white">{trade.pre_trade_emotion}</span></div>}
        </div>

        {trade.thesis && (
          <div className="mb-6">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Thesis</p>
            <p className="text-sm text-slate-300">{trade.thesis}</p>
          </div>
        )}

        <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Legs</p>
        <div className="space-y-2 mb-6">
          {trade.legs.map((l) => (
            <div key={l.leg_id} className="flex items-center justify-between bg-white/[0.03] border border-white/10 rounded-lg px-4 py-2.5 text-sm">
              <span className="text-slate-300">
                {l.side.toUpperCase()} {l.qty} × {l.strike ? `${l.strike} ${l.option_type}` : "Futures"} @ {Number(l.entry_price).toFixed(2)}
              </span>
              {l.exit_price !== null && l.exit_price !== undefined && <span className="text-slate-500">exit {Number(l.exit_price).toFixed(2)}</span>}
            </div>
          ))}
        </div>

        {(trade.iv_at_entry || trade.india_vix_at_entry || trade.straddle_regime_at_entry) && (
          <div className="mb-6 flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500 font-mono-ui">
            {trade.iv_at_entry && <span>IV: <span className="text-slate-300">{(Number(trade.iv_at_entry) * 100).toFixed(1)}%</span></span>}
            {trade.india_vix_at_entry && <span>VIX: <span className="text-slate-300">{Number(trade.india_vix_at_entry).toFixed(2)}</span></span>}
            {trade.straddle_regime_at_entry && <span>Regime: <span className="text-slate-300">{trade.straddle_regime_at_entry}</span></span>}
          </div>
        )}

        {trade.status === "closed" ? (
          <div className="border-t border-white/10 pt-4 flex items-center gap-4">
            <span className="text-sm text-slate-500">Realized P&L: <span className="text-white">₹{Number(trade.realized_pnl).toLocaleString("en-IN")}</span></span>
            <span className="text-sm text-slate-500">R: <span className="text-white">{Number(trade.r_multiple).toFixed(2)}R</span></span>
          </div>
        ) : (
          <div className="border-t border-white/10 pt-4">
            <p className="font-display text-base font-bold text-white mb-3">Close Trade</p>
            <div className="space-y-2 mb-4">
              {trade.legs.map((l) => (
                <div key={l.leg_id} className="flex items-center gap-3">
                  <span className="text-xs text-slate-400 w-40 shrink-0">{l.strike ? `${l.strike} ${l.option_type}` : "Futures"}</span>
                  <input
                    value={exitPrices[l.leg_id]}
                    onChange={(e) => setExitPrices((p) => ({ ...p, [l.leg_id]: e.target.value }))}
                    className={field}
                    placeholder="Exit price"
                    data-testid={`close-leg-${l.leg_id}`}
                  />
                </div>
              ))}
            </div>
            <div className="mb-4">
              <label className="text-[10px] uppercase tracking-wider text-slate-500 block mb-1">Exit Time</label>
              <input type="datetime-local" value={exitTime} onChange={(e) => setExitTime(e.target.value)} className={field} />
            </div>
            <button onClick={closeTrade} disabled={saving} className="btn-sapphire disabled:opacity-70" data-testid="close-trade-btn">
              {saving ? <><Loader2 size={16} className="animate-spin" /> Closing</> : "Close Trade"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default TradeLog;
