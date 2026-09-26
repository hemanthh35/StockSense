import { useState } from 'react'
import { api } from '../api'
import { useApi } from '../hooks'
import { Icon } from '../components/icons.jsx'
import { Empty, Field, Modal, PageHeader, Segmented, TableSkeleton, Toast, useToast } from '../components/ui.jsx'

const KIND_OPTS = [{ value: 'GST', label: 'GST' }, { value: 'OTHER', label: 'Other tax' }]
const autoName = (kind, rate) => (kind === 'GST' ? `GST ${Number(rate || 0)}%` : `Tax ${Number(rate || 0)}%`)
const fresh = () => ({ kind: 'GST', rate: '', name: '', nameTouched: false, active: true, is_default: false })

export default function Taxes() {
  const { data, reload } = useApi('/taxes', { include_inactive: true })
  const cats = useApi('/category-taxes')
  const [form, setForm] = useState(null)
  const [toast, notify, close] = useToast()
  const activeTaxes = (data || []).filter((t) => t.active)

  const change = (patch) => setForm((f) => {
    const next = { ...f, ...patch }
    if (!next.nameTouched && !next.id) next.name = autoName(next.kind, next.rate)
    return next
  })

  const save = async (e) => {
    e.preventDefault()
    try {
      const body = { name: form.name, rate: Number(form.rate), kind: form.kind, active: form.active, is_default: form.is_default }
      if (form.id) await api(`/taxes/${form.id}`, { method: 'PUT', body })
      else await api('/taxes', { method: 'POST', body })
      setForm(null); reload(); cats.reload(); notify('Tax saved', 'ok')
    } catch (x) { notify(x.message, 'error') }
  }

  const toggle = async (t) => {
    try {
      await api(`/taxes/${t.id}`, { method: 'PUT', body: { name: t.name, rate: t.rate, kind: t.kind, active: !t.active, is_default: t.is_default && !t.active } })
      reload()
    } catch (x) { notify(x.message, 'error') }
  }

  const setCatTax = async (c, value) => {
    try {
      await api(`/category-taxes/${c.id}`, { method: 'PUT', body: { default_tax_id: value ? Number(value) : null } })
      cats.reload(); notify(`${c.name} products will now default to ${value ? activeTaxes.find((t) => t.id === Number(value))?.name : 'the global default'}`, 'ok')
    } catch (x) { notify(x.message, 'error') }
  }

  return (
    <>
      <PageHeader
        title="Taxes"
        subtitle="Set a tax once and it applies itself — on products, receipts and deliveries. You never re-enter it per order."
        actions={<button className="btn primary" onClick={() => setForm(fresh())}><Icon name="plus" size={16} />New tax</button>}
      />

      <div className="card">
        <div className="card-head"><h3>Tax rates</h3><span className="muted small">Documents keep the rate they were created with</span></div>
        <div className="table-wrap">
          <table className="rows">
            <thead><tr><th>Name</th><th>Type</th><th className="num">Rate</th><th>Default</th><th style={{ width: 90 }}>Active</th></tr></thead>
            <tbody>
              {!data && <TableSkeleton cols={5} rows={5} />}
              {(data || []).map((t) => (
                <tr key={t.id} onClick={() => setForm({ ...t, nameTouched: true })} style={t.active ? undefined : { opacity: 0.55 }}>
                  <td className="strong">{t.name}</td>
                  <td><span className="tag">{t.kind === 'GST' ? 'GST' : 'Other'}</span></td>
                  <td className="num">{t.rate}%</td>
                  <td>{t.is_default && <span className="default-pill">Default</span>}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <label className="switch" aria-label={`${t.name} active`}><input type="checkbox" checked={t.active} onChange={() => toggle(t)} /><i /></label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && !data.length && <Empty icon="tag" title="No taxes yet" hint="Add a GST slab to get started." />}
      </div>

      <div className="card">
        <div className="card-head"><h3>Category defaults</h3><span className="muted small">New products pick this tax automatically</span></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Category</th><th className="num">Products</th><th style={{ width: 260 }}>Default tax</th></tr></thead>
            <tbody>
              {!cats.data && <TableSkeleton cols={3} rows={3} />}
              {(cats.data || []).map((c) => (
                <tr key={c.id}>
                  <td className="strong">{c.name}</td>
                  <td className="num">{c.products}</td>
                  <td>
                    <select value={c.default_tax_id || ''} onChange={(e) => setCatTax(c, e.target.value)}>
                      <option value="">Use global default</option>
                      {activeTaxes.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {cats.data && !cats.data.length && <Empty icon="tag" title="No categories yet" hint="Categories appear here once you create them on a product." />}
      </div>

      {form && (
        <Modal
          width={500}
          title={form.id ? 'Edit tax' : 'New tax'}
          subtitle={form.id ? undefined : 'A new GST slab or any other tax — available everywhere immediately.'}
          onClose={() => setForm(null)}
          footer={<><button className="btn" onClick={() => setForm(null)}>Discard</button><button className="btn primary" form="tax-form">Save tax</button></>}
        >
          <form id="tax-form" className="form-grid" onSubmit={save}>
            <Field label="Type" className="full"><Segmented value={form.kind} onChange={(kind) => change({ kind })} options={KIND_OPTS} /></Field>
            <Field label="Rate (%)"><input type="number" min="0" max="100" step="any" value={form.rate} onChange={(e) => change({ rate: e.target.value })} required autoFocus /></Field>
            <Field label="Name" hint="Shown on products and documents"><input value={form.name} onChange={(e) => change({ name: e.target.value, nameTouched: true })} required /></Field>
            <div className="full toggle-row">
              <span><b>Default for new products</b><small>Used when a product has no category default</small></span>
              <label className="switch"><input type="checkbox" checked={form.is_default} onChange={(e) => change({ is_default: e.target.checked })} /><i /></label>
            </div>
            <div className="full toggle-row">
              <span><b>Active</b><small>Inactive taxes can't be picked on new products</small></span>
              <label className="switch"><input type="checkbox" checked={form.active} onChange={(e) => change({ active: e.target.checked })} /><i /></label>
            </div>
            {form.id && <div className="full hint-box"><Icon name="alert" size={16} />Changing the rate updates draft and future documents. Validated documents keep their original rate.</div>}
          </form>
        </Modal>
      )}
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}
