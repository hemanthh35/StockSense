import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Icon, LogoMark } from '../components/icons.jsx'
import { Field } from '../components/ui.jsx'

const INK = '#3a2530'

function Rack() {
  const box = (x, y, w, h, fill) => <rect key={`${x}${y}`} x={x} y={y} width={w} height={h} rx="4" fill={fill} stroke={INK} strokeWidth="1.6" />
  return (
    <svg className="auth-rack" viewBox="0 0 400 290" fill="none" aria-hidden="true">
      {/* uprights + shelves */}
      <path d="M24 20v256M376 20v256" stroke={INK} strokeWidth="2" strokeLinecap="round" />
      <path d="M24 100h352M24 186h352M24 272h352" stroke={INK} strokeWidth="2" strokeLinecap="round" />
      {/* top shelf */}
      {box(44, 52, 70, 48, '#ffe08a')}
      {box(122, 68, 56, 32, '#b9ecd0')}
      {box(186, 40, 84, 60, '#cfc4f7')}
      {box(278, 62, 72, 38, '#b5d8ff')}
      {/* middle shelf */}
      {box(44, 130, 58, 56, '#b5d8ff')}
      {box(110, 146, 90, 40, '#ffc4b3')}
      {box(208, 120, 62, 66, '#b9ecd0')}
      {box(278, 152, 74, 34, '#ffe08a')}
      {/* bottom shelf */}
      {box(44, 216, 96, 56, '#cfc4f7')}
      {box(148, 236, 52, 36, '#ffe08a')}
      {box(208, 208, 66, 64, '#ffc4b3')}
      {box(282, 228, 70, 44, '#b9ecd0')}
      {/* labels */}
      <path d="M54 62h34M54 70h20M196 52h40M196 60h24M54 226h50M54 234h30M218 218h30" stroke={INK} strokeWidth="1.4" strokeLinecap="round" opacity=".55" />
    </svg>
  )
}

function Side() {
  return (
    <aside className="auth-side">
      <div className="brand"><LogoMark size={30} /><span>StockSense</span></div>
      <div className="auth-copy">
        <h2>Every unit, <em>accounted for.</em></h2>
        <p>Receipts, deliveries, transfers and adjustments in one ledger — with live stock and a full movement history.</p>
        <Rack />
      </div>
      <div className="auth-points">
        <span><b>Real-time</b>stock levels</span>
        <span><b>Multi-site</b>warehouses</span>
        <span><b>Full audit</b>move ledger</span>
      </div>
    </aside>
  )
}

const Shell = ({ title, lead, children }) => (
  <div className="auth">
    <Side />
    <main className="auth-main">
      <div className="auth-form">
        <div className="brand"><LogoMark size={28} /><span>StockSense</span></div>
        <h1>{title}</h1>
        <p className="lead">{lead}</p>
        {children}
      </div>
    </main>
  </div>
)

const ErrorBox = ({ msg }) => msg ? <div className="form-error"><Icon name="alert" size={16} />{msg}</div> : null

function PasswordInput({ value, onChange, placeholder, autoComplete }) {
  const [show, setShow] = useState(false)
  return (
    <div className="input-icon">
      <Icon name="lock" size={16} />
      <input type={show ? 'text' : 'password'} value={value} onChange={onChange} placeholder={placeholder} autoComplete={autoComplete} />
      <button type="button" className="icon-btn reveal" onClick={() => setShow(!show)} aria-label={show ? 'Hide password' : 'Show password'}>
        <Icon name={show ? 'eyeoff' : 'eye'} size={17} />
      </button>
    </div>
  )
}

export function Login({ onAuth }) {
  const nav = useNavigate()
  const [f, setF] = useState({ login_id: '', password: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setErr('')
    try { onAuth(await api('/auth/login', { method: 'POST', body: f })); nav('/') } catch (x) { setErr(x.message) }
    setBusy(false)
  }
  return (
    <Shell title="Welcome back" lead="Sign in to manage your stock.">
      <form className="stack" onSubmit={submit}>
        <Field label="Login ID">
          <div className="input-icon"><Icon name="user" size={16} /><input value={f.login_id} onChange={(e) => setF({ ...f, login_id: e.target.value })} placeholder="Your login ID" autoFocus autoComplete="username" /></div>
        </Field>
        <Field label="Password">
          <PasswordInput value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} placeholder="Your password" autoComplete="current-password" />
        </Field>
        <div className="row-between"><span /><Link to="/forgot" className="link small">Forgot password?</Link></div>
        <ErrorBox msg={err} />
        <button className="btn primary block" disabled={busy || !f.login_id || !f.password}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <p className="auth-alt">New to StockSense? <Link to="/signup" className="link">Create an account</Link></p>
    </Shell>
  )
}

const RULES = [
  ['9+ characters', (p) => p.length > 8],
  ['Lowercase letter', (p) => /[a-z]/.test(p)],
  ['Uppercase letter', (p) => /[A-Z]/.test(p)],
  ['Special character', (p) => /[^A-Za-z0-9]/.test(p)],
]

export function Rules({ password }) {
  return (
    <ul className="rules">
      {RULES.map(([label, test]) => (
        <li key={label} className={test(password) ? 'ok' : ''}>
          <span className="tick">{test(password) && <Icon name="check" size={10} />}</span>{label}
        </li>
      ))}
    </ul>
  )
}

