import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Icon } from './icons.jsx'
import { LifecycleActions } from './Lifecycle.jsx'
import { Field, Modal, Segmented, Status, fmtDate, money } from './ui.jsx'

const KIND_OPTS = [{ value: 'vendor', label: 'Supplier' }, { value: 'customer', label: 'Customer' }, { value: 'both', label: 'Both' }]
const PATH = { IN: 'receipts', OUT: 'deliveries', INT: 'transfers', ADJ: 'adjustments' }
const GSTIN_SHAPE = /^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/

/** Create or edit a supplier/customer. When editing it also lists the party's latest documents. */
export default function PartyModal({ party, defaults = {}, onClose, onSaved, notify }) {
  const editing = !!party?.id
  const [form, setForm] = useState({ name: '', kind: 'both', gstin: '', email: '', phone: '', address: '', ...defaults, ...(party || {}) })
  const [full, setFull] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (editing) api(`/parties/${party.id}`).then(setFull).catch(() => {})
  }, [editing, party?.id])

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const gstin = (form.gstin || '').toUpperCase().replace(/\s/g, '')
  const shape = !gstin ? null : GSTIN_SHAPE.test(gstin)

  const save = async (e) => {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      const body = { name: form.name, kind: form.kind, gstin: gstin || null, email: form.email || null, phone: form.phone || null, address: form.address || null }
      const saved = editing ? await api(`/parties/${party.id}`, { method: 'PUT', body }) : await api('/parties', { method: 'POST', body })
      onSaved(saved)
    } catch (x) { setError(x.message) }
    setBusy(false)
  }

  return (
    <Modal
      width={640}
      title={editing ? 'Edit contact' : 'New contact'}
      subtitle={editing ? undefined : 'Saved contacts fill in the name, address and GSTIN on documents.'}
      onClose={onClose}
      footer={<>
        {editing && <LifecycleActions item={{ ...party, ...(full || {}) }} base="/parties" name="Contact" notify={notify} onDone={onSaved.bind(null, null)} />}
        <button className="btn" onClick={onClose}>Discard</button>
        <button className="btn primary" form="party-form" disabled={busy}>Save contact</button>
      </>}
    >
      <form id="party-form" className="form-grid" onSubmit={save}>
        <Field label="Name" className="full"><input value={form.name} onChange={set('name')} required autoFocus /></Field>
        <Field label="Type" className="full"><Segmented value={form.kind} onChange={(kind) => setForm({ ...form, kind })} options={KIND_OPTS} /></Field>
        <Field
          label="GSTIN"
          hint={shape === false ? 'That does not look like a GSTIN yet (15 characters, e.g. 24AAACC1206D1ZM)' : shape ? 'Format looks right; the check digit is verified when you save' : 'Optional. Needed on GST invoices'}
        >
          <input value={form.gstin || ''} onChange={(e) => setForm({ ...form, gstin: e.target.value.toUpperCase() })} maxLength={15} className={`mono ${shape === false ? 'invalid' : ''}`} placeholder="24AAACC1206D1ZM" />
        </Field>
        <Field label="Phone"><input value={form.phone || ''} onChange={set('phone')} inputMode="tel" /></Field>
        <Field label="Email" className="full"><input type="email" value={form.email || ''} onChange={set('email')} /></Field>
        <Field label="Address" className="full"><input value={form.address || ''} onChange={set('address')} /></Field>
        {error && <div className="form-error full"><Icon name="alert" size={16} />{error}</div>}
      </form>

      {editing && full && (
        <div className="party-history">
          <div className="section-title" style={{ margin: '22px 0 8px' }}>Recent documents</div>
          {full.recent.length === 0 ? <p className="muted small">No documents yet.</p> : (
            <table>
              <tbody>
                {full.recent.map((o) => (
                  <tr key={o.id}>
                    <td className="mono"><Link className="link" to={`/operations/${PATH[o.type]}/${o.id}`} onClick={onClose}>{o.reference}</Link></td>
                    <td className="muted">{fmtDate(o.schedule_date)}</td>
                    <td className="num">{money(o.total)}</td>
                    <td><Status value={o.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted small" style={{ marginTop: 8 }}>{full.documents} document{full.documents === 1 ? '' : 's'} · {money(full.total_value)} in total (cancelled excluded)</p>
        </div>
      )}
    </Modal>
  )
}
