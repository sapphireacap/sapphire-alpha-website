// NSE market-hours helpers, shared by the Alpha Terminal pages and the
// landing page. Kept in their own module so the landing page can use them
// without importing the whole Alpha Terminal page into its bundle.

// NSE full-day trading holidays (equity/derivatives segment). Source: NSE holiday
// circular, cross-checked against Groww/ClearTax. Needs a fresh entry set added
// each calendar year — extend NSE_HOLIDAYS with the next year's list in advance.
export const NSE_HOLIDAYS = new Set([
  // 2026
  "2026-01-26", // Republic Day
  "2026-03-03", // Holi
  "2026-03-26", // Shri Ram Navami
  "2026-03-31", // Shri Mahavir Jayanti
  "2026-04-03", // Good Friday
  "2026-04-14", // Dr. Baba Saheb Ambedkar Jayanti
  "2026-05-01", // Maharashtra Day
  "2026-05-28", // Bakri Id
  "2026-06-26", // Muharram
  "2026-09-14", // Ganesh Chaturthi
  "2026-10-02", // Mahatma Gandhi Jayanti
  "2026-10-20", // Dussehra
  "2026-11-10", // Diwali-Balipratipada
  "2026-11-24", // Prakash Gurpurb Sri Guru Nanak Dev
  "2026-12-25", // Christmas
]);

const isoDateIst = (d) => `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;

// `d` must already be shifted to IST wall-clock time (see nowIst below) and read via getUTC* getters.
export const isTradingDay = (d) => {
  const day = d.getUTCDay();
  if (day === 0 || day === 6) return false;
  return !NSE_HOLIDAYS.has(isoDateIst(d));
};

export const nowIst = () => new Date(Date.now() + 5.5 * 60 * 60 * 1000);

export const isNseSessionLive = () => {
  const now = nowIst();
  if (!isTradingDay(now)) return false;
  const mins = now.getUTCHours() * 60 + now.getUTCMinutes();
  return mins >= 9 * 60 + 15 && mins <= 15 * 60 + 30;
};

