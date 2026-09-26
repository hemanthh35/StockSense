import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useApi, useDebounced } from '../hooks'
import { Icon } from '../components/icons.jsx'
import {
  Empty, Field, PageHeader, Pager, SearchInput, Segmented, Status, Stepper, STATUS_LABEL, TableSkeleton,
  Toast, fmtDate, num, usePager, useToast,
} from '../components/ui.jsx'

export const KINDS = {
  receipts: { type: 'IN', title: 'Receipts', single: 'Receipt', sub: 'Incoming stock from vendors.', partner: 'Receive from', flow: ['draft', 'ready', 'done'] },
  deliveries: { type: 'OUT', title: 'Deliveries', single: 'Delivery', sub: 'Outgoing stock to customers.', partner: 'Delivery address', flow: ['draft', 'waiting', 'ready', 'done'] },
  transfers: { type: 'INT', title: 'Internal transfers', single: 'Transfer', sub: 'Move stock between locations.', partner: 'Reason / contact', flow: ['draft', 'waiting', 'ready', 'done'] },
  adjustments: { type: 'ADJ', title: 'Adjustments', single: 'Adjustment', sub: 'Inventory counts reconciled against records.', partner: 'Contact', flow: ['done'] },
}
const VIEW_OPTS = [{ value: 'list', label: 'List', icon: 'list' }, { value: 'kanban', label: 'Kanban', icon: 'kanban' }]
const COL_CAP = 8

function Kanban({ rows, statuses, open }) {
  const [more, setMore] = useState({})
  return (
    <div className="kanban">
      {statuses.filter((s) => s !== 'cancelled' || rows.some((o) => o.status === 'cancelled')).map((s) => {
        const col = rows.filter((o) => o.status === s)
        const shown = more[s] ? col : col.slice(0, COL_CAP)
        return (
          <div key={s} className="col">
            <div className="col-head"><Status value={s} /><span className="count">{col.length}</span></div>
            {shown.map((o) => (
              <button key={o.id} className="kcard" onClick={() => open(o)}>
                <div className="ref mono">{o.reference}</div>
                <div className="muted small" style={{ marginTop: 2 }}>{o.contact || 'No contact'}</div>
                <div className="meta"><span className={o.late ? 'neg' : ''}>{fmtDate(o.schedule_date)}</span>{o.late && <span className="neg">Late</span>}</div>
              </button>
            ))}
            {col.length > COL_CAP && !more[s] && <button className="col-more" onClick={() => setMore({ ...more, [s]: true })}>Show {col.length - COL_CAP} more</button>}
            {!col.length && <div className="col-empty">Nothing here</div>}
          </div>
        )
      })}
    </div>
  )
}

