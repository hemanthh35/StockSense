import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useApi, useDebounced } from '../hooks'
import { Search, Status, Steps, STATUS_LABEL, Toast, useToast, ViewToggle, num } from '../components/ui.jsx'

export const KINDS = {
  receipts: { type: 'IN', title: 'Reciepts', single: 'Receipt', partner: 'Receive From', flow: ['draft', 'ready', 'done'] },
  deliveries: { type: 'OUT', title: 'Delivery', single: 'Delivery', partner: 'Delivery Adress', flow: ['draft', 'waiting', 'ready', 'done'] },
  transfers: { type: 'INT', title: 'Internal Transfers', single: 'Transfer', partner: 'Reason / Contact', flow: ['draft', 'waiting', 'ready', 'done'] },
  adjustments: { type: 'ADJ', title: 'Adjustments', single: 'Adjustment', partner: 'Contact', flow: ['done'] },
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
  if (!cfg) return <div>Unknown page</div>
  const rows = data || []
  const open = (o) => nav(`/operations/${kind}/${o.id}`)
  const statuses = cfg.flow.concat(['cancelled'])

  return (
    <>
      <div className="head">
        <h1>{cfg.title}</h1>
        <div className="filters">
          {kind !== 'adjustments' ? (
            <Link className="btn primary" to={`/operations/${kind}/new`}>NEW</Link>
          ) : (
            <Link className="btn primary" to="/stock">Update stock</Link>
          )}
          <Search value={q} onChange={setQ} />
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {statuses.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
          <ViewToggle view={view} setView={setView} />
        </div>
      </div>

      {view === 'list' ? (
        <div className="card">
          <table className="clickable">
            <thead><tr><th>Reference</th><th>Contact</th><th>Schedule date</th><th>Status</th></tr></thead>
            <tbody>
              {rows.map((o) => (
                <tr key={o.id} onClick={() => open(o)}>
                  <td>{o.reference}</td>
                  <td>{o.contact || '—'}</td>
                  <td className={o.late ? 'red' : ''}>{o.schedule_date}{o.late && ' (Late)'}</td>
                  <td><Status value={o.status} /></td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan="4" className="muted">Nothing here yet.</td></tr>}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="kanban">
          {statuses.map((s) => (
            <div key={s} className="col">
              <h4><Status value={s} /> <span className="muted">{rows.filter((o) => o.status === s).length}</span></h4>
              {rows.filter((o) => o.status === s).map((o) => (
                <div key={o.id} className="card kcard" onClick={() => open(o)}>
                  <b>{o.reference}</b>
                  <div className="muted">{o.contact || '—'}</div>
                  <div className={o.late ? 'red small' : 'muted small'}>{o.schedule_date}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </>
  )
}

const blank = { contact: '', schedule_date: new Date().toISOString().slice(0, 10), source_location_id: '', dest_location_id: '', lines: [] }

export function OperationDetail({ user }) {
  const { kind, id } = useParams()
  const cfg = KINDS[kind]
  const nav = useNavigate()
  const isNew = id === 'new'
  const [op, setOp] = useState(null)
  const [form, setForm] = useState(blank)
  const [toast, notify, closeToast] = useToast()
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
    if (isNew) { setOp(null); setForm(blank) }
    else api(`/operations/${id}`).then(hydrate).catch((e) => notify(e.message, 'error'))
    // eslint-disable-next-line
  }, [id, kind])

  if (!cfg) return <div>Unknown page</div>
  const status = op?.status || 'draft'
  const editable = isNew || ['draft', 'waiting', 'ready'].includes(status)
  const t = cfg.type
  const short = Object.fromEntries((op?.lines || []).map((l, i) => [i, l]))

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
  const guard = (fn) => async () => { try { await fn() } catch (e) { notify(e.message, 'error') } }
  const act = (action) => guard(async () => {
    const saved = editable ? await save() : op
    const o = await api(`/operations/${saved.id}/${action}`, { method: 'POST' })
    hydrate(o)
    if (o.message) notify(o.message, o.status === 'waiting' ? 'error' : 'info')
    else if (action === 'validate') notify(`${cfg.single} validated`, 'ok')
  })

  return (
    <>
      <div className="head no-print">
        <h1>{cfg.single}</h1>
        <div className="filters">
          <Link className="btn" to={`/operations/${kind}/new`}>New</Link>
          {status === 'draft' && <button className="btn primary" onClick={act('todo')}>TO DO</button>}
          {status === 'waiting' && <button className="btn" onClick={act('check')}>Check availability</button>}
          {status === 'ready' && <button className="btn primary" onClick={act('validate')}>Validate</button>}
          {status === 'done' && <button className="btn" onClick={() => window.print()}>Print</button>}
          {!isNew && ['draft', 'waiting', 'ready'].includes(status) && <button className="btn danger" onClick={act('cancel')}>Cancel</button>}
          {editable && <button className="btn" onClick={guard(async () => { await save(); notify('Saved', 'ok') })}>Save</button>}
        </div>
      </div>

      <div className="card">
        <div className="head">
          <h2 className="ref">{op?.reference || 'New'}</h2>
          <Steps flow={cfg.flow} current={status} />
        </div>
        <div className="form2">
          <label>{cfg.partner}
            <input disabled={!editable} value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} />
          </label>
          <label>Schedule Date
            <input type="date" disabled={!editable} value={form.schedule_date} onChange={(e) => setForm({ ...form, schedule_date: e.target.value })} />
          </label>
          <label>Responsible
            <input disabled value={op?.responsible || user.login_id} />
          </label>
          {t === 'INT' ? (
            <>
              <label>From
                <select disabled={!editable} value={form.source_location_id} onChange={(e) => setForm({ ...form, source_location_id: e.target.value })}>
                  <option value="">Select…</option>
                  {locs.map((l) => <option key={l.id} value={l.id}>{l.full_name}</option>)}
                </select>
              </label>
              <label>To
                <select disabled={!editable} value={form.dest_location_id} onChange={(e) => setForm({ ...form, dest_location_id: e.target.value })}>
                  <option value="">Select…</option>
                  {locs.map((l) => <option key={l.id} value={l.id}>{l.full_name}</option>)}
                </select>
              </label>
            </>
          ) : (
            <label>{t === 'IN' ? 'Receive into' : 'Ship from'}
              <select
                disabled={!editable}
                value={t === 'IN' ? form.dest_location_id : form.source_location_id}
                onChange={(e) => setForm({ ...form, [t === 'IN' ? 'dest_location_id' : 'source_location_id']: e.target.value })}
              >
                <option value="">Default location</option>
                {locs.map((l) => <option key={l.id} value={l.id}>{l.full_name}</option>)}
              </select>
            </label>
          )}
          {t === 'OUT' && <label>Operation type<input disabled value="Delivery Order" /></label>}
        </div>

        <h3>Products</h3>
        <table>
          <thead><tr><th>Product</th><th style={{ width: 140 }}>Quantity</th><th style={{ width: 40 }} /></tr></thead>
          <tbody>
            {form.lines.map((l, i) => {
              const bad = short[i]?.short
              return (
                <tr key={i} className={bad ? 'shortage' : ''}>
                  <td>
                    {editable ? (
                      <select value={l.product_id} onChange={(e) => setLine(i, { product_id: e.target.value })}>
                        <option value="">Select product…</option>
                        {products.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                      </select>
                    ) : short[i]?.product}
                    {bad && <div className="small red">Not in stock — short by {num(short[i].missing)}</div>}
                  </td>
                  <td>
                    {editable ? <input type="number" min="0" step="any" value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} /> : num(l.quantity)}
                  </td>
                  <td>{editable && <a className="x" onClick={() => setForm({ ...form, lines: form.lines.filter((_, j) => j !== i) })}>✕</a>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {editable && (
          <div className="rowgap">
            <button className="btn" onClick={() => setForm({ ...form, lines: [...form.lines, { product_id: '', quantity: 1 }] })}>+ New Product</button>
            <Link className="small" to="/products?new=1">Add New product</Link>
          </div>
        )}
      </div>
      <Toast msg={toast.msg} kind={toast.kind} onClose={closeToast} />
    </>
  )
}
