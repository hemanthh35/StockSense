import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useApi } from '../hooks'
import { Icon } from '../components/icons.jsx'
import { atLeast } from '../perm.js'
import { Empty, PageHeader, STATUS_LABEL, Toast, fmtDate, money, num, useToast } from '../components/ui.jsx'

const CARD = {
  IN: { title: 'Receipts', icon: 'receive', tint: 'var(--mint-bg)', ink: 'var(--green)', to: '/operations/receipts', verb: 'to receive' },
  OUT: { title: 'Deliveries', icon: 'deliver', tint: 'var(--sky-bg)', ink: 'var(--blue)', to: '/operations/deliveries', verb: 'to deliver' },
  INT: { title: 'Internal transfers', icon: 'swap', tint: 'var(--lav-bg)', ink: 'var(--lav)', to: '/operations/transfers', verb: 'to move' },
  ADJ: { title: 'Adjustments', icon: 'sliders', tint: 'var(--butter-bg)', ink: 'var(--amber)', to: '/operations/adjustments', verb: 'logged' },
}
const SEGMENTS = ['draft', 'waiting', 'ready', 'done', 'cancelled']
const SEG_COLOR = { draft: 'var(--p-draft)', waiting: 'var(--p-waiting)', ready: 'var(--p-ready)', done: 'var(--p-done)', cancelled: 'var(--p-cancelled)' }
const KEY = 'stocksense_dash_filters'
const EMPTY = { doc_type: '', status: '', warehouse_id: '', location_id: '', category_id: '' }

function load() {
  try { return { ...EMPTY, ...JSON.parse(sessionStorage.getItem(KEY) || '{}') } } catch { return EMPTY }
}

function OpCard({ type, d, status }) {
  const c = CARD[type]
  const s = d.by_status
  const shown = status ? [status] : type === 'ADJ' ? ['done'] : SEGMENTS.slice(0, 3)
  const total = Math.max(shown.reduce((a, k) => a + s[k], 0), 1)
  return (
    <Link to={c.to} className="card opcard" style={{ '--tint': c.tint, '--ink': c.ink }}>
      <div className="opcard-top">
        <span className="chip"><Icon name={c.icon} size={18} /></span>
        {c.title}
        <Icon name="arrowupright" size={18} className="go" />
      </div>
      <div className="opcard-num"><b>{d.to_process}</b><span>{status ? STATUS_LABEL[status].toLowerCase() : c.verb}</span></div>
      <div className="bar" aria-hidden="true">
        {shown.map((k) => s[k] > 0 && <i key={k} style={{ width: `${(s[k] / total) * 100}%`, background: SEG_COLOR[k] }} />)}
      </div>
      <div className="legend">
        {shown.map((k) => <span key={k} style={{ '--c': SEG_COLOR[k] }}>{STATUS_LABEL[k]} {s[k]}</span>)}
      </div>
      <div className="opcard-foot">
        <span className={d.late ? 'late' : ''}>{d.late} late</span>
        <span>{d.waiting} waiting</span>
        <span>{d.operations} scheduled</span>
      </div>
    </Link>
  )
}

const KPIS = [
  ['stock_value', 'Stock value'],
  ['total_products_in_stock', 'Products in stock'],
  ['low_stock', 'Low stock', 'warn'],
  ['out_of_stock', 'Out of stock', 'neg'],
  ['pending_receipts', 'Pending receipts'],
  ['pending_deliveries', 'Pending deliveries'],
  ['internal_transfers_scheduled', 'Transfers scheduled'],
]

