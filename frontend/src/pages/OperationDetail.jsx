import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useApi } from '../hooks'
import { Icon } from '../components/icons.jsx'
import { Field, PageHeader, Status, Stepper, Toast, money, num, useToast } from '../components/ui.jsx'
import { KINDS } from './Operations.jsx'

const blank = () => ({ warehouse_id: '', contact: '', schedule_date: new Date().toISOString().slice(0, 10), source_location_id: '', dest_location_id: '', lines: [] })

const toForm = (o) => ({
  warehouse_id: o.warehouse.id,
  contact: o.contact || '',
  schedule_date: o.schedule_date,
  source_location_id: o.source_location.id,
  dest_location_id: o.dest_location.id,
  lines: o.lines.map((l) => ({ product_id: l.product_id, quantity: l.quantity, unit_price: l.unit_price })),
})

/** A comparable fingerprint of what the user can edit, used to detect unsaved changes. */
const snap = (f) => JSON.stringify({
  c: f.contact || '', d: f.schedule_date, s: String(f.source_location_id ?? ''), t: String(f.dest_location_id ?? ''),
  l: f.lines.map((l) => [String(l.product_id), Number(l.quantity), Number(l.unit_price)]),
})

function Totals({ lines }) {
  let sub = 0
  const groups = {}
  lines.forEach((l) => {
    const base = (Number(l.quantity) || 0) * (Number(l.unit_price) || 0)
    sub += base
    if (l.tax_name) {
      const k = `${l.tax_name}|${l.tax_rate}`
      groups[k] = groups[k] || { name: l.tax_name, rate: Number(l.tax_rate), amount: 0 }
      groups[k].amount += (base * l.tax_rate) / 100
    }
  })
  const list = Object.values(groups).sort((a, b) => a.rate - b.rate)
  const tax = list.reduce((a, g) => a + g.amount, 0)
  return (
    <div className="totals">
      <div className="row"><span>Untaxed amount</span><span>{money(sub)}</span></div>
      {list.map((g) =>
        /^gst/i.test(g.name) && g.rate > 0 ? (
          <div key={g.name}>
            <div className="row"><span>{g.name}</span><span>{money(g.amount)}</span></div>
            <div className="row sub"><span>CGST {g.rate / 2}%</span><span>{money(g.amount / 2)}</span></div>
            <div className="row sub"><span>SGST {g.rate / 2}%</span><span>{money(g.amount / 2)}</span></div>
          </div>
        ) : (
          <div key={g.name} className="row"><span>{g.name}</span><span>{money(g.amount)}</span></div>
        )
      )}
      {!list.length && <div className="row"><span>Tax</span><span>{money(0)}</span></div>}
      <div className="row grand"><span>Total</span><span>{money(sub + tax)}</span></div>
    </div>
  )
}

function PickPack({ op }) {
  return (
    <div className="pickpack" aria-label="Pick and pack progress">
      <span className={`pp ${op.picked ? 'on' : ''}`}><Icon name="check" size={13} />Picked</span>
      <span className="pp-sep" />
      <span className={`pp ${op.packed ? 'on' : ''}`}><Icon name="check" size={13} />Packed</span>
    </div>
  )
}

