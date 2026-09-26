import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, useDebounced } from '../hooks'
import { Icon } from '../components/icons.jsx'
import { Empty, PageHeader, Pager, SearchInput, Segmented, Status, STATUS_LABEL, TableSkeleton, fmtDate, num, usePager } from '../components/ui.jsx'

const KIND_PATH = { IN: 'receipts', OUT: 'deliveries', INT: 'transfers', ADJ: 'adjustments' }
const VIEW_OPTS = [{ value: 'list', label: 'List', icon: 'list' }, { value: 'kanban', label: 'Kanban', icon: 'kanban' }]
const sign = (d) => (d === 'in' ? '+' : d === 'out' ? '−' : '')

export default function MoveHistory() {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [direction, setDirection] = useState('')
  const [wh, setWh] = useState('')
  const whs = useApi('/warehouses').data || []
  const [view, setView] = useState('list')
  const dq = useDebounced(q)
  const { data } = useApi('/moves', { q: dq, status, direction, warehouse_id: wh })
  const nav = useNavigate()
  const rows = data || []
  const pager = usePager(rows)
  const open = (r) => nav(`/operations/${KIND_PATH[r.type]}/${r.operation_id}`)

  return (
    <>
      <PageHeader title="Move history" subtitle="Every stock movement between locations. Incoming moves are green, outgoing are red." />
      <div className="card">
        <div className="toolbar">
          <SearchInput value={q} onChange={setQ} />
          <select value={direction} onChange={(e) => setDirection(e.target.value)}>
            <option value="">In &amp; out</option>
            <option value="in">Incoming</option>
            <option value="out">Outgoing</option>
            <option value="transfer">Transfers</option>
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {['waiting', 'ready', 'done'].map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
          {whs.length > 1 && (
            <select value={wh} onChange={(e) => setWh(e.target.value)}>
              <option value="">All warehouses</option>
              {whs.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          )}
          <span className="grow" />
          <Segmented value={view} onChange={setView} options={VIEW_OPTS} />
        </div>

        {view === 'list' ? (
          <>
            <div className="table-wrap">
              <table className="rows">
                <thead><tr><th>Reference</th><th>Contact</th><th>Product</th><th>Route</th><th className="num">Quantity</th><th>Date</th><th>Status</th></tr></thead>
                <tbody>
                  {!data && <TableSkeleton cols={7} />}
                  {pager.slice.map((r, i) => (
                    <tr key={i} className={`move ${r.direction}`} onClick={() => open(r)}>
                      <td className="mono strong">{r.reference}</td>
                      <td>{r.contact || <span className="dim">—</span>}</td>
                      <td>{r.product}</td>
                      <td><span className="route"><span className="mono">{r.from}</span><Icon name="arrowright" size={13} /><span className="mono">{r.to}</span></span></td>
                      <td className="num"><span className={`dir ${r.direction}`}>{sign(r.direction)}{num(r.quantity)}</span></td>
                      <td className="muted">{fmtDate(r.date)}</td>
                      <td><Status value={r.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data && !rows.length && <Empty icon="swap" title="No moves found" hint="Moves appear once a receipt, delivery or transfer is ready or done." />}
            <Pager p={pager} />
          </>
        ) : (
          <div className="kanban">
            {['waiting', 'ready', 'done'].map((s) => {
              const col = rows.filter((r) => r.status === s)
              return (
                <div key={s} className="col">
                  <div className="col-head"><Status value={s} /><span className="count">{col.length}</span></div>
                  {col.slice(0, 20).map((r, i) => (
                    <button key={i} className={`kcard ${r.direction}`} onClick={() => open(r)}>
                      <div className="ref mono">{r.reference}</div>
                      <div style={{ marginTop: 4 }}>{r.product}</div>
                      <div className="meta"><span className="mono">{r.from} → {r.to}</span><span className={`dir ${r.direction}`}>{sign(r.direction)}{num(r.quantity)}</span></div>
                    </button>
                  ))}
                  {col.length > 20 && <div className="col-empty">+{col.length - 20} more — use list view</div>}
                  {!col.length && <div className="col-empty">Nothing here</div>}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </>
  )
}
