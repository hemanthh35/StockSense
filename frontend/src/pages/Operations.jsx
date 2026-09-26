import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useApi, useDebounced, usePaged } from '../hooks'
import { canEditDocs } from '../perm.js'
import { Icon } from '../components/icons.jsx'
import {
  Empty, ExportButton, PageHeader, Pager, SearchInput, Segmented, Status, STATUS_LABEL, TableSkeleton, fmtDate, money,
} from '../components/ui.jsx'

export const KINDS = {
  receipts: { type: 'IN', title: 'Receipts', single: 'Receipt', sub: 'Incoming stock from vendors.', partner: 'Receive from', flow: ['draft', 'ready', 'done'] },
  deliveries: { type: 'OUT', title: 'Deliveries', single: 'Delivery', sub: 'Outgoing stock to customers.', partner: 'Delivery address', flow: ['draft', 'waiting', 'ready', 'done'] },
  transfers: { type: 'INT', title: 'Internal transfers', single: 'Transfer', sub: 'Move stock between locations.', partner: 'Reason / contact', flow: ['draft', 'waiting', 'ready', 'done'] },
  adjustments: { type: 'ADJ', title: 'Adjustments', single: 'Adjustment', sub: 'Inventory counts reconciled against records.', partner: 'Contact', flow: ['done'] },
}
const VIEW_OPTS = [{ value: 'list', label: 'List', icon: 'list' }, { value: 'kanban', label: 'Kanban', icon: 'kanban' }]
const COLUMN_PAGE = 8

/** One kanban column. It asks the server for its own status, 8 cards at a time, so a board with thousands of
 *  documents never loads them all. */
function KanbanColumn({ status, filters, open }) {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const key = JSON.stringify({ ...filters, status })

  useEffect(() => { setItems([]); setPage(1) }, [key])
  useEffect(() => {
    let live = true
    setLoading(true)
    api('/operations', { params: { ...filters, status, page, page_size: COLUMN_PAGE } })
      .then((d) => { if (live) { setItems((old) => (page === 1 ? d.items : [...old, ...d.items])); setTotal(d.total) } })
      .catch(() => {})
      .finally(() => live && setLoading(false))
    return () => { live = false }
    // eslint-disable-next-line
  }, [key, page])

  if (status === 'cancelled' && !loading && total === 0) return null
  return (
    <div className="col">
      <div className="col-head"><Status value={status} /><span className="count">{total}</span></div>
      {items.map((o) => (
        <button key={o.id} className="kcard" onClick={() => open(o)}>
          <div className="ref mono">{o.reference}</div>
          <div className="muted small" style={{ marginTop: 2 }}>{o.contact || 'No contact'}</div>
          <div className="meta"><span className={o.late ? 'neg' : ''}>{fmtDate(o.schedule_date)}</span>{o.late && <span className="neg">Late</span>}</div>
        </button>
      ))}
      {items.length < total && <button className="col-more" disabled={loading} onClick={() => setPage(page + 1)}>{loading ? 'Loading…' : `Show ${Math.min(COLUMN_PAGE, total - items.length)} more`}</button>}
      {!items.length && !loading && <div className="col-empty">Nothing here</div>}
    </div>
  )
}

export function OperationList({ user }) {
  const { kind } = useParams()
  const cfg = KINDS[kind]
  const [view, setView] = useState('list')
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [wh, setWh] = useState('')
  const dq = useDebounced(q)
  const whs = useApi('/warehouses').data || []
  const filters = { type: cfg?.type, q: dq, warehouse_id: wh }
  const paged = usePaged('/operations', { ...filters, status }, { size: 25, deps: [kind], enabled: view === 'list' && !!cfg })
  const nav = useNavigate()
  const rows = paged.rows
  useEffect(() => { setQ(''); setStatus(''); setWh('') }, [kind])
  if (!cfg) return <div className="muted">Unknown page</div>
  const open = (o) => nav(`/operations/${kind}/${o.id}`)
  const statuses = cfg.flow.concat(['cancelled'])
  const filtered = q || status || wh
  const canCreate = canEditDocs(user, cfg.type)

  return (
    <>
      <PageHeader
        title={cfg.title}
        subtitle={cfg.sub}
        actions={<>
          <ExportButton path="/export/operations.csv" params={{ type: cfg.type, q: dq, status, warehouse_id: wh }} filename={`${kind}.csv`} />
          {kind === 'adjustments'
            ? <Link className="btn primary" to="/stock"><Icon name="sliders" size={16} />Update stock</Link>
            : canCreate && <Link className="btn primary" to={`/operations/${kind}/new`}><Icon name="plus" size={16} />New {cfg.single.toLowerCase()}</Link>}
        </>}
      />
      <div className="card">
        <div className="toolbar">
          <SearchInput value={q} onChange={setQ} />
          <select value={status} onChange={(e) => setStatus(e.target.value)} disabled={view === 'kanban'} title={view === 'kanban' ? 'The board already groups by status' : undefined}>
            <option value="">All statuses</option>
            {statuses.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
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
                <thead><tr><th>Reference</th><th>Contact</th><th>Schedule date</th><th>Responsible</th>{kind !== 'adjustments' && <th className="num">Total</th>}<th>Status</th></tr></thead>
                <tbody>
                  {paged.loading && !rows.length && <TableSkeleton cols={6} />}
                  {rows.map((o) => (
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
            {!paged.loading && !rows.length && (
              <Empty
                title={filtered ? 'No matches' : `No ${cfg.title.toLowerCase()} yet`}
                hint={filtered ? 'Try a different search or status filter.' : cfg.sub}
                action={!filtered && kind !== 'adjustments' && canCreate && <Link className="btn primary sm" to={`/operations/${kind}/new`}>Create the first one</Link>}
              />
            )}
            <Pager p={paged} />
          </>
        ) : (
          <div className="kanban">
            {statuses.map((s) => <KanbanColumn key={s} status={s} filters={filters} open={open} />)}
          </div>
        )}
      </div>
    </>
  )
}
