import { useState } from 'react'
import { api } from '../api'
import { useApi } from '../hooks'
import { Icon } from '../components/icons.jsx'
import { ArchivedTag, LifecycleActions } from '../components/Lifecycle.jsx'
import { Empty, Field, Modal, PageHeader, Pager, TableSkeleton, Toast, usePager, useToast } from '../components/ui.jsx'

export function Warehouses() {
  const [showArchived, setShowArchived] = useState(false)
  const { data, reload } = useApi('/warehouses', { include_archived: showArchived ? 'true' : '' })
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
        <div className="toolbar">
          <label className="check"><span className="switch"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /><i /></span>Show archived</label>
        </div>
        <div className="table-wrap">
          <table className="rows">
            <thead><tr><th>Name</th><th>Short code</th><th>Address</th></tr></thead>
            <tbody>
              {!data && <TableSkeleton cols={3} rows={3} />}
              {pager.slice.map((w) => (
                <tr key={w.id} onClick={() => setForm(w)} style={w.active ? undefined : { opacity: 0.6 }}>
                  <td className="strong">{w.name} {!w.active && <ArchivedTag />}</td><td className="mono">{w.short_code}</td><td className="muted">{w.address || '—'}</td>
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
          footer={<>
            <LifecycleActions item={form} base="/warehouses" name="Warehouse" notify={notify} onDone={() => { setForm(null); reload() }} />
            <button className="btn" onClick={() => setForm(null)}>Discard</button>
            <button className="btn primary" form="wh-form">Save</button>
          </>}
        >
          <form id="wh-form" className="form-grid" onSubmit={save}>
            <Field label="Name"><input value={form.name} onChange={set('name')} required autoFocus /></Field>
            <Field label="Short code" hint="Up to 10 characters"><input value={form.short_code} onChange={set('short_code')} maxLength={10} required className="mono" /></Field>
            <Field label="Address" className="full"><input value={form.address || ''} onChange={set('address')} /></Field>
            {form.id && <div className="full hint-box"><Icon name="alert" size={16} />A warehouse can be archived once it holds no stock and has no open documents. Deleting is only possible if it was never used.</div>}
          </form>
        </Modal>
      )}
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}

export function Locations() {
  const [showArchived, setShowArchived] = useState(false)
  const { data, reload } = useApi('/locations', { include_archived: showArchived ? 'true' : '' })
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
        <div className="toolbar">
          <label className="check"><span className="switch"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /><i /></span>Show archived</label>
        </div>
        <div className="table-wrap">
          <table className="rows">
            <thead><tr><th>Location</th><th>Short code</th><th>Type</th></tr></thead>
            <tbody>
              {!data && <TableSkeleton cols={3} rows={4} />}
              {pager.slice.map((l) => (
                <tr key={l.id} onClick={() => l.type === 'internal' && setForm(l)} style={{ cursor: l.type !== 'internal' ? 'default' : undefined, opacity: l.active ? 1 : 0.6 }}>
                  <td className="mono strong">{l.full_name} {!l.active && <ArchivedTag />}</td>
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
          footer={<>
            <LifecycleActions item={form} base="/locations" name="Location" notify={notify} onDone={() => { setForm(null); reload() }} />
            <button className="btn" onClick={() => setForm(null)}>Discard</button>
            <button className="btn primary" form="loc-form">Save</button>
          </>}
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
