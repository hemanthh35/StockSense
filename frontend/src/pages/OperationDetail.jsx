import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useApi } from '../hooks'
import { canEditDocs } from '../perm.js'
import { Icon } from '../components/icons.jsx'
import History from '../components/History.jsx'
import PartyModal from '../components/PartyModal.jsx'
import ProductPicker from '../components/ProductPicker.jsx'
import PrintSheet, { sheetsFor } from '../components/PrintSheet.jsx'
import { Field, Menu, Modal, PageHeader, Status, Stepper, Toast, money, num, useToast } from '../components/ui.jsx'
import { KINDS } from './Operations.jsx'

const PATH = { IN: 'receipts', OUT: 'deliveries', INT: 'transfers', ADJ: 'adjustments' }
const CONFLICT = /changed by someone else/i
const blank = () => ({ warehouse_id: '', party_id: '', contact: '', schedule_date: new Date().toISOString().slice(0, 10), source_location_id: '', dest_location_id: '', lines: [] })

const toForm = (o) => ({
  warehouse_id: o.warehouse.id,
  party_id: o.party?.id ?? '',
  contact: o.contact || '',
  schedule_date: o.schedule_date,
  source_location_id: o.source_location.id,
  dest_location_id: o.dest_location.id,
  lines: o.lines.map((l) => ({ product_id: l.product_id, label: l.product, quantity: l.quantity, unit_price: l.unit_price, lot_no: l.lot_no || '', expiry_date: l.expiry_date || '' })),
})

/** A comparable fingerprint of what the user can edit, used to detect unsaved changes. */
const snap = (f) => JSON.stringify({
  c: f.contact || '', p: String(f.party_id ?? ''), d: f.schedule_date, s: String(f.source_location_id ?? ''), t: String(f.dest_location_id ?? ''),
  l: f.lines.map((l) => [String(l.product_id), Number(l.quantity), Number(l.unit_price), l.lot_no || '', l.expiry_date || '']),
})

// money is rounded to whole paise per line, half-up, exactly as the server does, so the preview matches what gets saved
const r2 = (n) => Math.round((Number(n) + Number.EPSILON) * 100 + 1e-7) / 100

