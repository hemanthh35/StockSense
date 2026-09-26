import { useState } from 'react'
import { api } from '../api'
import { useApi } from '../hooks'
import { Icon } from '../components/icons.jsx'
import { Empty, Field, Modal, PageHeader, Pager, TableSkeleton, Toast, usePager, useToast } from '../components/ui.jsx'

export function Warehouses() {
  const { data, reload } = useApi('/warehouses')
  const [form, setForm] = useState(null)
  const [toast, notify, close] = useToast()
  const pager = usePager(data || [])
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
      <PageHeader
        title="Warehouses"
        subtitle="The short code prefixes every reference, e.g. WH/IN/0001."
        actions={<button className="btn primary" onClick={() => setForm({ name: '', short_code: '', address: '' })}><Icon name="plus" size={16} />New warehouse</button>}
      />
      <div className="card">
        <div className="table-wrap">
          <table className="rows">
            <thead><tr><th>Name</th><th>Short code</th><th>Address</th></tr></thead>
            <tbody>
              {!data && <TableSkeleton cols={3} rows={3} />}
              {pager.slice.map((w) => (
                <tr key={w.id} onClick={() => setForm(w)}>
                  <td className="strong">{w.name}</td><td className="mono">{w.short_code}</td><td className="muted">{w.address || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && !data.length && <Empty icon="warehouse" title="No warehouses" hint="Create one to start receiving stock." />}
        <Pager p={pager} />
      </div>
      {form && (
        <Modal
          width={520}
          title={form.id ? 'Edit warehouse' : 'New warehouse'}
          onClose={() => setForm(null)}
          footer={<><button className="btn" onClick={() => setForm(null)}>Discard</button><button className="btn primary" form="wh-form">Save</button></>}
        >
          <form id="wh-form" className="form-grid" onSubmit={save}>
            <Field label="Name"><input value={form.name} onChange={set('name')} required autoFocus /></Field>
            <Field label="Short code" hint="Up to 10 characters"><input value={form.short_code} onChange={set('short_code')} maxLength={10} required className="mono" /></Field>
            <Field label="Address" className="full"><input value={form.address || ''} onChange={set('address')} /></Field>
          </form>
        </Modal>
      )}
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}

export function Locations() {
  const { data, reload } = useApi('/locations')
  const whs = useApi('/warehouses').data || []
  const [form, setForm] = useState(null)
  const [toast, notify, close] = useToast()
  const pager = usePager(data || [])
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
      <PageHeader
        title="Locations"
        subtitle="Racks, rooms and stock areas inside a warehouse. Locations are the From / To ends of every move."
        actions={<button className="btn primary" onClick={() => setForm({ name: '', short_code: '', warehouse_id: whs[0]?.id || '' })}><Icon name="plus" size={16} />New location</button>}
      />
      <div className="card">
        <div className="table-wrap">
          <table className="rows">
            <thead><tr><th>Location</th><th>Short code</th><th>Type</th></tr></thead>
            <tbody>
              {!data && <TableSkeleton cols={3} rows={4} />}
              {pager.slice.map((l) => (
                <tr key={l.id} onClick={() => l.type === 'internal' && setForm(l)} style={l.type !== 'internal' ? { cursor: 'default' } : undefined}>
                  <td className="mono strong">{l.full_name}</td>
                  <td className="mono muted">{l.short_code}</td>
                  <td><span className="tag">{l.type === 'internal' ? 'Stock location' : `Virtual · ${l.type}`}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pager p={pager} />
      </div>
      {form && (
        <Modal
          width={520}
          title={form.id ? 'Edit location' : 'New location'}
          onClose={() => setForm(null)}
          footer={<><button className="btn" onClick={() => setForm(null)}>Discard</button><button className="btn primary" form="loc-form">Save</button></>}
        >
          <form id="loc-form" className="form-grid" onSubmit={save}>
            <Field label="Name"><input value={form.name} onChange={set('name')} required autoFocus /></Field>
            <Field label="Short code"><input value={form.short_code} onChange={set('short_code')} required className="mono" /></Field>
            <Field label="Warehouse" className="full">
              <select value={form.warehouse_id} onChange={set('warehouse_id')} required>
                {whs.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            </Field>
          </form>
        </Modal>
      )}
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}

export function Profile({ user }) {
  return (
    <>
      <PageHeader title="My profile" subtitle="Your account details." />
      <div className="card" style={{ maxWidth: 640 }}>
        <div className="profile">
          <span className="avatar lg">{user.login_id[0].toUpperCase()}</span>
          <div><h3 style={{ fontSize: 20, fontWeight: 600, letterSpacing: '-0.02em' }}>{user.login_id}</h3><p className="muted">{user.email}</p></div>
        </div>
        <div className="card-pad form-grid">
          <Field label="Login ID"><input disabled value={user.login_id} /></Field>
          <Field label="Email"><input disabled value={user.email} /></Field>
        </div>
      </div>
    </>
  )
}
