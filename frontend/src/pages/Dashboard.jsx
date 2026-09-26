import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks'
import { Icon } from '../components/icons.jsx'
import { Empty, PageHeader, Status, fmtDate, num } from '../components/ui.jsx'

function OpCard({ title, icon, tint, ink, to, verb, d }) {
  const s = d.by_status
  const total = Math.max(s.draft + s.waiting + s.ready, 1)
  return (
    <Link to={to} className="card opcard" style={{ '--tint': tint, '--ink': ink }}>
      <div className="opcard-top">
        <span className="chip"><Icon name={icon} size={18} /></span>
        {title}
        <Icon name="arrowupright" size={18} className="go" />
      </div>
      <div className="opcard-num"><b>{d.to_process}</b><span>to {verb}</span></div>
      <div className="bar" aria-hidden="true">
        {['draft', 'waiting', 'ready'].map((k) => s[k] > 0 && <i key={k} className={`b-${k}`} style={{ width: `${(s[k] / total) * 100}%` }} />)}
      </div>
      <div className="legend">
        <span style={{ '--c': 'var(--p-draft)' }}>Draft {s.draft}</span>
        <span style={{ '--c': 'var(--p-waiting)' }}>Waiting {s.waiting}</span>
        <span style={{ '--c': 'var(--p-ready)' }}>Ready {s.ready}</span>
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
  ['total_products_in_stock', 'Products in stock'],
  ['low_stock', 'Low stock', 'warn'],
  ['out_of_stock', 'Out of stock', 'neg'],
  ['pending_receipts', 'Pending receipts'],
  ['pending_deliveries', 'Pending deliveries'],
  ['internal_transfers_scheduled', 'Transfers scheduled'],
]

export default function Dashboard() {
  const [f, setF] = useState({ warehouse_id: '', category_id: '' })
  const { data } = useApi('/dashboard', f)
  const moves = useApi('/moves', { warehouse_id: f.warehouse_id }).data
  const wh = useApi('/warehouses').data || []
  const cats = useApi('/categories').data || []

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="A live snapshot of your inventory operations."
        actions={
          <>
            <select value={f.warehouse_id} onChange={(e) => setF({ ...f, warehouse_id: e.target.value })} style={{ width: 180 }}>
              <option value="">All warehouses</option>
              {wh.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
            <select value={f.category_id} onChange={(e) => setF({ ...f, category_id: e.target.value })} style={{ width: 170 }}>
              <option value="">All categories</option>
              {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </>
        }
      />

      {!data ? (
        <div className="grid3">{[0, 1, 2].map((i) => <div key={i} className="card opcard" style={{ height: 222 }}><span className="skeleton" style={{ width: '40%' }} /><span className="skeleton" style={{ width: '25%', height: 34 }} /></div>)}</div>
      ) : (
        <>
          <div className="grid3">
            <OpCard title="Receipts" icon="receive" tint="var(--mint-bg)" ink="var(--green)" to="/operations/receipts" verb="receive" d={data.receipt} />
            <OpCard title="Deliveries" icon="deliver" tint="var(--sky-bg)" ink="var(--blue)" to="/operations/deliveries" verb="deliver" d={data.delivery} />
            <OpCard title="Internal transfers" icon="swap" tint="var(--lav-bg)" ink="var(--lav)" to="/operations/transfers" verb="move" d={data.internal} />
          </div>

          <div className="section-title">Inventory snapshot</div>
          <div className="card kpi-strip">
            {KPIS.map(([k, label, tone]) => (
              <div key={k} className="kpi">
                <small>{label}</small>
                <b className={data.kpis[k] > 0 ? tone : ''}>{data.kpis[k]}</b>
              </div>
            ))}
          </div>

          <div className="section-title">Attention</div>
          <div className="two-col">
            <div className="card">
              <div className="card-head"><h3>Low stock alerts</h3><Link to="/stock" className="link small">View stock</Link></div>
              {data.low_stock_items.length === 0 ? (
                <Empty icon="check" title="All stocked up" hint="No product is at or below its reorder level." />
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Product</th><th>Level</th><th className="num">On hand</th><th className="num">Reorder at</th></tr></thead>
                    <tbody>
                      {data.low_stock_items.map((i) => {
                        const pct = i.reorder_min > 0 ? Math.min((i.on_hand / i.reorder_min) * 100, 100) : 0
                        return (
                          <tr key={i.product_id}>
                            <td className="strong">{i.name}<span className="sub mono">{i.sku}</span></td>
                            <td><span className={`meter ${i.on_hand <= 0 ? 'zero' : ''}`}><i style={{ width: `${pct}%` }} /></span></td>
                            <td className={`num ${i.on_hand <= 0 ? 'neg' : 'warn'}`}>{num(i.on_hand)}</td>
                            <td className="num">{num(i.reorder_min)}</td>
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
                <Empty icon="swap" title="No movements yet" hint="Validated receipts and deliveries show up here." />
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
    </>
  )
}
