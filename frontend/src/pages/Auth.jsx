import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'

const Shell = ({ title, children }) => (
  <div className="auth">
    <div className="card auth-card">
      <div className="logo">App Logo</div>
      <h2>{title}</h2>
      {children}
    </div>
  </div>
)

export function Login({ onAuth }) {
  const nav = useNavigate()
  const [f, setF] = useState({ login_id: '', password: '' })
  const [err, setErr] = useState('')
  const submit = async (e) => {
    e.preventDefault()
    try { onAuth(await api('/auth/login', { method: 'POST', body: f })); nav('/') } catch (x) { setErr(x.message) }
  }
  return (
    <Shell title="Sign in">
      <form onSubmit={submit}>
        <label>Login Id<input value={f.login_id} onChange={(e) => setF({ ...f, login_id: e.target.value })} autoFocus /></label>
        <label>Password<input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></label>
        {err && <div className="error">"{err}"</div>}
        <button className="btn primary block">SIGN IN</button>
        <div className="links"><Link to="/forgot">Forget Password ?</Link> | <Link to="/signup">Sign Up</Link></div>
      </form>
    </Shell>
  )
}

export function Signup({ onAuth }) {
  const nav = useNavigate()
  const [f, setF] = useState({ login_id: '', password: '', confirm_password: '', email: '' })
  const [err, setErr] = useState('')
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const submit = async (e) => {
    e.preventDefault()
    try { onAuth(await api('/auth/signup', { method: 'POST', body: f })); nav('/') } catch (x) { setErr(x.message) }
  }
  return (
    <Shell title="Sign up">
      <form onSubmit={submit}>
        <label>Enter Login Id<input value={f.login_id} onChange={set('login_id')} placeholder="6–12 characters" /></label>
        <label>Enter Email Id<input type="email" value={f.email} onChange={set('email')} /></label>
        <label>Enter Password<input type="password" value={f.password} onChange={set('password')} /></label>
        <label>Re-Enter Password<input type="password" value={f.confirm_password} onChange={set('confirm_password')} /></label>
        <p className="muted small">Password: 9+ characters with a lowercase, an uppercase and a special character.</p>
        {err && <div className="error">{err}</div>}
        <button className="btn primary block">SIGN UP</button>
        <div className="links"><Link to="/login">Back to Login</Link></div>
      </form>
    </Shell>
  )
}

export function Forgot() {
  const [step, setStep] = useState(1)
  const [f, setF] = useState({ email: '', otp: '', new_password: '', confirm_password: '' })
  const [err, setErr] = useState('')
  const [info, setInfo] = useState('')
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const run = (fn) => async (e) => { e.preventDefault(); setErr(''); try { await fn() } catch (x) { setErr(x.message) } }

  const send = run(async () => {
    const r = await api('/auth/forgot-password', { method: 'POST', body: { email: f.email } })
    setInfo(r.message); setStep(2)
  })
  const reset = run(async () => {
    const r = await api('/auth/reset-password', { method: 'POST', body: f })
    setInfo(r.message); setStep(3)
  })

  return (
    <Shell title="Reset password">
      {step === 1 && (
        <form onSubmit={send}>
          <label>Email Id<input type="email" value={f.email} onChange={set('email')} autoFocus /></label>
          {err && <div className="error">{err}</div>}
          <button className="btn primary block">SEND OTP</button>
        </form>
      )}
      {step === 2 && (
        <form onSubmit={reset}>
          <p className="muted small">{info}</p>
          <label>6-digit code<input value={f.otp} onChange={set('otp')} maxLength={6} inputMode="numeric" autoFocus /></label>
          <label>New Password<input type="password" value={f.new_password} onChange={set('new_password')} /></label>
          <label>Re-Enter Password<input type="password" value={f.confirm_password} onChange={set('confirm_password')} /></label>
          {err && <div className="error">{err}</div>}
          <button className="btn primary block">RESET PASSWORD</button>
          <div className="links"><a onClick={() => setStep(1)}>Resend code</a></div>
        </form>
      )}
      {step === 3 && <p className="ok">{info}</p>}
      <div className="links"><Link to="/login">Back to Login</Link></div>
    </Shell>
  )
}
