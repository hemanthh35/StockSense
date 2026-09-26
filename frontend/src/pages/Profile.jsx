import { useState } from 'react'
import { api } from '../api'
import { Icon } from '../components/icons.jsx'
import { Field, PageHeader, Toast, useToast } from '../components/ui.jsx'
import { Rules } from './Auth.jsx'

function Pw({ value, onChange, autoComplete }) {
  const [show, setShow] = useState(false)
  return (
    <div className="input-icon">
      <Icon name="lock" size={16} />
      <input type={show ? 'text' : 'password'} value={value} onChange={onChange} autoComplete={autoComplete} />
      <button type="button" className="icon-btn reveal" onClick={() => setShow(!show)} aria-label={show ? 'Hide password' : 'Show password'}><Icon name={show ? 'eyeoff' : 'eye'} size={17} /></button>
    </div>
  )
}

export default function Profile({ user, onUserChange }) {
  const [email, setEmail] = useState(user.email)
  const [pw, setPw] = useState({ current_password: '', new_password: '', confirm_password: '' })
  const [toast, notify, close] = useToast()
  const [busy, setBusy] = useState('')
  const set = (k) => (e) => setPw({ ...pw, [k]: e.target.value })

  const saveEmail = async (e) => {
    e.preventDefault()
    setBusy('email')
    try { onUserChange(await api('/auth/me', { method: 'PUT', body: { email } })); notify('Email updated', 'ok') } catch (x) { notify(x.message, 'error') }
    setBusy('')
  }
  const savePw = async (e) => {
    e.preventDefault()
    setBusy('pw')
    try {
      await api('/auth/change-password', { method: 'POST', body: pw })
      setPw({ current_password: '', new_password: '', confirm_password: '' })
      notify('Password changed', 'ok')
    } catch (x) { notify(x.message, 'error') }
    setBusy('')
  }

  return (
    <>
      <PageHeader title="My profile" subtitle="Your account details and password." />
      <div className="profile-grid">
        <div className="card">
          <div className="profile">
            <span className="avatar lg">{user.login_id[0].toUpperCase()}</span>
            <div><h3 style={{ fontSize: 20, fontWeight: 600, letterSpacing: '-0.02em' }}>{user.login_id}</h3><p className="muted">{user.email}</p></div>
          </div>
          <form className="card-pad" onSubmit={saveEmail} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Field label="Login ID" hint="Your login ID can't be changed"><input disabled value={user.login_id} /></Field>
            <Field label="Email"><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
            <div><button className="btn primary" disabled={busy === 'email' || email === user.email}>Save email</button></div>
          </form>
        </div>

        <form className="card card-pad" onSubmit={savePw} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div><h3 style={{ fontSize: 16, fontWeight: 600 }}>Change password</h3><p className="muted small" style={{ marginTop: 4 }}>Use at least 9 characters with upper and lower case letters and a special character.</p></div>
          <Field label="Current password"><Pw value={pw.current_password} onChange={set('current_password')} autoComplete="current-password" /></Field>
          <Field label="New password"><Pw value={pw.new_password} onChange={set('new_password')} autoComplete="new-password" /></Field>
          <Rules password={pw.new_password} />
          <Field label="Confirm new password"><Pw value={pw.confirm_password} onChange={set('confirm_password')} autoComplete="new-password" /></Field>
          <div><button className="btn primary" disabled={busy === 'pw' || !pw.current_password || !pw.new_password}>Change password</button></div>
        </form>
      </div>
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}
