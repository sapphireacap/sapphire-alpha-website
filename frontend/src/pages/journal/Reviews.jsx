import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Loader2, ChevronDown, Sparkles } from "lucide-react";
import { TRADER_TOKEN_KEY } from "../Auth";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const authHeaders = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem(TRADER_TOKEN_KEY)}` } });
const errMsg = (err, fallback) => {
  const d = err?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
};

const field = "w-full bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-sapphire-light transition-colors";

const fmtR = (v) => `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(2)}R`;

const Reviews = () => {
  const [reviews, setReviews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(null);
  const [expanded, setExpanded] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/journal/reviews`, authHeaders());
      setReviews(data.reviews);
    } catch {
      toast.error("Failed to load reviews.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const generate = async (period_type) => {
    setGenerating(period_type);
    try {
      const { data } = await axios.post(`${API}/journal/reviews/generate`, { period_type }, authHeaders());
      toast.success(`${period_type === "weekly" ? "Weekly" : "Monthly"} review generated.`);
      setExpanded(data.id);
      await load();
    } catch (err) {
      toast.error(errMsg(err, "Failed to generate review."));
    } finally {
      setGenerating(null);
    }
  };

  return (
    <div data-testid="journal-reviews">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <h1 className="font-display text-2xl font-bold text-white">Reviews</h1>
        <div className="flex gap-3">
          <button onClick={() => generate("weekly")} disabled={generating !== null} className="btn-ghost !px-4 !py-2 text-sm disabled:opacity-70" data-testid="generate-weekly-btn">
            {generating === "weekly" ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} This Week
          </button>
          <button onClick={() => generate("monthly")} disabled={generating !== null} className="btn-ghost !px-4 !py-2 text-sm disabled:opacity-70" data-testid="generate-monthly-btn">
            {generating === "monthly" ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} This Month
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-24 text-slate-500 gap-3"><Loader2 className="animate-spin" size={18} /> Loading…</div>
      ) : reviews.length === 0 ? (
        <div className="glass rounded-2xl py-20 text-center text-slate-500">No reviews yet — generate one above.</div>
      ) : (
        <div className="space-y-3">
          {reviews.map((r) => (
            <ReviewCard key={r.id} review={r} isOpen={expanded === r.id} onToggle={() => setExpanded(expanded === r.id ? null : r.id)} onSaved={load} />
          ))}
        </div>
      )}
    </div>
  );
};

const ReviewCard = ({ review, isOpen, onToggle, onSaved }) => {
  const [reflection, setReflection] = useState(review.reflection || "");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await axios.put(`${API}/journal/reviews/${review.id}`, { reflection }, authHeaders());
      toast.success("Reflection saved.");
      onSaved();
    } catch (err) {
      toast.error(errMsg(err, "Failed to save."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="glass rounded-2xl overflow-hidden">
      <button onClick={onToggle} className="w-full flex items-center justify-between px-6 py-4 hover:bg-white/[0.03] transition-colors" data-testid={`review-toggle-${review.id}`}>
        <span className="flex items-center gap-4">
          <span className="font-mono-ui text-[10px] uppercase tracking-wider text-sapphire-light">{review.period_type}</span>
          <span className="text-sm text-white">{review.period_start} — {review.period_end}</span>
          <span className="font-mono-ui text-xs text-slate-500">{review.kpis.trade_count} trades</span>
        </span>
        <span className="flex items-center gap-3">
          <span className={`font-mono-ui text-sm ${Number(review.kpis.expectancy_r) >= 0 ? "text-emerald-300" : "text-red-300"}`}>{fmtR(review.kpis.expectancy_r)}</span>
          <ChevronDown size={16} className={`text-slate-500 transition-transform ${isOpen ? "rotate-180" : ""}`} />
        </span>
      </button>
      {isOpen && (
        <div className="px-6 pb-6 pt-1">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
            {[
              ["Win Rate", `${(Number(review.kpis.win_rate) * 100).toFixed(0)}%`],
              ["Profit Factor", Number(review.kpis.profit_factor).toFixed(2)],
              ["Max Drawdown", fmtR(review.kpis.max_drawdown_r)],
              ["Rule Adherence", `${(Number(review.kpis.rule_adherence_rate) * 100).toFixed(0)}%`],
            ].map(([l, v]) => (
              <div key={l} className="bg-white/[0.03] border border-white/10 rounded-lg p-3">
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">{l}</p>
                <p className="text-sm font-semibold text-white">{v}</p>
              </div>
            ))}
          </div>
          {review.kpis.low_sample_size && (
            <p className="text-xs text-amber-300 mb-4">Low sample size — fewer than 20 trades this period.</p>
          )}
          {Object.keys(review.emotion_distribution || {}).length > 0 && (
            <div className="mb-5">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Emotions</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(review.emotion_distribution).map(([tag, count]) => (
                  <span key={tag} className="text-xs text-slate-300 bg-white/5 border border-white/10 rounded-full px-3 py-1">{tag} × {count}</span>
                ))}
              </div>
            </div>
          )}
          <label className="text-[10px] uppercase tracking-wider text-slate-500 block mb-1.5">Reflection</label>
          <textarea value={reflection} onChange={(e) => setReflection(e.target.value)} rows={4} className={field} placeholder="What went well, what didn't, what to adjust next period" data-testid={`review-reflection-${review.id}`} />
          <button onClick={save} disabled={saving} className="btn-sapphire mt-3 disabled:opacity-70" data-testid={`review-save-${review.id}`}>
            {saving ? <><Loader2 size={16} className="animate-spin" /> Saving</> : "Save Reflection"}
          </button>
        </div>
      )}
    </div>
  );
};

export default Reviews;
