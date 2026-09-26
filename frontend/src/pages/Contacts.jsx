import { useState } from 'react'
import { useDebounced, usePaged } from '../hooks'
import { atLeast } from '../perm.js'
import { Icon } from '../components/icons.jsx'
import { ArchivedTag } from '../components/Lifecycle.jsx'
import PartyModal from '../components/PartyModal.jsx'
import { Empty, ExportButton, PageHeader, Pager, SearchInput, TableSkeleton, Toast, fmtDate, money, usePager, useToast } from '../components/ui.jsx'

const KIND_LABEL = { vendor: 'Supplier', customer: 'Customer', both: 'Supplier & customer' }

export default function Contacts({ user }) {
  const canManage = atLeast(user, 'manager')
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const dq = useDebounced(q)
  const paged = usePaged('/parties', { q: dq, kind, include_archived: showArchived ? 'true' : '' }, { size: 25 })
  const { reload } = paged
  const [editing, setEditing] = useState(null) // party object, or {} for a new one
  const [toast, notify, close] = useToast()
  const rows = paged.rows

  return (
    <>
      <PageHeader
        title="Contacts"
        subtitle="Your suppliers and customers, with GSTIN, address and document history."
        actions={<>
          <ExportButton path="/export/parties.csv" params={{ kind, include_archived: showArchived ? 'true' : '' }} filename="contacts.csv" onError={(m) => notify(m, 'error')} />
          {canManage && <button className="btn primary" onClick={() => setEditing({})}><Icon name="plus" size={16} />New contact</button>}
        </>}
      />
      <div className="card">
        <div className="toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search name, GSTIN or email" />
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Suppliers &amp; customers</option>
            <option value="vendor">Suppliers</option>
            <option value="customer">Customers</option>
          </select>
          <span className="grow" />
          <label className="check"><span className="switch"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /><i /></span>Show archived</label>
        </div>
        <div className="table-wrap">
          <table className="rows">
            <thead><tr><th>Name</th><th>Type</th><th>GSTIN</th><th className="num">Documents</th><th className="num">Total value</th><th>Last document</th></tr></thead>
            <tbody>
              {paged.loading && !rows.length && <TableSkeleton cols={6} />}
              {rows.map((p) => (
                <tr key={p.id} onClick={() => setEditing(p)} style={p.active ? undefined : { opacity: 0.6 }}>
                  <td className="strong">{p.name} {!p.active && <ArchivedTag />}<span className="sub">{[p.email, p.phone].filter(Boolean).join(' · ') || '—'}</span></td>
                  <td><span className="tag">{KIND_LABEL[p.kind]}</span></td>
                  <td>{p.gstin ? <><span className="mono">{p.gstin}</span><span className="sub">{p.state}</span></> : <span className="dim">—</span>}</td>
                  <td className="num">{p.documents}</td>
                  <td className="num">{p.total_value ? money(p.total_value) : <span className="dim">—</span>}</td>
                  <td className="muted">{p.last_document ? fmtDate(p.last_document) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!paged.loading && !rows.length && (
          <Empty icon="user" title={q || kind ? 'No matches' : 'No contacts yet'} hint={q || kind ? 'Try a different search.' : 'Add your suppliers and customers so documents can pick them from a list.'} />
        )}
        <Pager p={paged} />
      </div>

      {editing && (
        <PartyModal
          party={editing.id ? editing : null}
          readOnly={!canManage}
          onClose={() => setEditing(null)}
          onSaved={(saved) => { setEditing(null); reload(); if (saved) notify('Contact saved', 'ok') }}
          notify={notify}
        />
      )}
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}
