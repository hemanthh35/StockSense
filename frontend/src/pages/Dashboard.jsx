import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks'
import { num } from '../components/ui.jsx'

function OpCard({ title, to, verb, d }) {
  return (
    <Link to={to} className="card opcard">
      <h3>{title}</h3>
      <div className="big">{d.to_process} <span>to {verb}</span></div>
      <div className="stats">
        <span className={d.late ? 'red' : 'muted'}>{d.late} Late</span>
        <span className="muted">{d.waiting} waiting</span>
        <span className="muted">{d.operations} operations</span>
      </div>
    </Link>
  )
}

export default function Dashboard() {
  const [f, setF] = useState({ warehouse_id: '', category_id: '' })
  const { data } = useApi('/dashboard', f)
  const wh = useApi('/warehouses').data || []
  const cats = useApi('/categories').data || []
  if (!data) return <div className="muted">Loading…</div>
  const k = data.kpis
  return (
    <>
      <div className="head">
        <h1>Dashboard</h1>
        <div className="filters">
          <select value={f.warehouse_id} onChange={(e) => setF({ ...f, warehouse_id: e.target.value })}>
            <option value="">All warehouses</option>
            {wh.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
          <select value={f.category_id} onChange={(e) => setF({ ...f, category_id: e.target.value })}>
            <option value="">All categories</option>
            {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
      </div>

      <div className="grid cards3">
        <OpCard title="Reciept" to="/operations/receipts" verb="receive" d={data.receipt} />
        <OpCard title="Delivery" to="/operations/deliveries" verb="Deliver" d={data.delivery} />
        <OpCard title="Internal Transfers" to="/operations/transfers" verb="move" d={data.internal} />
      </div>

      <h2>Inventory snapshot</h2>
      <div className="grid kpis">
        <div className="card kpi"><b>{k.total_products_in_stock}</b>Products in stock</div>
        <div className="card kpi"><b className={k.low_stock ? 'amber' : ''}>{k.low_stock}</b>Low stock</div>
        <div className="card kpi"><b className={k.out_of_stock ? 'red' : ''}>{k.out_of_stock}</b>Out of stock</div>
        <div className="card kpi"><b>{k.pending_receipts}</b>Pending receipts</div>
        <div className="card kpi"><b>{k.pending_deliveries}</b>Pending deliveries</div>
        <div className="card kpi"><b>{k.internal_transfers_scheduled}</b>Transfers scheduled</div>
      </div>

      {data.low_stock_items.length > 0 && (
        <>
          <h2>Low stock alerts</h2>
          <div className="card">
            <table>
              <thead><tr><th>Product</th><th>On hand</th><th>Reorder at</th></tr></thead>
              <tbody>
                {data.low_stock_items.map((i) => (
                  <tr key={i.product_id}>
                    <td>[{i.sku}] {i.name}</td>
                    <td className={i.on_hand <= 0 ? 'red' : 'amber'}>{num(i.on_hand)}</td>
                    <td>{num(i.reorder_min)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  )
}