export default function Dashboard({ user }) {
  const canReorder = atLeast(user, 'manager')
  const [f, setF] = useState(load)
  useEffect(() => { try { sessionStorage.setItem(KEY, JSON.stringify(f)) } catch { /* private mode */ } }, [f])
  const { data } = useApi('/dashboard', f)
  const moves = useApi('/moves', { type: f.doc_type, status: f.status, warehouse_id: f.warehouse_id, location_id: f.location_id, category_id: f.category_id }).data
  const wh = useApi('/warehouses').data || []
  const locs = useApi('/locations', { internal_only: true, warehouse_id: f.warehouse_id }).data || []
  const cats = useApi('/categories').data || []
  const active = Object.values(f).filter(Boolean).length
  const nav = useNavigate()
  const [toast, notify, closeToast] = useToast()
  const reorder = async (ids) => {
    try {
      const o = await api('/reorder/receipt', { method: 'POST', body: { product_ids: ids, warehouse_id: f.warehouse_id ? Number(f.warehouse_id) : null } })
      nav(`/operations/receipts/${o.id}`)
    } catch (e) { notify(e.message, 'error') }
  }
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value, ...(k === 'warehouse_id' ? { location_id: '' } : {}) })

  return (
    <>
      <PageHeader title="Dashboard" subtitle="A live snapshot of your inventory operations." />

      <div className="card filterbar">
        <div className="filter-fields">
          <label><span>Document</span>
            <select value={f.doc_type} onChange={set('doc_type')}>
              <option value="">All documents</option>
              {Object.entries(CARD).map(([k, c]) => <option key={k} value={k}>{c.title}</option>)}
            </select>
          </label>
          <label><span>Status</span>
            <select value={f.status} onChange={set('status')}>
              <option value="">Open work</option>
              {SEGMENTS.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
            </select>
          </label>
          <label><span>Warehouse</span>
            <select value={f.warehouse_id} onChange={set('warehouse_id')}>
              <option value="">All warehouses</option>
              {wh.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </label>
          <label><span>Location</span>
            <select value={f.location_id} onChange={set('location_id')}>
              <option value="">All locations</option>
              {locs.map((l) => <option key={l.id} value={l.id}>{l.full_name}</option>)}
            </select>
          </label>
          <label><span>Category</span>
            <select value={f.category_id} onChange={set('category_id')}>
              <option value="">All categories</option>
              {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
        </div>
        {active > 0 && <button className="btn ghost sm" onClick={() => setF(EMPTY)}><Icon name="x" size={14} />Clear {active} filter{active > 1 ? 's' : ''}</button>}
      </div>

      {!data ? (
        <div className="grid3">{[0, 1, 2].map((i) => <div key={i} className="card opcard" style={{ height: 222 }}><span className="skeleton" style={{ width: '40%' }} /><span className="skeleton" style={{ width: '25%', height: 34 }} /></div>)}</div>
      ) : (
        <>
          <div className="grid3">
            {data.cards.map((c) => <OpCard key={c.type} type={c.type} d={c} status={f.status} />)}
          </div>

          <div className="section-title">Inventory snapshot</div>
          <div className="card kpi-strip">
            {KPIS.map(([k, label, tone]) => (
              <div key={k} className="kpi">
                <small>{label}</small>
                <b className={data.kpis[k] > 0 ? tone : ''}>{k === 'stock_value' ? money(data.kpis[k]) : data.kpis[k]}</b>
              </div>
            ))}
          </div>

          <div className="section-title">Attention</div>
          <div className="two-col">
            <div className="card">
              <div className="card-head">
                <h3>Low stock alerts</h3>
                {data.reorder_count > 0 && canReorder
                  ? <button className="btn primary sm" onClick={() => reorder(null)}><Icon name="receive" size={14} />Reorder {data.reorder_count} item{data.reorder_count > 1 ? 's' : ''}</button>
                  : <Link to="/stock" className="link small">View stock</Link>}
              </div>
              {data.low_stock_items.length === 0 ? (
                <Empty icon="check" title="All stocked up" hint="No product is at or below its reorder level." />
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Product</th><th>Level</th><th className="num">On hand</th><th className="num">Incoming</th><th>Suggested</th></tr></thead>
                    <tbody>
                      {data.low_stock_items.map((i) => {
                        const pct = i.reorder_min > 0 ? Math.min((i.on_hand / i.reorder_min) * 100, 100) : 0
                        return (
                          <tr key={i.product_id}>
                            <td className="strong">{i.name}<span className="sub mono">{i.sku}</span></td>
                            <td><span className={`meter ${i.on_hand <= 0 ? 'zero' : ''}`}><i style={{ width: `${pct}%` }} /></span></td>
                            <td className={`num ${i.on_hand <= 0 ? 'neg' : 'warn'}`}>{num(i.on_hand)}</td>
                            <td className="num muted">{i.incoming ? `+${num(i.incoming)}` : '—'}</td>
                            <td>
                              {i.suggested_qty > 0
                                ? <span className="inline" style={{ alignItems: 'center' }}><span className="suggest">Order {num(i.suggested_qty)}</span>{canReorder && <button className="btn sm" onClick={() => reorder([i.product_id])}>Create receipt</button>}</span>
                                : <span className="suggest ok">{i.incoming ? 'Covered by incoming' : 'No rule set'}</span>}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="card">
              <div className="card-head"><h3>Recent movements</h3><Link to="/moves" className="link small">All moves</Link></div>
              {!moves || moves.length === 0 ? (
                <Empty icon="swap" title="No movements" hint={active ? 'Nothing matches these filters.' : 'Validated receipts and deliveries show up here.'} />
              ) : (
                <ul className="feed">
                  {moves.slice(0, 6).map((m, i) => (
                    <li key={i}>
                      <span className={`mv ${m.direction}`}><Icon name={m.direction === 'in' ? 'receive' : m.direction === 'out' ? 'deliver' : 'swap'} size={16} /></span>
                      <span className="txt"><b>{m.product}</b><small className="mono">{m.reference} · {fmtDate(m.date)}</small></span>
                      <span className={`qty ${m.direction === 'in' ? 'pos' : m.direction === 'out' ? 'neg' : ''}`}>{m.direction === 'in' ? '+' : m.direction === 'out' ? '−' : ''}{num(m.quantity)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
      <Toast msg={toast.msg} kind={toast.kind} onClose={closeToast} />
    </>
  )
}