export function Signup({ onAuth }) {
  const nav = useNavigate()
  const [f, setF] = useState({ login_id: '', email: '', password: '', confirm_password: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setErr('')
    try { onAuth(await api('/auth/signup', { method: 'POST', body: f })); nav('/') } catch (x) { setErr(x.message) }
    setBusy(false)
  }
  return (
    <Shell title="Create your account" lead="Start tracking inventory in a minute.">
      <form className="stack" onSubmit={submit}>
        <Field label="Login ID" hint="6–12 characters, must be unique">
          <div className="input-icon"><Icon name="user" size={16} /><input value={f.login_id} onChange={set('login_id')} maxLength={12} placeholder="e.g. warehouse01" autoFocus autoComplete="username" /></div>
        </Field>
        <Field label="Email">
          <div className="input-icon"><Icon name="mail" size={16} /><input type="email" value={f.email} onChange={set('email')} placeholder="you@company.com" autoComplete="email" /></div>
        </Field>
        <Field label="Password"><PasswordInput value={f.password} onChange={set('password')} placeholder="Create a password" autoComplete="new-password" /></Field>
        <Rules password={f.password} />
        <Field label="Confirm password"><PasswordInput value={f.confirm_password} onChange={set('confirm_password')} placeholder="Re-enter password" autoComplete="new-password" /></Field>
        <ErrorBox msg={err} />
        <button className="btn primary block" disabled={busy}>{busy ? 'Creating…' : 'Create account'}</button>
      </form>
      <p className="auth-alt">Already registered? <Link to="/login" className="link">Sign in</Link></p>
    </Shell>
  )
}

function OtpInput({ value, onChange }) {
  const refs = useRef([])
  const digits = Array.from({ length: 6 }, (_, i) => value[i] || '')
  const setAt = (i, ch) => {
    const arr = digits.slice(); arr[i] = ch
    onChange(arr.join(''))
  }
  return (
    <div className="otp">
      {digits.map((d, i) => (
        <input
          key={i}
          ref={(el) => (refs.current[i] = el)}
          value={d}
          inputMode="numeric"
          maxLength={1}
          autoFocus={i === 0}
          aria-label={`Digit ${i + 1}`}
          onChange={(e) => {
            const ch = e.target.value.replace(/\D/g, '').slice(-1)
            setAt(i, ch)
            if (ch && i < 5) refs.current[i + 1]?.focus()
          }}
          onKeyDown={(e) => {
            if (e.key === 'Backspace' && !d && i > 0) refs.current[i - 1]?.focus()
          }}
          onPaste={(e) => {
            const t = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
            if (t) { e.preventDefault(); onChange(t); refs.current[Math.min(t.length, 5)]?.focus() }
          }}
        />
      ))}
    </div>
  )
}

export function Forgot() {
  const [step, setStep] = useState(1)
  const [f, setF] = useState({ email: '', otp: '', new_password: '', confirm_password: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const run = (fn) => async (e) => {
    e.preventDefault(); setErr(''); setBusy(true)
    try { await fn() } catch (x) { setErr(x.message) }
    setBusy(false)
  }
  const send = run(async () => { await api('/auth/forgot-password', { method: 'POST', body: { email: f.email } }); setStep(2) })
  const reset = run(async () => { await api('/auth/reset-password', { method: 'POST', body: f }); setStep(3) })

  const titles = {
    1: ['Reset your password', "Enter your account email and we'll send a 6-digit code."],
    2: ['Check your inbox', `We sent a code to ${f.email}. It expires in 10 minutes.`],
    3: ['Password updated', 'You can now sign in with your new password.'],
  }
  return (
    <Shell title={titles[step][0]} lead={titles[step][1]}>
      {step === 1 && (
        <form className="stack" onSubmit={send}>
          <Field label="Email">
            <div className="input-icon"><Icon name="mail" size={16} /><input type="email" value={f.email} onChange={set('email')} placeholder="you@company.com" autoFocus /></div>
          </Field>
          <ErrorBox msg={err} />
          <button className="btn primary block" disabled={busy || !f.email}>{busy ? 'Sending…' : 'Send code'}</button>
        </form>
      )}
      {step === 2 && (
        <form className="stack" onSubmit={reset}>
          <Field label="6-digit code"><OtpInput value={f.otp} onChange={(otp) => setF({ ...f, otp })} /></Field>
          <Field label="New password"><PasswordInput value={f.new_password} onChange={set('new_password')} placeholder="New password" autoComplete="new-password" /></Field>
          <Rules password={f.new_password} />
          <Field label="Confirm password"><PasswordInput value={f.confirm_password} onChange={set('confirm_password')} placeholder="Re-enter password" autoComplete="new-password" /></Field>
          <ErrorBox msg={err} />
          <button className="btn primary block" disabled={busy || f.otp.length < 6}>{busy ? 'Updating…' : 'Reset password'}</button>
          <div className="auth-alt" style={{ margin: 0 }}>Didn't get it? <button type="button" className="link" onClick={() => { setStep(1); setErr('') }}>Send again</button></div>
        </form>
      )}
      {step === 3 && (
        <div className="stack">
          <div className="form-ok"><Icon name="check" size={18} />Your password has been changed.</div>
          <Link to="/login" className="btn primary block">Back to sign in</Link>
        </div>
      )}
      {step !== 3 && <p className="auth-alt"><Link to="/login" className="link"><Icon name="arrowleft" size={14} /> Back to sign in</Link></p>}
    </Shell>
  )
}
