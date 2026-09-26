import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, useDebounced } from '../hooks'
import { Search, Status, STATUS_LABEL, ViewToggle, num } from '../components/ui.jsx'

const KIND_PATH = { IN: 'receipts', OUT: 'deliveries', INT: 'transfers', ADJ: 'adjustments' }

export default function MoveHistory() {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [direction, setDirection] = useState('')
  const [view, setView] = useState('list')
  const dq = useDebounced(q)
  const { data } = useApi('/moves', { q: dq, status, direction })
  const nav = useNavigate()
  const rows = data || []
  const open = (r) => nav(`/operations/${KIND_PATH[r.type]}/${r.operation_id}`)

  return (
    <>
      <div className="head">
        <h1>Move History</h1>
        <div className="filters">
          <Search value={q} onChange={setQ} />
          <select value={direction} onChange={(e) => setDirection(e.target.value)}>
            <option value="">In &amp; Out</option>
            <option value="in">In</option>
            <option value="out">Out</option>
            <option value="transfer">Transfers</option>
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {['waiting', 'ready', 'done'].map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
          <ViewToggle view={view} setView={setView} />
        </div>
      </div>

      {view === 'list' ? (
        <div className="card">
          <table className="clickable">
            <thead><tr><th>Reference</th><th>Contact</th><th>Product</th><th>From</th><th>To</th><th>Quantity</th><th>Date</th><th>Status</th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className={`move ${r.direction}`} onClick={() => open(r)}>
                  <td>{r.reference}</td><td>{r.contact || '—'}</td><td>{r.product}</td>
                  <td>{r.from}</td><td>{r.to}</td>
                  <td>{r.direction === 'in' ? '+' : r.direction === 'out' ? '−' : ''}{num(r.quantity)}</td>
                  <td>{r.date}</td><td><Status value={r.status} /></td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan="8" className="muted">No moves yet.</td></tr>}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="kanban">
          {['waiting', 'ready', 'done'].map((s) => (
            <div key={s} className="col">
              <h4><Status value={s} /></h4>
              {rows.filter((r) => r.status === s).map((r, i) => (
                <div key={i} className={`card kcard move ${r.direction}`} onClick={() => open(r)}>
                  <b>{r.reference}</b>
                  <div>{r.product}</div>
                  <div className="muted small">{r.from} → {r.to}</div>
                  <div>{num(r.quantity)}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </>
  )
}
