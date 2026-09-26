import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi, usePaged } from '../hooks'
import { Empty, PageHeader, Pager, TableSkeleton, num } from '../components/ui.jsx'

const LEVEL = { out: 'Out of stock', critical: 'Under a week', soon: 'Under 2 weeks', ok: 'Fine' }
const day = (d) => new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })

/** How long each product will last at the recent pace of deliveries. */
export default function Forecast({ tabs }) {
  const [days, setDays] = useState(30)
  const [wh, setWh] = useState('')
  const [only, setOnly] = useState('')
  const whs = useApi('/warehouses').data || []
  const pager = usePaged('/reports/forecast', { days, warehouse_id: wh, level: only }, { size: 10, deps: [days, wh, only] })
  const c = pager.data?.counts
  const rows = pager.rows

  return (
    <>
      <PageHeader title="Stock" subtitle="How long each product will last, based on what you delivered recently. Soonest to run out first." />
      {tabs}
      <div className="tiles">
        {['out', 'critical', 'soon', 'ok'].map((k) => (
          <button key={k} className={`card tile tile-btn ${only === k ? 'on' : ''}`} onClick={() => setOnly(only === k ? '' : k)}>
            <small>{LEVEL[k]}</small>
            <b className={k === 'ok' ? 'pos' : k === 'soon' ? '' : 'neg'}>{c ? c[k] : '…'}</b>
            <span className="muted small">products</span>
          </button>
        ))}
      </div>
      <div className="card">
        <div className="toolbar">
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Pace of last 7 days</option><option value={30}>Pace of last 30 days</option><option value={90}>Pace of last 90 days</option>
          </select>
          <select value={wh} onChange={(e) => setWh(e.target.value)}>
            <option value="">All warehouses</option>
            {whs.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Product</th><th className="num">On hand</th><th className="num">Selling / day</th><th className="num">Days left</th><th>Runs out</th><th className="num">On order</th></tr></thead>
            <tbody>
              {pager.loading && !rows.length && <TableSkeleton cols={6} />}
              {rows.map((r) => (
                <tr key={r.product_id}>
                  <td className="strong"><Link to={`/products?q=${encodeURIComponent(r.sku)}`}>{r.name}</Link><span className="sub mono">{r.sku}</span></td>
                  <td className="num">{num(r.on_hand)}</td>
                  <td className="num muted">{num(r.per_day)}</td>
                  <td className="num"><span className={`lvl lvl-${r.level}`}>{r.level === 'out' ? 'None' : `${num(r.days_left)} days`}</span></td>
                  <td>{r.runs_out_on ? day(r.runs_out_on) : <span className="dim">Now</span>}</td>
                  <td className="num">{r.incoming ? num(r.incoming) : <span className="dim">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!pager.loading && !rows.length && <Empty icon="box" title="Nothing to forecast" hint="Once you validate some deliveries, the days of stock left show up here." />}
        <Pager p={pager} />
      </div>
    </>
  )
}