export default function OperationDetail({ user }) {
  const { kind, id } = useParams()
  const cfg = KINDS[kind]
  const nav = useNavigate()
  const isNew = id === 'new'
  const [op, setOp] = useState(null)
  const [form, setForm] = useState(blank())
  const baseline = useRef(snap(blank()))
  const [toast, notify, closeToast] = useToast()
  const [busy, setBusy] = useState(false)
  const products = useApi('/products').data || []
  const locs = useApi('/locations', { internal_only: true }).data || []
  const whs = useApi('/warehouses').data || []
  const contacts = useApi('/contacts', { type: cfg?.type }, [kind]).data || []

  const hydrate = (o) => {
    const f = toForm(o)
    baseline.current = snap(f)
    setOp(o)
    setForm(f)
  }
  useEffect(() => {
    if (isNew) { setOp(null); setForm(blank()); baseline.current = snap(blank()) }
    else api(`/operations/${id}`).then(hydrate).catch((e) => notify(e.message, 'error'))
    // eslint-disable-next-line
  }, [id, kind])

  const chosenWh = form.warehouse_id || (isNew ? whs[0]?.id : '') || ''
  if (!cfg) return <div className="muted">Unknown page</div>
  const status = op?.status || 'draft'
  const editable = isNew || ['draft', 'waiting', 'ready'].includes(status)
  const dirty = !isNew && snap(form) !== baseline.current
  const t = cfg.type
  const priced = t !== 'ADJ'
  const shortLines = (op?.lines || []).filter((l) => l.short)
  const totalQty = form.lines.reduce((a, l) => a + (Number(l.quantity) || 0), 0)
  const prod = (pid) => products.find((p) => p.id === Number(pid))

  const setLine = (i, patch) => setForm({ ...form, lines: form.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) })
  const pickProduct = (i, pid) => {
    const p = prod(pid)
    setLine(i, { product_id: pid, unit_price: p ? p.unit_cost : '' })
  }
  const payload = () => ({
    type: t,
    warehouse_id: t !== 'INT' && chosenWh ? Number(chosenWh) : null,
    contact: form.contact || null,
    schedule_date: form.schedule_date,
    source_location_id: form.source_location_id ? Number(form.source_location_id) : null,
    dest_location_id: form.dest_location_id ? Number(form.dest_location_id) : null,
    lines: form.lines.filter((l) => l.product_id).map((l) => ({
      product_id: Number(l.product_id),
      quantity: Number(l.quantity),
      unit_price: l.unit_price === '' || l.unit_price == null ? null : Number(l.unit_price),
    })),
  })
  const save = async () => {
    if (isNew) {
      const o = await api('/operations', { method: 'POST', body: payload() })
      nav(`/operations/${kind}/${o.id}`, { replace: true })
      return o
    }
    const o = await api(`/operations/${id}`, { method: 'PUT', body: payload() })
    hydrate(o)
    return o
  }
  const guard = (fn) => async () => {
    setBusy(true)
    try { await fn() } catch (e) { notify(e.message, 'error') }
    setBusy(false)
  }
  /** Run a workflow action. Drafts are saved first; later states must not be re-saved
   *  (saving sends the document back to Draft), so unsaved edits have to be dealt with first. */
  const act = (action) => guard(async () => {
    let target = op
    if (isNew || status === 'draft') target = await save()
    else if (dirty) throw new Error('You have unsaved changes. Save them first (the order returns to Draft), or reload to discard.')
    const o = await api(`/operations/${target.id}/${action}`, { method: 'POST' })
    hydrate(o)
    if (o.message) notify(o.message, o.status === 'waiting' ? 'error' : 'info')
    else if (action === 'validate') notify(`${cfg.single} validated — stock updated`, 'ok')
    else if (action === 'pick') notify('Items picked — now pack them', 'ok')
    else if (action === 'pack') notify('Items packed — ready to validate', 'ok')
  })
  const duplicate = guard(async () => {
    const o = await api(`/operations/${id}/duplicate`, { method: 'POST' })
    nav(`/operations/${kind}/${o.id}`)
    notify(`Copied to ${o.reference} as a draft`, 'ok')
  })

  const totalsLines = editable
    ? form.lines.filter((l) => l.product_id).map((l) => ({ quantity: l.quantity, unit_price: l.unit_price, tax_rate: prod(l.product_id)?.tax?.rate || 0, tax_name: prod(l.product_id)?.tax?.name }))
    : (op?.lines || [])

  // receipts/deliveries stay inside one warehouse; transfers may cross warehouses
  const locOptions = t === 'INT' || !chosenWh ? locs : locs.filter((l) => l.warehouse_id === Number(chosenWh))
  const locSelect = (key, empty) => (
    <select disabled={!editable} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })}>
      <option value="">{empty}</option>
      {locOptions.map((l) => <option key={l.id} value={l.id}>{l.full_name}</option>)}
    </select>
  )
  const pickWarehouse = (e) => setForm({ ...form, warehouse_id: e.target.value, source_location_id: '', dest_location_id: '' })

  // the one primary action for the current state
  const isDelivery = t === 'OUT'
  const primary =
    status === 'draft' ? <button className="btn primary" disabled={busy} onClick={act('todo')}><Icon name="check" size={16} />To do</button>
    : status === 'waiting' ? <button className="btn" disabled={busy} onClick={act('check')}><Icon name="refresh" size={16} />Check availability</button>
    : status === 'ready' && isDelivery && !op?.picked ? <button className="btn primary" disabled={busy} onClick={act('pick')}><Icon name="box" size={16} />Mark picked</button>
    : status === 'ready' && isDelivery && !op?.packed ? <button className="btn primary" disabled={busy} onClick={act('pack')}><Icon name="box" size={16} />Mark packed</button>
    : status === 'ready' ? <button className="btn primary" disabled={busy} onClick={act('validate')}><Icon name="check" size={16} />Validate</button>
    : status === 'done' ? <button className="btn" onClick={() => window.print()}><Icon name="print" size={16} />Print</button>
    : null

  return (
    <>
      <PageHeader
        back={<Link className="back no-print" to={`/operations/${kind}`}><Icon name="arrowleft" size={14} />{cfg.title}</Link>}
        title={isNew ? `New ${cfg.single.toLowerCase()}` : cfg.single}
        actions={
          <div className="ph-actions no-print">
            {primary}
            {editable && <button className={`btn ${dirty ? 'primary' : ''}`} disabled={busy} onClick={guard(async () => { await save(); notify('Saved', 'ok') })}>Save</button>}
            {!isNew && priced && <button className="btn ghost" disabled={busy} onClick={duplicate}>Duplicate</button>}
            {!isNew && ['draft', 'waiting', 'ready'].includes(status) && <button className="btn danger" disabled={busy} onClick={act('cancel')}>Cancel</button>}
          </div>
        }
      />

      <div className="print-head">
        <div><b>StockSense</b><span>Inventory document</span></div>
        <div className="right"><b>{cfg.single} {op?.reference}</b><span>{op?.warehouse?.name} · printed {new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}</span></div>
      </div>

      {dirty && status !== 'draft' && (
        <div className="hint-box no-print" style={{ marginBottom: 16 }}>
          <Icon name="alert" size={16} />
          <span>Saving these changes will send this {cfg.single.toLowerCase()} back to Draft so stock is checked again.</span>
        </div>
      )}

      {shortLines.length > 0 && (
        <div className="banner" role="alert">
          <Icon name="alert" size={18} />
          <div><b>Not enough stock</b>{shortLines.length} product{shortLines.length > 1 ? 's are' : ' is'} short. This order stays in Waiting until stock arrives.</div>
        </div>
      )}

      <div className="card">
        <div className="detail-head">
          <div className="detail-ref">
            <span className="mono">{op?.reference || 'Reference assigned on save'}</span>
            {op && <Status value={op.status} />}
          </div>
          <Stepper flow={cfg.flow} current={status} />
        </div>
        {op && isDelivery && ['ready', 'done'].includes(status) && <PickPack op={op} />}
        <div className="card-pad">
          <div className="form-grid">
            <Field label={cfg.partner}>
              <input disabled={!editable} list="contact-list" value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} placeholder="Type or pick a previous contact" />
              <datalist id="contact-list">{contacts.map((c) => <option key={c} value={c} />)}</datalist>
            </Field>
            <Field label="Schedule date"><input type="date" disabled={!editable} value={form.schedule_date} onChange={(e) => setForm({ ...form, schedule_date: e.target.value })} /></Field>
            <Field label="Responsible"><input disabled value={op?.responsible || user.login_id} /></Field>
            {t !== 'INT' && (
              <Field label="Warehouse" hint={isNew ? 'Sets the reference prefix and stock locations' : undefined}>
                <select disabled={!isNew} value={chosenWh} onChange={pickWarehouse}>
                  {whs.map((w) => <option key={w.id} value={w.id}>{w.name} ({w.short_code})</option>)}
                </select>
              </Field>
            )}
            {t === 'INT' ? (
              <>
                <Field label="From">{locSelect('source_location_id', 'Select location')}</Field>
                <Field label="To">{locSelect('dest_location_id', 'Select location')}</Field>
              </>
            ) : t === 'IN' ? (
              <Field label="Receive into">{locSelect('dest_location_id', 'Default location')}</Field>
            ) : (
              <>
                <Field label="Ship from">{locSelect('source_location_id', 'Default location')}</Field>
                <Field label="Operation type"><input disabled value="Delivery order" /></Field>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h3>Products</h3>
          {editable && <Link className="link small no-print" to="/products?new=1">Add new product to catalogue</Link>}
        </div>
        <div className="table-wrap">
          <table className="detail-table">
            <thead>
              <tr>
                <th>Product</th><th className="num" style={{ width: 120 }}>Quantity</th>
                {priced && <><th className="num" style={{ width: 170 }}>Unit price</th><th style={{ width: 120 }}>Tax</th><th className="num" style={{ width: 130 }}>Subtotal</th></>}
                <th style={{ width: 52 }} />
              </tr>
            </thead>
            <tbody>
              {form.lines.map((l, i) => {
                const ln = op?.lines[i]
                const bad = !editable ? false : ln?.short && op.lines.length === form.lines.length
                const p = prod(l.product_id)
                const taxName = editable ? p?.tax?.name : ln?.tax_name
                const sub = (Number(l.quantity) || 0) * (Number(l.unit_price) || 0)
                return (
                  <tr key={i} className={bad ? 'short' : ''}>
                    <td>
                      {editable ? (
                        <select value={l.product_id} onChange={(e) => pickProduct(i, e.target.value)}>
                          <option value="">Select product</option>
                          {products.map((pp) => <option key={pp.id} value={pp.id}>{pp.label}</option>)}
                        </select>
                      ) : <span className="strong">{ln?.product}</span>}
                      {bad && <div className="line-warn"><Icon name="alert" size={13} />Short by {num(ln.missing)} — not in stock</div>}
                    </td>
                    <td className="num">
                      {editable ? <input type="number" min="0" step="any" value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} /> : num(l.quantity)}
                    </td>
                    {priced && (
                      <>
                        <td className="num price">
                          {editable ? <div className="prefix"><span>₹</span><input type="number" min="0" step="any" value={l.unit_price ?? ''} onChange={(e) => setLine(i, { unit_price: e.target.value })} /></div> : money(l.unit_price)}
                        </td>
                        <td>{l.product_id ? (taxName ? <span className="tax-tag">{taxName}</span> : <span className="tax-tag none">No tax</span>) : <span className="dim">—</span>}</td>
                        <td className="num strong">{money(sub)}</td>
                      </>
                    )}
                    <td>{editable && <button className="icon-btn line-x no-print" aria-label="Remove line" onClick={() => setForm({ ...form, lines: form.lines.filter((_, j) => j !== i) })}><Icon name="x" size={16} /></button>}</td>
                  </tr>
                )
              })}
              {!form.lines.length && <tr><td colSpan={priced ? 6 : 3} className="muted" style={{ height: 80, textAlign: 'center' }}>No products yet</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="table-foot">
          {editable
            ? <button className="btn sm no-print" onClick={() => setForm({ ...form, lines: [...form.lines, { product_id: '', quantity: 1, unit_price: '' }] })}><Icon name="plus" size={15} />New product line</button>
            : <span />}
          <span className="muted">Total quantity <b style={{ color: 'var(--text)', marginLeft: 6 }}>{num(totalQty)}</b></span>
        </div>
        {priced && <Totals lines={totalsLines} />}
      </div>
      <Toast msg={toast.msg} kind={toast.kind} onClose={closeToast} />
    </>
  )
}
