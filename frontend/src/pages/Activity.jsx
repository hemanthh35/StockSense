import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { usePaged, useDebounced } from '../hooks'
import { Empty, PageHeader, Pager, SearchInput, TableSkeleton, ago, fmtDateTime } from '../components/ui.jsx'

const ENTITIES = ['operation', 'product', 'contact', 'warehouse', 'location', 'tax', 'category', 'user', 'stock']
const ACTIONS = ['create', 'update', 'todo', 'check', 'pick', 'pack', 'validate', 'cancel', 'duplicate', 'archive', 'restore', 'delete', 'adjust', 'import', 'reorder', 'signup', 'password', 'role']
const DOC_PATH = { IN: 'receipts', OUT: 'deliveries', INT: 'transfers', ADJ: 'adjustments' }
const show = (v) => (v === null || v === undefined || v === '' ? '—' : String(v))

function target(a) {
  if (a.entity === 'operation' && a.entity_id && a.label) {
    const kind = DOC_PATH[a.label.split('/')[1]]
    if (kind) return <Link className="link mono" to={`/operations/${kind}/${a.entity_id}`}>{a.label}</Link>
  }
  return <span>{a.label || '—'}</span>
}

/** The audit log: every change, who made it, and what it was before and after. */
export default function Activity() {
  const [q, setQ] = useState('')
  const [entity, setEntity] = useState('')
  const [action, setAction] = useState('')
  const [open, setOpen] = useState(null)
  const dq = useDebounced(q)
  const paged = usePaged('/audit', { q: dq, entity, action }, { size: 25 })

  return (
    <>
      <PageHeader title="Activity log" subtitle="Who changed what, and when. Entries are written together with the change itself, so nothing is missed." />
      <div className="card">
        <div className="toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search person, reference or name" />
          <select value={entity} onChange={(e) => setEntity(e.target.value)}>
            <option value="">Everything</option>
            {ENTITIES.map((x) => <option key={x} value={x}>{x[0].toUpperCase() + x.slice(1)}</option>)}
          </select>
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">Any action</option>
            {ACTIONS.map((x) => <option key={x} value={x}>{x[0].toUpperCase() + x.slice(1)}</option>)}
          </select>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th style={{ width: 150 }}>When</th><th>Person</th><th>Action</th><th>What</th><th>Details</th></tr></thead>
            <tbody>
              {paged.loading && !paged.rows.length && <TableSkeleton cols={5} />}
              {paged.rows.map((a) => (
                <Fragment key={a.id}>
                  <tr className={a.changes ? 'expandable' : ''} onClick={() => a.changes && setOpen(open === a.id ? null : a.id)}>
                    <td title={fmtDateTime(a.at)} className="muted">{ago(a.at)}</td>
                    <td className="strong">{a.user || <span className="dim">system</span>}</td>
                    <td><span className="tag">{a.action}</span></td>
                    <td><span className="muted small">{a.entity}</span> {target(a)}</td>
                    <td className="muted">{a.detail || (a.changes ? `${Object.keys(a.changes).length} field${Object.keys(a.changes).length > 1 ? 's' : ''} changed` : '')}</td>
                  </tr>
                  {open === a.id && a.changes && (
                    <tr className="subrow"><td colSpan={5}>
                      <div className="changes">{Object.entries(a.changes).map(([k, [o, n]]) => <span key={k}><b>{k.replace(/_/g, ' ')}</b> {show(o)} → {show(n)}</span>)}</div>
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {!paged.loading && !paged.rows.length && <Empty icon="clock" title="No activity yet" hint="Changes will appear here as people work." />}
        <Pager p={paged} sizes={[25, 50, 100]} />
      </div>
    </>
  )
}