export function OperationList() {
  const { kind } = useParams()
  const cfg = KINDS[kind]
  const [view, setView] = useState('list')
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const dq = useDebounced(q)
  const { data } = useApi('/operations', { type: cfg?.type, q: dq, status }, [kind])
  const nav = useNavigate()
  const rows = data || []
  const pager = usePager(rows)
  useEffect(() => { setQ(''); setStatus('') }, [kind])
  if (!cfg) return <div className="muted">Unknown page</div>
  const open = (o) => nav(`/operations/${kind}/${o.id}`)
  const statuses = cfg.flow.concat(['cancelled'])
  const filtered = q || status

  return (
    <>
      <PageHeader
        title={cfg.title}
        subtitle={cfg.sub}
        actions={kind === 'adjustments'
          ? <Link className="btn primary" to="/stock"><Icon name="sliders" size={16} />Update stock</Link>
          : <Link className="btn primary" to={`/operations/${kind}/new`}><Icon name="plus" size={16} />New {cfg.single.toLowerCase()}</Link>}
      />
      <div className="card">
        <div className="toolbar">
          <SearchInput value={q} onChange={setQ} />
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {statuses.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
          <span className="grow" />
          <Segmented value={view} onChange={setView} options={VIEW_OPTS} />
        </div>

        {view === 'list' ? (
          <>
            <div className="table-wrap">
              <table className="rows">
                <thead><tr><th>Reference</th><th>Contact</th><th>Schedule date</th><th>Responsible</th><th>Status</th></tr></thead>
                <tbody>
                  {!data && <TableSkeleton cols={5} />}
                  {pager.slice.map((o) => (
                    <tr key={o.id} onClick={() => open(o)}>
                      <td className="mono strong">{o.reference}</td>
                      <td>{o.contact || <span className="dim">—</span>}</td>
                      <td>{fmtDate(o.schedule_date)}{o.late && <span className="late-flag"><Icon name="clock" size={13} />Late</span>}</td>
                      <td className="muted">{o.responsible || '—'}</td>
                      <td><Status value={o.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data && !rows.length && (
              <Empty
                title={filtered ? 'No matches' : `No ${cfg.title.toLowerCase()} yet`}
                hint={filtered ? 'Try a different search or status filter.' : cfg.sub}
                action={!filtered && kind !== 'adjustments' && <Link className="btn primary sm" to={`/operations/${kind}/new`}>Create the first one</Link>}
              />
            )}
            <Pager p={pager} />
          </>
        ) : (
          <Kanban rows={rows} statuses={statuses} open={open} />
        )}
      </div>
    </>
  )
}

const blank = () => ({ contact: '', schedule_date: new Date().toISOString().slice(0, 10), source_location_id: '', dest_location_id: '', lines: [] })

export function OperationDetail({ user }) {
  const { kind, id } = useParams()
  const cfg = KINDS[kind]
  const nav = useNavigate()
  const isNew = id === 'new'
  const [op, setOp] = useState(null)
  const [form, setForm] = useState(blank())
  const [toast, notify, closeToast] = useToast()
  const [busy, setBusy] = useState(false)
  const products = useApi('/products').data || []
  const locs = useApi('/locations', { internal_only: true }).data || []

  const hydrate = (o) => {
    setOp(o)
    setForm({
      contact: o.contact || '',
      schedule_date: o.schedule_date,
      source_location_id: o.source_location.id,
      dest_location_id: o.dest_location.id,
      lines: o.lines.map((l) => ({ product_id: l.product_id, quantity: l.quantity })),
    })
  }
  useEffect(() => {
    if (isNew) { setOp(null); setForm(blank()) }
    else api(`/operations/${id}`).then(hydrate).catch((e) => notify(e.message, 'error'))
    // eslint-disable-next-line
  }, [id, kind])

  if (!cfg) return <div className="muted">Unknown page</div>
  const status = op?.status || 'draft'
  const editable = isNew || ['draft', 'waiting', 'ready'].includes(status)
  const t = cfg.type
  const shortLines = (op?.lines || []).filter((l) => l.short)
  const totalQty = form.lines.reduce((a, l) => a + (Number(l.quantity) || 0), 0)

  const setLine = (i, patch) => setForm({ ...form, lines: form.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) })
  const payload = () => ({
    type: t,
    contact: form.contact || null,
    schedule_date: form.schedule_date,
    source_location_id: form.source_location_id ? Number(form.source_location_id) : null,
    dest_location_id: form.dest_location_id ? Number(form.dest_location_id) : null,
    lines: form.lines.filter((l) => l.product_id).map((l) => ({ product_id: Number(l.product_id), quantity: Number(l.quantity) })),
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
  const act = (action) => guard(async () => {
    const saved = editable ? await save() : op
    const o = await api(`/operations/${saved.id}/${action}`, { method: 'POST' })
    hydrate(o)
    if (o.message) notify(o.message, o.status === 'waiting' ? 'error' : 'info')
    else if (action === 'validate') notify(`${cfg.single} validated — stock updated`, 'ok')
  })

  const locSelect = (key, empty) => (
    <select disabled={!editable} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })}>
      <option value="">{empty}</option>
      {locs.map((l) => <option key={l.id} value={l.id}>{l.full_name}</option>)}
    </select>
  )

  return (
    <>
      <PageHeader
        back={<Link className="back no-print" to={`/operations/${kind}`}><Icon name="arrowleft" size={14} />{cfg.title}</Link>}
        title={isNew ? `New ${cfg.single.toLowerCase()}` : cfg.single}
        actions={
          <div className="ph-actions no-print">
            {status === 'draft' && <button className="btn primary" disabled={busy} onClick={act('todo')}><Icon name="check" size={16} />To do</button>}
            {status === 'waiting' && <button className="btn" disabled={busy} onClick={act('check')}><Icon name="refresh" size={16} />Check availability</button>}
            {status === 'ready' && <button className="btn primary" disabled={busy} onClick={act('validate')}><Icon name="check" size={16} />Validate</button>}
            {status === 'done' && <button className="btn" onClick={() => window.print()}><Icon name="print" size={16} />Print</button>}
            {editable && <button className="btn" disabled={busy} onClick={guard(async () => { await save(); notify('Saved', 'ok') })}>Save</button>}
            {!isNew && ['draft', 'waiting', 'ready'].includes(status) && <button className="btn danger" disabled={busy} onClick={act('cancel')}>Cancel</button>}
          </div>
        }
      />

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
        <div className="card-pad">
          <div className="form-grid">
            <Field label={cfg.partner}><input disabled={!editable} value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} placeholder="e.g. Azure Interior" /></Field>
            <Field label="Schedule date"><input type="date" disabled={!editable} value={form.schedule_date} onChange={(e) => setForm({ ...form, schedule_date: e.target.value })} /></Field>
            <Field label="Responsible"><input disabled value={op?.responsible || user.login_id} /></Field>
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
            <thead><tr><th>Product</th><th className="num" style={{ width: 170 }}>Quantity</th><th style={{ width: 52 }} /></tr></thead>
            <tbody>
              {form.lines.map((l, i) => {
                const ln = op?.lines[i]
                const bad = !editable ? false : ln?.short && op.lines.length === form.lines.length
                return (
                  <tr key={i} className={bad ? 'short' : ''}>
                    <td>
                      {editable ? (
                        <select value={l.product_id} onChange={(e) => setLine(i, { product_id: e.target.value })}>
                          <option value="">Select product</option>
                          {products.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                        </select>
                      ) : <span className="strong">{ln?.product}</span>}
                      {bad && <div className="line-warn"><Icon name="alert" size={13} />Short by {num(ln.missing)} — not in stock</div>}
                    </td>
                    <td className="num">
                      {editable ? <input type="number" min="0" step="any" value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} /> : num(l.quantity)}
                    </td>
                    <td>{editable && <button className="icon-btn line-x no-print" aria-label="Remove line" onClick={() => setForm({ ...form, lines: form.lines.filter((_, j) => j !== i) })}><Icon name="x" size={16} /></button>}</td>
                  </tr>
                )
              })}
              {!form.lines.length && <tr><td colSpan="3" className="muted" style={{ height: 80, textAlign: 'center' }}>No products yet</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="table-foot">
          {editable
            ? <button className="btn sm no-print" onClick={() => setForm({ ...form, lines: [...form.lines, { product_id: '', quantity: 1 }] })}><Icon name="plus" size={15} />New product line</button>
            : <span />}
          <span className="muted">Total quantity <b style={{ color: 'var(--text)', marginLeft: 6 }}>{num(totalQty)}</b></span>
        </div>
      </div>
      <Toast msg={toast.msg} kind={toast.kind} onClose={closeToast} />
    </>
  )
}
