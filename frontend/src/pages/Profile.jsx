import { useState } from 'react'
import { api } from '../api'
import { useApi } from '../hooks'
import { Icon } from '../components/icons.jsx'
import { Field, PageHeader, Toast, useToast } from '../components/ui.jsx'
import { Rules } from './Auth.jsx'
import { ROLE_LABEL } from '../perm.js'

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
  const prefs = useApi('/notifications/preferences')
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

  const toggleDigest = async (on) => {
    try {
      await api('/notifications/preferences', { method: 'PUT', body: { low_stock_digest: on } })
      await prefs.reload()
      notify(on ? 'Daily digest turned on' : 'Daily digest turned off', 'ok')
    } catch (x) { notify(x.message, 'error') }
  }
  const sendTest = async () => {
    setBusy('digest')
    try {
      const r = await api('/notifications/digest/test', { method: 'POST' })
      notify(r.sent ? `Sent to ${user.email}: ${r.items} product${r.items === 1 ? '' : 's'} to reorder` : r.reason, r.sent ? 'ok' : 'info')
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
            <div><h3 style={{ fontSize: 20, fontWeight: 600, letterSpacing: '-0.02em' }}>{user.login_id}</h3><p className="muted">{user.email}</p><span className="role-pill" style={{ marginTop: 8 }}>{ROLE_LABEL[user.role]}</span></div>
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
      <div className="card card-pad" style={{ marginTop: 16 }}>
        <div className="notify-row">
          <div>
            <b>Daily low-stock email</b>
            <small>What to reorder, what is late and what is waiting for stock, sent to {user.email}. {prefs.data?.schedule}.</small>
          </div>
          <label className="switch" aria-label="Daily low-stock email">
            <input type="checkbox" checked={!!prefs.data?.low_stock_digest} disabled={!prefs.data} onChange={(e) => toggleDigest(e.target.checked)} /><i />
          </label>
        </div>
        <div className="rowgap" style={{ marginTop: 14 }}>
          <button className="btn" disabled={busy === 'digest'} onClick={sendTest}><Icon name="mail" size={16} />{busy === 'digest' ? 'Sending…' : "Send me today's digest now"}</button>
          {prefs.data && !prefs.data.email_configured && <span className="muted small">Email delivery isn't configured on this server, so nothing will actually be sent.</span>}
        </div>
      </div>
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}
