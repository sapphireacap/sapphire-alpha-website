import { useRef, useState } from "react";
import axios from "axios";
import { ArrowRight, CheckCircle2, Loader2, Mail } from "lucide-react";
import { CONTACT, SITE } from "@/content/homepage";
import Reveal from "./Reveal";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const EMPTY = { name: "", email: "", company: "", message: "", website: "" };

const inputClass =
  "w-full min-w-0 min-h-[48px] rounded-lg border border-white/15 bg-white/[0.03] focus:border-sapphire-light focus:bg-white/[0.05] outline-none text-white font-light px-4 py-3 placeholder:text-slate-400 transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#8fb2f5] aria-[invalid=true]:border-red-400";

const Field = ({ id, label, optional, error, children }) => (
  <div>
    <label htmlFor={id} className="label-mono block mb-2.5">
      {label} {optional && <span className="normal-case tracking-normal">{optional}</span>}
    </label>
    {children}
    {error && (
      <p id={`${id}-error`} className="mt-2 text-sm text-red-300">
        {error}
      </p>
    )}
  </div>
);

export const Contact = () => {
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [status, setStatus] = useState("idle"); // idle | sending | sent | error | limited
  const openedAt = useRef(Date.now());

  const set = (k) => (e) => {
    setForm((f) => ({ ...f, [k]: e.target.value }));
    if (errors[k]) setErrors((x) => ({ ...x, [k]: undefined }));
  };

  const validate = () => {
    const e = {};
    if (!form.name.trim()) e.name = CONTACT.errors.name;
    if (!EMAIL_RE.test(form.email.trim())) e.email = CONTACT.errors.email;
    if (!form.message.trim()) e.message = CONTACT.errors.message;
    return e;
  };

  const submit = async (ev) => {
    ev.preventDefault();
    const e = validate();
    setErrors(e);
    if (Object.keys(e).length) {
      document.getElementById(`contact-${Object.keys(e)[0]}`)?.focus();
      return;
    }
    setStatus("sending");
    try {
      await axios.post(`${API}/contact`, {
        name: form.name.trim(),
        email: form.email.trim(),
        company: form.company.trim() || null,
        message: form.message.trim(),
        website: form.website,
        elapsed_ms: Date.now() - openedAt.current,
      });
      setForm(EMPTY);
      setStatus("sent");
    } catch (err) {
      setStatus(err?.response?.status === 429 ? "limited" : "error");
    }
  };

  const sent = status === "sent";

  return (
    <section id="contact" aria-labelledby="contact-heading" className="relative section-y" data-testid="contact-section">
      <div className="container-x relative">
        <div className="flex flex-col lg:grid lg:grid-cols-12 gap-12 md:gap-16">
          <Reveal className="lg:col-span-5">
            <p className="label-mono mb-6">{CONTACT.label}</p>
            <h2 id="contact-heading" className="font-display font-normal tracking-[-0.015em] text-bone text-[2.25rem] md:text-6xl leading-[1.04]">
              {CONTACT.heading}
            </h2>
            <p className="mt-6 text-base md:text-lg font-light text-bone/80 max-w-md">{CONTACT.intro}</p>
            <a
              href={`mailto:${SITE.email}`}
              className="mt-8 inline-flex min-h-[44px] items-center gap-3 text-sapphire-light hover:text-white transition-colors duration-200 font-mono-ui text-sm"
              data-testid="contact-email-link"
            >
              <Mail size={16} aria-hidden="true" /> {SITE.email}
            </a>
          </Reveal>

          <Reveal delay={0.1} className="lg:col-span-7">
            {sent ? (
              <div role="status" className="glass rounded-3xl p-8 md:p-14" data-testid="contact-success">
                <CheckCircle2 className="text-emerald-300" size={28} aria-hidden="true" />
                <p className="mt-5 text-xl md:text-2xl text-bone">{CONTACT.success}</p>
              </div>
            ) : (
              <form onSubmit={submit} noValidate className="w-full min-w-0 glass rounded-3xl p-8 md:p-14 space-y-8" data-testid="contact-form">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-8 min-w-0">
                  <Field id="contact-name" label={CONTACT.fields.name} error={errors.name}>
                    <input
                      id="contact-name" name="name" autoComplete="name" required
                      value={form.name} onChange={set("name")} placeholder="Jane Doe"
                      aria-invalid={!!errors.name} aria-describedby={errors.name ? "contact-name-error" : undefined}
                      className={inputClass} data-testid="contact-name"
                    />
                  </Field>
                  <Field id="contact-email" label={CONTACT.fields.email} error={errors.email}>
                    <input
                      id="contact-email" name="email" type="email" autoComplete="email" required
                      value={form.email} onChange={set("email")} placeholder="jane@firm.com"
                      aria-invalid={!!errors.email} aria-describedby={errors.email ? "contact-email-error" : undefined}
                      className={inputClass} data-testid="contact-email"
                    />
                  </Field>
                </div>
                <Field id="contact-company" label={CONTACT.fields.company} optional={CONTACT.fields.optional}>
                  <input
                    id="contact-company" name="company" autoComplete="organization"
                    value={form.company} onChange={set("company")} placeholder="Firm / Fund"
                    className={inputClass} data-testid="contact-company"
                  />
                </Field>
                <Field id="contact-message" label={CONTACT.fields.message} error={errors.message}>
                  <textarea
                    id="contact-message" name="message" required rows={4} maxLength={4000}
                    value={form.message} onChange={set("message")} placeholder={CONTACT.fields.messagePlaceholder}
                    aria-invalid={!!errors.message} aria-describedby={errors.message ? "contact-message-error" : undefined}
                    className={`${inputClass} resize-none`} data-testid="contact-message"
                  />
                </Field>

                {/* Spam trap: invisible to people and to assistive tech. */}
                <div aria-hidden="true" style={{ position: "absolute", left: "-10000px", width: 1, height: 1, overflow: "hidden" }}>
                  <label htmlFor="contact-website">Leave this empty</label>
                  <input id="contact-website" name="website" tabIndex={-1} autoComplete="off" value={form.website} onChange={set("website")} />
                </div>

                <div aria-live="polite" className="min-h-[1.5rem]">
                  {status === "error" && <p className="text-sm text-red-300" data-testid="contact-error">{CONTACT.error}</p>}
                  {status === "limited" && <p className="text-sm text-red-300" data-testid="contact-error">{CONTACT.rateLimited}</p>}
                </div>

                <button
                  type="submit" disabled={status === "sending"}
                  className="btn-sapphire w-full sm:w-auto min-h-[48px] disabled:opacity-70"
                  data-testid="contact-submit-btn"
                >
                  {status === "sending" ? (<><Loader2 size={16} className="animate-spin" aria-hidden="true" /> {CONTACT.sending}</>) : (<>{CONTACT.submit} <ArrowRight size={16} aria-hidden="true" /></>)}
                </button>
              </form>
            )}
          </Reveal>
        </div>
      </div>
    </section>
  );
};

export default Contact;
