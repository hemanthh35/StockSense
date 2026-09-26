import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useApi, useDebounced } from '../hooks'
import { Icon } from '../components/icons.jsx'
import {
  Empty, PageHeader, Pager, SearchInput, Segmented, Status, STATUS_LABEL, TableSkeleton, fmtDate, money, usePager,
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
                <thead><tr><th>Reference</th><th>Contact</th><th>Schedule date</th><th>Responsible</th>{kind !== 'adjustments' && <th className="num">Total</th>}<th>Status</th></tr></thead>
                <tbody>
                  {!data && <TableSkeleton cols={6} />}
                  {pager.slice.map((o) => (
                    <tr key={o.id} onClick={() => open(o)}>
                      <td className="mono strong">{o.reference}</td>
                      <td>{o.contact || <span className="dim">—</span>}</td>
                      <td>{fmtDate(o.schedule_date)}{o.late && <span className="late-flag"><Icon name="clock" size={13} />Late</span>}</td>
                      <td className="muted">{o.responsible || '—'}</td>
                      {kind !== 'adjustments' && <td className="num">{money(o.total)}</td>}
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
