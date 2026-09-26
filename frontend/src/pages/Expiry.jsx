import { useState } from 'react'
import { Link } from 'react-router-dom'
import { usePaged, useDebounced } from '../hooks'
import { Empty, PageHeader, Pager, SearchInput, TableSkeleton, money, num } from '../components/ui.jsx'

const LEVELS = [['expired', 'Expired', 'neg'], ['soon', 'Expiring soon', ''], ['ok', 'Later', 'pos'], ['none', 'No expiry', '']]
const day = (d) => (d ? new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—')
const left = (r) => (r.days_left == null ? '' : r.days_left < 0 ? `${-r.days_left} days ago` : r.days_left === 0 ? 'Today' : `in ${r.days_left} days`)

/** Batches still on the shelf, earliest expiry first. Lots are created by receipts that carry a lot number or expiry date. */
export default function Expiry({ tabs }) {
  const [q, setQ] = useState('')
  const [days, setDays] = useState(30)
  const [only, setOnly] = useState('')
  const dq = useDebounced(q)
  const pager = usePaged('/lots', { q: dq, days, status: only }, { size: 10, deps: [dq, days, only] })
  const s = pager.data?.summary
  const count = { expired: s?.expired, soon: s?.expiring_soon, ok: s?.later, none: s?.no_expiry }

  return (
    <>
      <PageHeader title="Stock" subtitle="Batches on your shelves by expiry date. Deliveries use the batch that expires first." />
      {tabs}
      <div className="tiles">
        {LEVELS.map(([k, label, tone]) => (
          <button key={k} className={`card tile tile-btn ${only === k ? 'on' : ''}`} onClick={() => setOnly(only === k ? '' : k)}>
            <small>{k === 'soon' ? `Expiring in ${days} days` : label}</small>
            <b className={count[k] > 0 ? tone : ''}>{s ? count[k] : '…'}</b>
            <span className="muted small">{k === 'expired' && s?.expired_value ? `${money(s.expired_value)} at cost` : 'batches'}</span>
          </button>
        ))}
      </div>
      <div className="card">
        <div className="toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search product, SKU or lot" />
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Soon = 7 days</option><option value={30}>Soon = 30 days</option><option value={60}>Soon = 60 days</option><option value={90}>Soon = 90 days</option>
          </select>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Product</th><th>Lot</th><th>Expires</th><th className="num">Left</th><th className="num">Value</th><th>Received</th></tr></thead>
            <tbody>
              {pager.loading && !pager.rows.length && <TableSkeleton cols={6} />}
              {pager.rows.map((r) => (
                <tr key={r.id}>
                  <td className="strong"><Link to={`/products?q=${encodeURIComponent(r.sku)}`}>{r.name}</Link><span className="sub mono">{r.sku}</span></td>
                  <td className="mono">{r.lot_no}</td>
                  <td>{r.expiry_date ? <span className={`lvl lvl-${r.level === 'expired' ? 'out' : r.level}`}>{day(r.expiry_date)}</span> : <span className="dim">—</span>}<span className="sub">{left(r)}</span></td>
                  <td className="num">{num(r.remaining)}</td>
                  <td className="num muted">{money(r.value)}</td>
                  <td className="muted">{r.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!pager.loading && !pager.rows.length && <Empty icon="box" title="No batches" hint="Add a lot number and expiry date on a receipt line. When the receipt is validated, the batch shows up here." />}
        <Pager p={pager} />
      </div>
    </>
  )
}
