import { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useNavigate, useOutletContext } from "react-router-dom";
import { Loader2, Plus, Trash2, ChevronDown } from "lucide-react";
import { TRADER_TOKEN_KEY } from "../Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const authHeaders = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem(TRADER_TOKEN_KEY)}` } });
const errMsg = (err, fallback) => {
  const d = err?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
};

const nowLocalDatetime = () => {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
};

const emptyLeg = () => ({ strike: "", option_type: "CE", expiry: "", side: "sell", qty: "", entry_price: "" });

const field = "w-full bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-sapphire-light transition-colors";
const selectCls = field + " [color-scheme:dark]";
const label = "font-mono-ui text-[10px] uppercase tracking-[0.18em] text-slate-500 block mb-1.5";

const STRATEGY_FAMILIES = ["straddle_sell", "iron_condor", "directional_ce", "directional_pe", "futures", "other"];

const TradeEntry = () => {
  const { user } = useOutletContext();
  const navigate = useNavigate();
  const [saving, setSaving] = useState(false);
  const [showContext, setShowContext] = useState(false);

  const [form, setForm] = useState({
    instrument: "NIFTY",
    strategy_family: "straddle_sell",
    direction: "neutral",
    entry_time: nowLocalDatetime(),
    legs: [emptyLeg()],
    position_size: "",
    initial_risk: "",
  });
  const [context, setContext] = useState({ thesis: "", setup_tag: "", pre_trade_emotion: "", signals_present: [] });
  const [signalInput, setSignalInput] = useState("");

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const setCtx = (k) => (e) => setContext((c) => ({ ...c, [k]: e.target.value }));

  const updateLeg = (idx, k, value) =>
    setForm((f) => {
      const legs = [...f.legs];
      legs[idx] = { ...legs[idx], [k]: value };
      return { ...f, legs };
    });
  const addLeg = () => setForm((f) => ({ ...f, legs: [...f.legs, emptyLeg()] }));
  const removeLeg = (idx) => setForm((f) => ({ ...f, legs: f.legs.filter((_, i) => i !== idx) }));

  const addSignal = () => {
    const v = signalInput.trim();
    if (!v) return;
    setContext((c) => ({ ...c, signals_present: [...c.signals_present, v] }));
    setSignalInput("");
  };
  const removeSignal = (i) => setContext((c) => ({ ...c, signals_present: c.signals_present.filter((_, idx) => idx !== i) }));

  const completeness = [context.thesis, context.setup_tag, context.pre_trade_emotion, context.signals_present.length > 0].filter(Boolean).length;

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        instrument: form.instrument,
        strategy_family: form.strategy_family,
        direction: form.direction,
        entry_time: form.entry_time,
        legs: form.legs.map((l) => ({
          strike: l.strike ? Number(l.strike) : null,
          option_type: l.option_type || null,
          expiry: l.expiry || null,
          side: l.side,
          qty: Number(l.qty),
          entry_price: Number(l.entry_price),
          entry_time: form.entry_time,
        })),
        position_size: Number(form.position_size),
        initial_risk: Number(form.initial_risk),
        thesis: context.thesis,
        setup_tag: context.setup_tag || null,
        signals_present: context.signals_present,
        pre_trade_emotion: context.pre_trade_emotion || null,
      };
      await axios.post(`${API}/journal/trades`, payload, authHeaders());
      toast.success("Trade logged.");
      navigate("/journal/trades");
    } catch (err) {
      toast.error(errMsg(err, "Failed to save trade."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="max-w-3xl" data-testid="trade-entry-form">
      <h1 className="font-display text-2xl font-bold text-white mb-6">Log a Trade</h1>

      <div className="glass rounded-2xl p-6 md:p-8 mb-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div>
            <label className={label}>Instrument</label>
            <select value={form.instrument} onChange={set("instrument")} style={{ colorScheme: "dark" }} className={selectCls} data-testid="trade-instrument">
              {["NIFTY", "BANKNIFTY", "STOCK"].map((o) => <option key={o} value={o} className="bg-surface">{o}</option>)}
            </select>
          </div>
          <div>
            <label className={label}>Strategy</label>
            <select value={form.strategy_family} onChange={set("strategy_family")} style={{ colorScheme: "dark" }} className={selectCls} data-testid="trade-strategy">
              {STRATEGY_FAMILIES.map((o) => <option key={o} value={o} className="bg-surface">{o.replace(/_/g, " ")}</option>)}
            </select>
          </div>
          <div>
            <label className={label}>Direction</label>
            <select value={form.direction} onChange={set("direction")} style={{ colorScheme: "dark" }} className={selectCls} data-testid="trade-direction">
              {["long", "short", "neutral"].map((o) => <option key={o} value={o} className="bg-surface">{o}</option>)}
            </select>
          </div>
          <div>
            <label className={label}>Entry Time</label>
            <input type="datetime-local" value={form.entry_time} onChange={set("entry_time")} className={field} data-testid="trade-entry-time" required />
          </div>
        </div>

        <label className={label}>Legs</label>
        <div className="space-y-3 mb-4">
          {form.legs.map((leg, i) => (
            <div key={i} className="grid grid-cols-2 md:grid-cols-6 gap-2 items-end bg-white/[0.03] border border-white/10 rounded-lg p-3">
              <div>
                <label className="text-[10px] text-slate-500 block mb-1">Strike</label>
                <input value={leg.strike} onChange={(e) => updateLeg(i, "strike", e.target.value)} className={field} placeholder="24000" data-testid={`leg-${i}-strike`} />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 block mb-1">Type</label>
                <select value={leg.option_type} onChange={(e) => updateLeg(i, "option_type", e.target.value)} style={{ colorScheme: "dark" }} className={selectCls}>
                  <option value="CE" className="bg-surface">CE</option>
                  <option value="PE" className="bg-surface">PE</option>
                  <option value="" className="bg-surface">Futures/Equity</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-500 block mb-1">Expiry</label>
                <input type="date" value={leg.expiry} onChange={(e) => updateLeg(i, "expiry", e.target.value)} className={field} />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 block mb-1">Side</label>
                <select value={leg.side} onChange={(e) => updateLeg(i, "side", e.target.value)} style={{ colorScheme: "dark" }} className={selectCls}>
                  <option value="buy" className="bg-surface">Buy</option>
                  <option value="sell" className="bg-surface">Sell</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-500 block mb-1">Qty</label>
                <input value={leg.qty} onChange={(e) => updateLeg(i, "qty", e.target.value)} className={field} placeholder="50" data-testid={`leg-${i}-qty`} required />
              </div>
              <div className="flex gap-1.5">
                <div className="flex-1">
                  <label className="text-[10px] text-slate-500 block mb-1">Entry Price</label>
                  <input value={leg.entry_price} onChange={(e) => updateLeg(i, "entry_price", e.target.value)} className={field} placeholder="120.50" data-testid={`leg-${i}-entry-price`} required />
                </div>
                {form.legs.length > 1 && (
                  <button type="button" onClick={() => removeLeg(i)} className="text-slate-500 hover:text-red-400 transition-colors self-end pb-2">
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
        <button type="button" onClick={addLeg} className="btn-ghost !px-4 !py-2 text-sm mb-6" data-testid="add-leg-btn">
          <Plus size={14} /> Add Leg
        </button>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={label}>Position Size (₹)</label>
            <input value={form.position_size} onChange={set("position_size")} className={field} placeholder="575000" data-testid="trade-position-size" required />
          </div>
          <div>
            <label className={label}>Initial Risk (₹)</label>
            <input value={form.initial_risk} onChange={set("initial_risk")} className={field} placeholder="11500" data-testid="trade-initial-risk" required />
          </div>
        </div>
      </div>

      <div className="glass rounded-2xl overflow-hidden mb-6">
        <button
          type="button"
          onClick={() => setShowContext((s) => !s)}
          className="w-full flex items-center justify-between px-6 py-4 hover:bg-white/[0.03] transition-colors"
          data-testid="toggle-context-btn"
        >
          <span className="flex items-center gap-3">
            <span className="font-display text-base font-bold text-white">Context</span>
            <span className="font-mono-ui text-[10px] uppercase tracking-wider text-slate-500">Optional — won't block save</span>
          </span>
          <span className="flex items-center gap-3">
            <span className="font-mono-ui text-[10px] text-slate-500">{completeness}/4 filled</span>
            <ChevronDown size={16} className={`text-slate-500 transition-transform ${showContext ? "rotate-180" : ""}`} />
          </span>
        </button>
        {showContext && (
          <div className="px-6 pb-6 pt-1 space-y-5">
            <div>
              <label className={label}>Thesis</label>
              <textarea value={context.thesis} onChange={setCtx("thesis")} rows={2} className={field} placeholder="Why this trade, in a sentence" data-testid="trade-thesis" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={label}>Setup Tag</label>
                <select value={context.setup_tag} onChange={setCtx("setup_tag")} style={{ colorScheme: "dark" }} className={selectCls} data-testid="trade-setup-tag">
                  <option value="" className="bg-surface">—</option>
                  {(user?.setup_tags || []).map((t) => <option key={t} value={t} className="bg-surface">{t}</option>)}
                </select>
              </div>
              <div>
                <label className={label}>Pre-Trade Emotion</label>
                <select value={context.pre_trade_emotion} onChange={setCtx("pre_trade_emotion")} style={{ colorScheme: "dark" }} className={selectCls} data-testid="trade-emotion">
                  <option value="" className="bg-surface">—</option>
                  {(user?.emotion_tags || []).map((t) => <option key={t} value={t} className="bg-surface">{t}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className={label}>Signals Present</label>
              <div className="flex flex-wrap gap-2 mb-2">
                {context.signals_present.map((s, i) => (
                  <span key={i} className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-slate-300">
                    {s}
                    <button type="button" onClick={() => removeSignal(i)} className="text-slate-500 hover:text-red-400">×</button>
                  </span>
                ))}
              </div>
              <div className="flex gap-2">
                <input
                  value={signalInput}
                  onChange={(e) => setSignalInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSignal(); } }}
                  className={field}
                  placeholder="Type a signal, press Enter"
                />
                <button type="button" onClick={addSignal} className="btn-ghost !px-4 !py-2 text-sm">Add</button>
              </div>
            </div>
          </div>
        )}
      </div>

      <button type="submit" disabled={saving} className="btn-sapphire disabled:opacity-70" data-testid="trade-submit-btn">
        {saving ? <><Loader2 size={16} className="animate-spin" /> Saving</> : "Log Trade"}
      </button>
    </form>
  );
};

export default TradeEntry;