function Totals({ lines }) {
  let sub = 0
  const groups = {}
  lines.forEach((l) => {
    const base = r2((Number(l.quantity) || 0) * (Number(l.unit_price) || 0))
    sub += base
    if (l.tax_name) {
      const k = `${l.tax_name}|${l.tax_rate}`
      groups[k] = groups[k] || { name: l.tax_name, rate: Number(l.tax_rate), amount: 0 }
      groups[k].amount += r2((base * l.tax_rate) / 100)
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

/** Ask how much was really received / shipped, and what to do about the rest. */
function ValidateModal({ op, verb, busy, onClose, onConfirm }) {
  const [done, setDone] = useState(() => Object.fromEntries(op.lines.map((l) => [l.id, String(l.quantity)])))
  const [backorder, setBackorder] = useState(true)
  const qty = (l) => Math.min(Math.max(Number(done[l.id]) || 0, 0), l.quantity)
  const short = op.lines.filter((l) => qty(l) < l.quantity)
  const nothing = op.lines.every((l) => qty(l) === 0)
  const restUnits = short.reduce((a, l) => a + (l.quantity - qty(l)), 0)

  return (
    <Modal
      width={640}
      title={`Validate ${op.reference}`}
      subtitle={`Enter what was actually ${verb}. Anything less than ordered can carry on as a backorder.`}
      onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={busy || nothing} onClick={() => onConfirm({ lines: op.lines.map((l) => ({ line_id: l.id, done_qty: qty(l) })), backorder })}>
          <Icon name="check" size={16} />Validate
        </button>
      </>}
    >
      <table className="detail-table">
        <thead><tr><th>Product</th><th className="num" style={{ width: 110 }}>Ordered</th><th className="num" style={{ width: 150 }}>{verb[0].toUpperCase() + verb.slice(1)}</th></tr></thead>
        <tbody>
          {op.lines.map((l) => (
            <tr key={l.id}>
              <td className="strong">{l.product}</td>
              <td className="num muted">{num(l.quantity)}</td>
              <td className="num"><input type="number" min="0" max={l.quantity} step="any" value={done[l.id]} onChange={(e) => setDone({ ...done, [l.id]: e.target.value })} /></td>
            </tr>
          ))}
        </tbody>
      </table>

      {nothing ? (
        <div className="form-error" style={{ marginTop: 14 }}><Icon name="alert" size={16} />Enter a quantity for at least one product.</div>
      ) : short.length ? (
        <div className="choice-group">
          <label className={`choice ${backorder ? 'on' : ''}`}>
            <input type="radio" checked={backorder} onChange={() => setBackorder(true)} />
            <span><b>Create a backorder</b><small>What's left ({num(restUnits)} unit{restUnits === 1 ? '' : 's'}) goes onto a new document you can complete later.</small></span>
          </label>
          <label className={`choice ${!backorder ? 'on' : ''}`}>
            <input type="radio" checked={!backorder} onChange={() => setBackorder(false)} />
            <span><b>No backorder</b><small>What's left ({num(restUnits)} unit{restUnits === 1 ? '' : 's'}) is cancelled.</small></span>
          </label>
        </div>
      ) : <p className="muted small" style={{ marginTop: 14 }}>Everything ordered is {verb}, so no backorder is needed.</p>}
    </Modal>
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
  const [conflict, setConflict] = useState(false)
  const [partialOpen, setPartialOpen] = useState(false)
  const [newParty, setNewParty] = useState(null)
  const [cache, setCache] = useState({}) // id -> product, for the tax and price of the products on this document
  const locs = useApi('/locations', { internal_only: true }).data || []
  const whs = useApi('/warehouses').data || []
  const partyKind = cfg?.type === 'IN' ? 'vendor' : cfg?.type === 'OUT' ? 'customer' : ''
  const parties = useApi('/parties', { kind: partyKind }, [kind])
  const contacts = useApi('/contacts', { type: cfg?.type }, [kind]).data || []

  const remember = (products) => setCache((c) => ({ ...c, ...Object.fromEntries(products.map((p) => [p.id, p])) }))

  const hydrate = (o) => {
    const f = toForm(o)
    baseline.current = snap(f)
    setOp(o)
    setForm(f)
    setConflict(false)
    const missing = o.lines.map((l) => l.product_id).filter((pid) => !cache[pid])
    if (missing.length) api('/products', { params: { ids: [...new Set(missing)].join(',') } }).then(remember).catch(() => {})
  }
  const reloadDoc = () => api(`/operations/${id}`).then((o) => { hydrate(o); notify('Reloaded the latest version', 'info') }).catch((e) => notify(e.message, 'error'))

  useEffect(() => {
    if (isNew) { setOp(null); setForm(blank()); baseline.current = snap(blank()); setConflict(false) }
    else api(`/operations/${id}`).then(hydrate).catch((e) => notify(e.message, 'error'))
    // eslint-disable-next-line
  }, [id, kind])

  const chosenWh = form.warehouse_id || (isNew ? whs[0]?.id : '') || ''
  if (!cfg) return <div className="muted">Unknown page</div>
  const status = op?.status || 'draft'
  const t = cfg.type
  const canEdit = canEditDocs(user, t) // may this person change the document itself?
  const open = isNew || ['draft', 'waiting', 'ready'].includes(status)
  const editable = open && canEdit
  const dirty = !isNew && editable && snap(form) !== baseline.current
  const priced = t !== 'ADJ'
  const usesParty = t === 'IN' || t === 'OUT'
  const shortLines = (op?.lines || []).filter((l) => l.short)
  const totalQty = form.lines.reduce((a, l) => a + (Number(l.quantity) || 0), 0)
  const prod = (pid) => cache[Number(pid)]
  const partyList = parties.data || []
  const selectedParty = partyList.find((p) => p.id === Number(form.party_id)) || (op?.party && op.party.id === Number(form.party_id) ? op.party : null)

  const setLine = (i, patch) => setForm({ ...form, lines: form.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) })
  const pickProduct = (i, p) => {
    remember([p])
    // receipts are bought at the purchase price, everything else is priced at the sales price
    setLine(i, { product_id: p.id, label: p.label, unit_price: t === 'IN' ? p.cost_price || p.unit_cost : p.unit_cost })
  }
  const pickParty = (e) => {
    const p = partyList.find((x) => x.id === Number(e.target.value))
    setForm({ ...form, party_id: e.target.value, contact: p ? p.name : form.contact })
  }
  const payload = () => ({
    type: t,
    warehouse_id: t !== 'INT' && chosenWh ? Number(chosenWh) : null,
    party_id: usesParty && form.party_id ? Number(form.party_id) : null,
    contact: form.contact || null,
    schedule_date: form.schedule_date,
    source_location_id: form.source_location_id ? Number(form.source_location_id) : null,
    dest_location_id: form.dest_location_id ? Number(form.dest_location_id) : null,
    version: isNew ? undefined : op?.version,
    lines: form.lines.filter((l) => l.product_id).map((l) => ({
      product_id: Number(l.product_id),
      quantity: Number(l.quantity),
      unit_price: l.unit_price === '' || l.unit_price == null ? null : Number(l.unit_price),
      ...(t === 'IN' ? { lot_no: l.lot_no || null, expiry_date: l.expiry_date || null } : {}),
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
    try { await fn() } catch (e) {
      if (CONFLICT.test(e.message)) setConflict(true)
      notify(e.message, 'error')
    }
    setBusy(false)
  }
  const UNSAVED = 'You have unsaved changes. Save them first (the order returns to Draft), or reload to discard.'
  const call = (target, action, body) => api(`/operations/${target.id}/${action}?version=${target.version}`, { method: 'POST', body })
  /** Run a workflow action. Drafts are saved first; later states must not be re-saved
   *  (saving sends the document back to Draft), so unsaved edits have to be dealt with first. */
  const act = (action) => guard(async () => {
    let target = op
    if (isNew || (status === 'draft' && canEdit)) target = await save()
    else if (dirty) throw new Error(UNSAVED)
    const o = await call(target, action)
    hydrate(o)
    if (o.message) notify(o.message, o.status === 'waiting' ? 'error' : 'info')
    else if (action === 'validate') notify(`${cfg.single} validated — stock updated`, 'ok')
    else if (action === 'pick') notify('Items picked — now pack them', 'ok')
    else if (action === 'pack') notify('Items packed — ready to validate', 'ok')
  })
  const validatePartial = (body) => guard(async () => {
    if (dirty) throw new Error(UNSAVED)
    const o = await call(op, 'validate', body)
    hydrate(o)
    setPartialOpen(false)
    notify(o.message || `${cfg.single} validated — stock updated`, o.message ? 'info' : 'ok')
  })()
  const duplicate = guard(async () => {
    const o = await call(op, 'duplicate')
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
  const canPartial = status === 'ready' && op?.lines.length > 0 && (t === 'IN' || (isDelivery && op?.packed))
  const [sheet, setSheet] = useState(null)
  useEffect(() => {
    const done = () => { document.body.classList.remove('printing-sheet'); setSheet(null) }
    window.addEventListener('afterprint', done)
    return () => window.removeEventListener('afterprint', done)
  }, [])
  const printAs = (kindOfSheet) => {
    setSheet(kindOfSheet)
    if (kindOfSheet) document.body.classList.add('printing-sheet')
    setTimeout(() => window.print(), 80)
  }
  const primary =
    status === 'draft' && (!isNew || canEdit) ? <button className="btn primary" disabled={busy} onClick={act('todo')}><Icon name="check" size={16} />To do</button>
    : status === 'waiting' ? <button className="btn" disabled={busy} onClick={act('check')}><Icon name="refresh" size={16} />Check availability</button>
    : status === 'ready' && isDelivery && !op?.picked ? <button className="btn primary" disabled={busy} onClick={act('pick')}><Icon name="box" size={16} />Mark picked</button>
    : status === 'ready' && isDelivery && !op?.packed ? <button className="btn primary" disabled={busy} onClick={act('pack')}><Icon name="box" size={16} />Mark packed</button>
    : status === 'ready' ? <button className="btn primary" disabled={busy} onClick={act('validate')}><Icon name="check" size={16} />Validate</button>
    : null

  return (
    <>
      <PageHeader
        back={<Link className="back no-print" to={`/operations/${kind}`}><Icon name="arrowleft" size={14} />{cfg.title}</Link>}
        title={isNew ? `New ${cfg.single.toLowerCase()}` : cfg.single}
        actions={
          <div className="ph-actions no-print">
            {primary}
            {!isNew && op && (
              <Menu align="right" trigger={(_, toggle) => <button className="btn" onClick={toggle}><Icon name="print" size={16} />Print<Icon name="down" size={14} className="caret" /></button>}>
                {sheetsFor(op).map((s) => <a key={s.id} className="menu-item slim" onClick={() => printAs(s.id)}><Icon name="print" size={16} />{s.label}</a>)}
                <a className="menu-item slim" onClick={() => printAs(null)}><Icon name="print" size={16} />This page</a>
              </Menu>
            )}
            {canPartial && <button className="btn" disabled={busy} onClick={() => setPartialOpen(true)}>Validate partially…</button>}
            {editable && <button className={`btn ${dirty ? 'primary' : ''}`} disabled={busy} onClick={guard(async () => { await save(); notify('Saved', 'ok') })}>Save</button>}
            {!isNew && priced && canEdit && <button className="btn ghost" disabled={busy} onClick={duplicate}>Duplicate</button>}
            {!isNew && canEdit && ['draft', 'waiting', 'ready'].includes(status) && <button className="btn danger" disabled={busy} onClick={act('cancel')}>Cancel</button>}
          </div>
        }
      />

      {conflict && (
        <div className="banner" role="alert">
          <Icon name="alert" size={18} />
          <div style={{ flex: 1 }}><b>Someone else changed this {cfg.single.toLowerCase()}</b>Your screen was out of date, so nothing was overwritten.</div>
          <button className="btn sm" onClick={reloadDoc}><Icon name="refresh" size={14} />Reload</button>
        </div>
      )}

      <div className="print-head">
        <div><b>StockSense</b><span>Inventory document</span></div>
        <div className="right"><b>{cfg.single} {op?.reference}</b><span>{op?.warehouse?.name} · printed {new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}</span></div>
      </div>
      {op && (op.party || op.contact) && usesParty && (
        <div className="print-party">
          <small>{t === 'IN' ? 'Supplier' : 'Customer'}</small>
          <b>{op.party?.name || op.contact}</b>
          {op.party?.address && <span>{op.party.address}</span>}
          {op.party?.gstin && <span>GSTIN {op.party.gstin}{op.party.state ? ` · ${op.party.state}` : ''}</span>}
        </div>
      )}

      {open && !canEdit && !isNew && (
        <div className="hint-box no-print" style={{ marginBottom: 16 }}>
          <Icon name="user" size={16} />
          <span>You can move this {cfg.single.toLowerCase()} through its stages, but only a manager can change what's on it.</span>
        </div>
      )}
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
            {op?.backorder_of && <Link className="chip-link no-print" to={`/operations/${PATH[op.backorder_of.type]}/${op.backorder_of.id}`}>Backorder of <span className="mono">{op.backorder_of.reference}</span></Link>}
            {op?.backorders?.map((b) => <Link key={b.id} className="chip-link no-print" to={`/operations/${PATH[b.type]}/${b.id}`}>Backorder <span className="mono">{b.reference}</span> · {b.status}</Link>)}
          </div>
          <Stepper flow={cfg.flow} current={status} />
        </div>
        {op && isDelivery && ['ready', 'done'].includes(status) && <PickPack op={op} />}
        <div className="card-pad">
          <div className="form-grid">
            {usesParty ? (
              <Field label={t === 'IN' ? 'Supplier' : 'Customer'}>
                <div className="inline">
                  <select disabled={!editable} value={form.party_id} onChange={pickParty}>
                    <option value="">{form.contact && !form.party_id ? `${form.contact} (not a saved contact)` : `Select a ${t === 'IN' ? 'supplier' : 'customer'}`}</option>
                    {op?.party && !partyList.some((p) => p.id === op.party.id) && <option value={op.party.id}>{op.party.name}</option>}
                    {partyList.map((p) => <option key={p.id} value={p.id}>{p.name}{p.gstin ? ` · ${p.gstin}` : ''}</option>)}
                  </select>
                  {editable && <button type="button" className="btn no-print" onClick={() => setNewParty({ name: form.party_id ? '' : form.contact })}><Icon name="plus" size={15} />New</button>}
                </div>
                {selectedParty && (selectedParty.gstin || selectedParty.address) && (
                  <span className="party-note">{[selectedParty.gstin && `GSTIN ${selectedParty.gstin}`, selectedParty.state, selectedParty.address].filter(Boolean).join(' · ')}</span>
                )}
              </Field>
            ) : (
              <Field label={cfg.partner}>
                <input disabled={!editable} list="contact-list" value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} placeholder="Type or pick a previous contact" />
                <datalist id="contact-list">{contacts.map((c) => <option key={c} value={c} />)}</datalist>
              </Field>
            )}
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
                const sub = r2((Number(l.quantity) || 0) * (Number(l.unit_price) || 0))
                return (
                  <tr key={i} className={bad ? 'short' : ''}>
                    <td>
                      {editable ? (
                        <ProductPicker label={l.label} onPick={(pp) => pickProduct(i, pp)} />
                      ) : <span className="strong">{ln?.product}</span>}
                      {t === 'IN' && (editable ? (
                        <div className="lot-row">
                          <input placeholder="Lot no. (optional)" maxLength={40} value={l.lot_no || ''} onChange={(e) => setLine(i, { lot_no: e.target.value })} />
                          <input type="date" title="Expiry date" value={l.expiry_date || ''} onChange={(e) => setLine(i, { expiry_date: e.target.value })} />
                        </div>
                      ) : (ln?.lot_no || ln?.expiry_date) && <span className="sub">{ln.lot_no ? `Lot ${ln.lot_no}` : ''}{ln.lot_no && ln.expiry_date ? ' · ' : ''}{ln.expiry_date ? `Expires ${new Date(ln.expiry_date).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}` : ''}</span>)}
                      {bad && <div className="line-warn"><Icon name="alert" size={13} />Short by {num(ln.missing)} — not in stock</div>}
                    </td>
                    <td className="num">
                      {editable ? <input type="number" min="0" step="any" value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} /> : (
                        <>{num(l.quantity)}{ln?.ordered_qty != null && ln.ordered_qty !== ln.quantity && <span className="sub">of {num(ln.ordered_qty)} ordered</span>}</>
                      )}
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
            ? <button className="btn sm no-print" onClick={() => setForm({ ...form, lines: [...form.lines, { product_id: '', label: '', quantity: 1, unit_price: '' }] })}><Icon name="plus" size={15} />New product line</button>
            : <span />}
          <span className="muted">Total quantity <b style={{ color: 'var(--text)', marginLeft: 6 }}>{num(totalQty)}</b></span>
        </div>
        {priced && <Totals lines={totalsLines} />}
      </div>

      <PrintSheet op={op} kind={sheet} />

      {!isNew && op && <History path={`/operations/${op.id}/history`} refreshKey={op.version} />}

      {partialOpen && op && (
        <ValidateModal op={op} verb={t === 'IN' ? 'received' : 'shipped'} busy={busy} onClose={() => setPartialOpen(false)} onConfirm={validatePartial} />
      )}
      {newParty && (
        <PartyModal
          defaults={{ ...newParty, kind: t === 'IN' ? 'vendor' : 'customer' }}
          onClose={() => setNewParty(null)}
          notify={notify}
          onSaved={(saved) => {
            setNewParty(null)
            if (saved) { parties.reload(); setForm((f) => ({ ...f, party_id: saved.id, contact: saved.name })); notify('Contact saved', 'ok') }
          }}
        />
      )}
      <Toast msg={toast.msg} kind={toast.kind} onClose={closeToast} />
    </>
  )
}
