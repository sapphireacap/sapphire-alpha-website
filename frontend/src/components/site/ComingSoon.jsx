import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { ArrowRight, Check, Loader2 } from "lucide-react";
import Reveal from "./Reveal";
import ParticleField from "./ParticleField";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const ComingSoon = () => {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [count, setCount] = useState(null);

  useEffect(() => {
    axios
      .get(`${API}/waitlist/count`)
      .then((r) => setCount(r.data.count))
      .catch(() => {});
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    const valid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    if (!valid) {
      toast.error("Please enter a valid email address.");
      return;
    }
    setLoading(true);
    try {
      await axios.post(`${API}/waitlist`, { email });
      setDone(true);
      setCount((c) => (c === null ? c : c + 1));
      toast.success("You're on the list. We'll be in touch.");
      setEmail("");
    } catch (err) {
      if (err?.response?.status === 409) {
        toast.info("This email is already on the waitlist.");
      } else {
        toast.error("Something went wrong. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <section id="waitlist" className="relative py-24 md:py-40 overflow-hidden" data-testid="coming-soon-section">
      <div className="container-x">
        <Reveal className="relative glass rounded-3xl overflow-hidden px-6 py-14 md:px-20 md:py-24">
          <ParticleField density={0.00006} />
          <div className="absolute -right-20 -top-20 w-[420px] h-[420px] rounded-full bg-sapphire/15 blur-[120px] pointer-events-none" />
          <div className="relative z-10 max-w-3xl">
            <p className="overline mb-6">Coming Soon</p>
            <h2 className="font-display font-black tracking-tighter text-white text-4xl md:text-6xl leading-[1.02]">
              Platform launching soon.
            </h2>
            <p className="mt-6 text-base md:text-lg font-light text-slate-400 max-w-xl">
              Join the waitlist for early access. Be among the first to explore our
              quantitative research, systematic frameworks, and market insights.
            </p>

            <form onSubmit={submit} className="mt-10 flex flex-col sm:flex-row gap-4 max-w-xl" data-testid="waitlist-form">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter your email address"
                disabled={loading || done}
                className="flex-1 bg-transparent border-b border-white/20 focus:border-sapphire-light outline-none text-white font-mono-ui text-sm py-3 placeholder:text-slate-600 transition-colors duration-300 disabled:opacity-60"
                data-testid="waitlist-input"
              />
              <button
                type="submit"
                disabled={loading || done}
                className="btn-sapphire whitespace-nowrap disabled:opacity-70"
                data-testid="waitlist-submit-btn"
              >
                {done ? (
                  <>
                    Joined <Check size={16} />
                  </>
                ) : loading ? (
                  <>
                    <Loader2 size={16} className="animate-spin" /> Joining
                  </>
                ) : (
                  <>
                    Notify Me <ArrowRight size={16} />
                  </>
                )}
              </button>
            </form>

            <p className="mt-6 font-mono-ui text-xs text-slate-500" data-testid="waitlist-count">
              {count !== null ? `${count.toLocaleString()} on the waitlist` : "Private beta · No spam, ever."}
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  );
};

export default ComingSoon;
