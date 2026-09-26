import { useState } from 'react'
import { api } from '../api'
import { useApi } from '../hooks'
import { Toast, useToast } from '../components/ui.jsx'

export function Warehouses() {
  const { data, reload } = useApi('/warehouses')
  const [form, setForm] = useState(null)
  const [toast, notify, close] = useToast()
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const save = async (e) => {
    e.preventDefault()
    try {
      const body = { name: form.name, short_code: form.short_code, address: form.address }
      if (form.id) await api(`/warehouses/${form.id}`, { method: 'PUT', body })
      else await api('/warehouses', { method: 'POST', body })
      setForm(null); reload(); notify('Warehouse saved', 'ok')
    } catch (x) { notify(x.message, 'error') }
  }
  return (
    <>
      <div className="head">
        <h1>Warehouse</h1>
        <button className="btn primary" onClick={() => setForm({ name: '', short_code: '', address: '' })}>New</button>
      </div>
      {form && (
        <form className="card form2" onSubmit={save}>
          <label>Name:<input value={form.name} onChange={set('name')} required /></label>
          <label>Short Code:<input value={form.short_code} onChange={set('short_code')} maxLength={10} required /></label>
          <label className="full">Address:<input value={form.address || ''} onChange={set('address')} /></label>
          <div className="rowgap full">
            <button className="btn primary">Save</button>
            <button type="button" className="btn" onClick={() => setForm(null)}>Discard</button>
          </div>
        </form>
      )}
      <div className="card">
        <table className="clickable">
          <thead><tr><th>Name</th><th>Short Code</th><th>Address</th></tr></thead>
          <tbody>
            {(data || []).map((w) => (
              <tr key={w.id} onClick={() => setForm(w)}><td>{w.name}</td><td>{w.short_code}</td><td>{w.address || '—'}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}

export function Locations() {
  const { data, reload } = useApi('/locations')
  const whs = useApi('/warehouses').data || []
  const [form, setForm] = useState(null)
  const [toast, notify, close] = useToast()
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const save = async (e) => {
    e.preventDefault()
    try {
      const body = { name: form.name, short_code: form.short_code, warehouse_id: Number(form.warehouse_id) }
      if (form.id) await api(`/locations/${form.id}`, { method: 'PUT', body })
      else await api('/locations', { method: 'POST', body })
      setForm(null); reload(); notify('Location saved', 'ok')
    } catch (x) { notify(x.message, 'error') }
  }
  return (
    <>
      <div className="head">
        <h1>location</h1>
        <button className="btn primary" onClick={() => setForm({ name: '', short_code: '', warehouse_id: whs[0]?.id || '' })}>New</button>
      </div>
      <p className="muted">This holds the multiple locations of warehouse, rooms etc..</p>
      {form && (
        <form className="card form2" onSubmit={save}>
          <label>Name:<input value={form.name} onChange={set('name')} required /></label>
          <label>Short Code:<input value={form.short_code} onChange={set('short_code')} required /></label>
          <label>warehouse:
            <select value={form.warehouse_id} onChange={set('warehouse_id')} required>
              {whs.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </label>
          <div className="rowgap full">
            <button className="btn primary">Save</button>
            <button type="button" className="btn" onClick={() => setForm(null)}>Discard</button>
          </div>
        </form>
      )}
      <div className="card">
        <table className="clickable">
          <thead><tr><th>Location</th><th>Short Code</th><th>Type</th></tr></thead>
          <tbody>
            {(data || []).map((l) => (
              <tr key={l.id} onClick={() => l.type === 'internal' && setForm(l)}>
                <td>{l.full_name}</td><td>{l.short_code}</td><td className="muted">{l.type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}

export function Profile({ user }) {
  return (
    <>
      <h1>My Profile</h1>
      <div className="card form2">
        <label>Login Id<input disabled value={user.login_id} /></label>
        <label>Email<input disabled value={user.email} /></label>
      </div>
    </>
  )
}
