import { useEffect, useState } from "react";
import axios from "axios";
import { X } from "lucide-react";
import { TRADER_TOKEN_KEY } from "../Auth";
import { compactField } from "./PnfChart";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const authHeaders = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem(TRADER_TOKEN_KEY)}` } });

const MODES = [
  { key: "RS", label: "RS" },
  { key: "STRADDLE", label: "Straddle" },
  { key: "STRANGLE", label: "Strangle" },
];

// RS legs can be any NSE/FUT/OPT instrument, so this offers the full
// segment/symbol/expiry/strike/type picker. Straddle/Strangle are always
// two option legs on the SAME underlying+expiry, so those modes lock the
// segment to OPT and only ask for what actually varies -- one shared
// symbol/expiry field, matching the reference terminal's own dialog
// (screenshots supplied by the user, 2026-08-27) rather than making the
// user re-enter the same underlying twice.
const LEG_SEGMENTS = ["NSE", "FUT", "OPT"];

// One instrument-search widget, backed by the same /pnf/instruments
// endpoint PnfChart's own toolbar already uses -- kept local to this
// modal since RS needs two independent copies of it and Straddle/
// Strangle need a segment-locked one.
function useInstrumentPicker(lockedSegment) {
  const [segment, setSegment] = useState(lockedSegment || "NSE");
  const [query, setQuery] = useState("");
  const [symbols, setSymbols] = useState([]);
  const [symbol, setSymbol] = useState("");
  const [expiries, setExpiries] = useState([]);
  const [expiry, setExpiry] = useState("");
  const [strikes, setStrikes] = useState([]);

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      axios.get(`${API}/pnf/instruments`, { params: { segment, query }, ...authHeaders() })
        .then(({ data: d }) => { if (!cancelled) setSymbols(d.symbols || []); })
        .catch(() => { if (!cancelled) setSymbols([]); });
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [segment, query]);

  useEffect(() => {
    setExpiry(""); setStrikes([]);
    if (!symbol || (segment !== "FUT" && segment !== "OPT")) { setExpiries([]); return; }
    axios.get(`${API}/pnf/instruments`, { params: { segment, symbol }, ...authHeaders() })
      .then(({ data: d }) => setExpiries(d.expiries || []))
      .catch(() => setExpiries([]));
  }, [symbol, segment]);

  useEffect(() => {
    setStrikes([]);
    if (!symbol || !expiry || segment !== "OPT") return;
    axios.get(`${API}/pnf/instruments`, { params: { segment, symbol, expiry }, ...authHeaders() })
      .then(({ data: d }) => setStrikes(d.strikes || []))
      .catch(() => setStrikes([]));
  }, [symbol, expiry, segment]);

  return {
    segment, setSegment, query, setQuery, symbols, symbol, setSymbol,
    expiries, expiry, setExpiry, strikes,
  };
}

function LegSearch({ picker, locked, label }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {label && <span className="text-[11px] text-slate-500 w-16 shrink-0">{label}</span>}
      <select
        className={compactField}
        value={picker.segment}
        disabled={!!locked}
        onChange={(e) => { picker.setSegment(e.target.value); picker.setSymbol(""); }}
      >
        {LEG_SEGMENTS.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <input
        className={compactField + " w-24"}
        value={picker.query} placeholder="Search"
        onChange={(e) => picker.setQuery(e.target.value)}
      />
      <select className={compactField + " min-w-0 max-w-[9rem]"} value={picker.symbol} onChange={(e) => picker.setSymbol(e.target.value)}>
        <option value="">Symbol…</option>
        {picker.symbols.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      {(picker.segment === "FUT" || picker.segment === "OPT") && (
        <select className={compactField} value={picker.expiry} onChange={(e) => picker.setExpiry(e.target.value)}>
          <option value="">Expiry…</option>
          {picker.expiries.map((e2) => <option key={e2} value={e2}>{e2}</option>)}
        </select>
      )}
    </div>
  );
}

// RS: two full instrument pickers (any NSE/FUT/OPT combination), each
// with its own strike+CE/PE when the leg is an option.
function RsLegFields({ picker, strike, setStrike, optionType, setOptionType, label }) {
  return (
    <div className="space-y-1.5">
      <LegSearch picker={picker} label={label} />
      {picker.segment === "OPT" && (
        <div className="flex items-center gap-2 pl-[4.5rem]">
          <select className={compactField} value={strike} onChange={(e) => setStrike(e.target.value)}>
            <option value="">Strike…</option>
            {picker.strikes.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select className={compactField} value={optionType} onChange={(e) => setOptionType(e.target.value)}>
            <option value="CE">CE</option><option value="PE">PE</option>
          </select>
        </div>
      )}
    </div>
  );
}

export const PnfComboModal = ({ open, onClose, onApply }) => {
  const [mode, setMode] = useState("RS");

  // RS mode state — two independent legs.
  const legA = useInstrumentPicker("NSE");
  const legB = useInstrumentPicker("NSE");
  const [strikeA, setStrikeA] = useState("");
  const [optionTypeA, setOptionTypeA] = useState("CE");
  const [strikeB, setStrikeB] = useState("");
  const [optionTypeB, setOptionTypeB] = useState("PE");

  // Straddle/Strangle mode state — one underlying+expiry, segment
  // locked to OPT (both legs are always options on the same series).
  const combo = useInstrumentPicker("OPT");
  const [straddleStrike, setStraddleStrike] = useState("");
  const [callStrike, setCallStrike] = useState("");
  const [putStrike, setPutStrike] = useState("");

  useEffect(() => { setStrikeA(""); }, [legA.symbol, legA.expiry]);
  useEffect(() => { setStrikeB(""); }, [legB.symbol, legB.expiry]);
  useEffect(() => { setStraddleStrike(""); setCallStrike(""); setPutStrike(""); }, [combo.symbol, combo.expiry]);

  if (!open) return null;

  const canApply = mode === "RS"
    ? legA.symbol && legB.symbol && (legA.segment !== "OPT" || strikeA) && (legB.segment !== "OPT" || strikeB)
    : mode === "STRADDLE"
      ? combo.symbol && combo.expiry && straddleStrike
      : combo.symbol && combo.expiry && callStrike && putStrike;

  const apply = () => {
    if (!canApply) return;
    if (mode === "RS") {
      onApply({
        op: "rs",
        legA: { segment: legA.segment, symbol: legA.symbol, expiry: legA.expiry || null,
                strike: legA.segment === "OPT" ? strikeA : null, optionType: legA.segment === "OPT" ? optionTypeA : null },
        legB: { segment: legB.segment, symbol: legB.symbol, expiry: legB.expiry || null,
                strike: legB.segment === "OPT" ? strikeB : null, optionType: legB.segment === "OPT" ? optionTypeB : null },
      });
    } else if (mode === "STRADDLE") {
      onApply({
        op: "straddle",
        legA: { segment: "OPT", symbol: combo.symbol, expiry: combo.expiry, strike: straddleStrike, optionType: "CE" },
        legB: { segment: "OPT", symbol: combo.symbol, expiry: combo.expiry, strike: straddleStrike, optionType: "PE" },
      });
    } else {
      onApply({
        op: "strangle",
        legA: { segment: "OPT", symbol: combo.symbol, expiry: combo.expiry, strike: callStrike, optionType: "CE" },
        legB: { segment: "OPT", symbol: combo.symbol, expiry: combo.expiry, strike: putStrike, optionType: "PE" },
      });
    }
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-xl border border-white/10 bg-[#0B1220] p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-white">Point &amp; Figure (RS / Straddle / Strangle)</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-white transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="flex items-center gap-4 mb-4">
          {MODES.map((m) => (
            <label key={m.key} className="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer">
              <input type="radio" name="combo-mode" checked={mode === m.key} onChange={() => setMode(m.key)} />
              {m.label}
            </label>
          ))}
        </div>

        {mode === "RS" && (
          <div className="space-y-3">
            <RsLegFields picker={legA} strike={strikeA} setStrike={setStrikeA} optionType={optionTypeA} setOptionType={setOptionTypeA} label="Leg A" />
            <RsLegFields picker={legB} strike={strikeB} setStrike={setStrikeB} optionType={optionTypeB} setOptionType={setOptionTypeB} label="Leg B" />
          </div>
        )}

        {(mode === "STRADDLE" || mode === "STRANGLE") && (
          <div className="space-y-2">
            <LegSearch picker={combo} locked label="Market" />
            {mode === "STRADDLE" ? (
              <div className="flex items-center gap-2 pl-[4.5rem]">
                <span className="text-[11px] text-slate-500">Strike</span>
                <select className={compactField} value={straddleStrike} onChange={(e) => setStraddleStrike(e.target.value)}>
                  <option value="">Strike…</option>
                  {combo.strikes.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            ) : (
              <div className="flex items-center gap-2 pl-[4.5rem]">
                <span className="text-[11px] text-slate-500">CE</span>
                <select className={compactField} value={callStrike} onChange={(e) => setCallStrike(e.target.value)}>
                  <option value="">Strike…</option>
                  {combo.strikes.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
                <span className="text-[11px] text-slate-500">PE</span>
                <select className={compactField} value={putStrike} onChange={(e) => setPutStrike(e.target.value)}>
                  <option value="">Strike…</option>
                  {combo.strikes.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            )}
          </div>
        )}

        <p className="text-[10px] text-slate-500 mt-4">
          Uses this chart's own interval and box-size fields — set those on the main toolbar, then hit Plot.
        </p>

        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="h-8 px-3.5 rounded-md border border-white/10 text-xs text-slate-300 hover:text-white transition-colors">
            Cancel
          </button>
          <button
            onClick={apply} disabled={!canApply}
            className="h-8 px-3.5 rounded-md bg-sapphire-light/90 hover:bg-sapphire-light text-white text-xs font-semibold transition-colors disabled:opacity-40"
          >
            Apply
          </button>
        </div>
      </div>
    </div>
  );
};

export default PnfComboModal;
