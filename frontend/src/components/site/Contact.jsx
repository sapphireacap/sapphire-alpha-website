import { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { ArrowRight, Loader2, Mail } from "lucide-react";
import Reveal from "./Reveal";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const Contact = () => {
  const [form, setForm] = useState({ name: "", email: "", company: "", message: "" });
  const [loading, setLoading] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim() || !form.message.trim()) {
      toast.error("Please add your name and a message.");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      toast.error("Please enter a valid email address.");
      return;
    }
    setLoading(true);
    try {
      await axios.post(`${API}/contact`, form);
      toast.success("Message sent. We'll be in touch shortly.");
      setForm({ name: "", email: "", company: "", message: "" });
    } catch {
      toast.error("Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const field =
    "w-full bg-transparent border-b border-white/15 focus:border-sapphire-light outline-none text-white font-light py-3 placeholder:text-slate-600 transition-colors duration-300";

  return (
    <section id="contact" className="relative py-24 md:py-40 border-t border-white/5" data-testid="contact-section">
      <div className="absolute inset-0 grid-bg opacity-30 pointer-events-none" />
      <div className="container-x relative">
        <div className="grid grid-cols-12 gap-12 md:gap-16">
          <Reveal className="col-span-12 lg:col-span-5">
            <p className="overline mb-6">Contact</p>
            <h2 className="font-display font-black tracking-tighter text-white text-4xl md:text-6xl leading-[1.0]">
              Let&apos;s build something meaningful.
            </h2>
            <p className="mt-6 text-base md:text-lg font-light text-slate-400 max-w-md">
              Whether you&apos;re interested in our research, collaborations, or future
              initiatives, we&apos;d love to hear from you.
            </p>
            <a
              href="mailto:contact@sapphirealphacapital.com"
              className="mt-10 inline-flex items-center gap-3 text-sapphire-light hover:text-white transition-colors font-mono-ui text-sm"
              data-testid="contact-email-link"
            >
              <Mail size={16} /> contact@sapphirealphacapital.com
            </a>
          </Reveal>

          <Reveal delay={0.15} className="col-span-12 lg:col-span-7">
            <form onSubmit={submit} className="glass rounded-3xl p-8 md:p-12 space-y-8" data-testid="contact-form">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-8">
                <div>
                  <label className="overline !text-slate-500 block mb-2">Name</label>
                  <input value={form.name} onChange={set("name")} placeholder="Jane Doe" className={field} data-testid="contact-name" />
                </div>
                <div>
                  <label className="overline !text-slate-500 block mb-2">Email</label>
                  <input type="email" value={form.email} onChange={set("email")} placeholder="jane@firm.com" className={field} data-testid="contact-email" />
                </div>
              </div>
              <div>
                <label className="overline !text-slate-500 block mb-2">Company <span className="normal-case tracking-normal">(optional)</span></label>
                <input value={form.company} onChange={set("company")} placeholder="Firm / Fund" className={field} data-testid="contact-company" />
              </div>
              <div>
                <label className="overline !text-slate-500 block mb-2">Message</label>
                <textarea value={form.message} onChange={set("message")} placeholder="Tell us what you're interested in…" rows={4} className={`${field} resize-none`} data-testid="contact-message" />
              </div>
              <button type="submit" disabled={loading} className="btn-sapphire w-full sm:w-auto disabled:opacity-70" data-testid="contact-submit-btn">
                {loading ? (<><Loader2 size={16} className="animate-spin" /> Sending</>) : (<>Send Message <ArrowRight size={16} /></>)}
              </button>
            </form>
          </Reveal>
        </div>
      </div>
    </section>
  );
};

export default Contact;
