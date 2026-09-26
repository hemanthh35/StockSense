import { useState } from 'react'
import { api } from '../api'
import { usePaged } from '../hooks'
import { Icon } from '../components/icons.jsx'
import { Empty, PageHeader, Pager, TableSkeleton, Toast, fmtDate, useToast } from '../components/ui.jsx'
import { ROLE_LABEL } from '../perm.js'

const ROLE_HELP = {
  staff: 'Sees everything. Runs internal transfers, picks, packs and validates, and counts stock.',
  manager: 'Everything staff can do, plus creating and editing receipts, deliveries, products and contacts, importing and reordering.',
  admin: 'Everything, plus warehouses, locations, taxes, users and the activity log.',
}

export default function Users({ me }) {
  const paged = usePaged('/users', {}, { size: 25 })
  const [toast, notify, close] = useToast()
  const [busy, setBusy] = useState(null)

  const update = async (u, patch) => {
    setBusy(u.id)
    try {
      await api(`/users/${u.id}`, { method: 'PUT', body: { role: u.role, active: u.active, ...patch } })
      notify(`${u.login_id} updated`, 'ok')
      paged.reload()
    } catch (e) { notify(e.message, 'error') }
    setBusy(null)
  }

  return (
    <>
      <PageHeader title="Users" subtitle="Choose what each person can do. New sign-ups start as warehouse staff; the first person to sign up is the administrator." />
      <div className="role-cards">
        {Object.entries(ROLE_LABEL).map(([k, label]) => (
          <div key={k} className="card role-card"><b>{label}</b><p className="muted small">{ROLE_HELP[k]}</p></div>
        ))}
      </div>
      <div className="card">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Login ID</th><th>Email</th><th style={{ width: 200 }}>Role</th><th>Joined</th><th style={{ width: 90 }}>Active</th></tr></thead>
            <tbody>
              {paged.loading && !paged.rows.length && <TableSkeleton cols={5} rows={4} />}
              {paged.rows.map((u) => (
                <tr key={u.id} style={u.active ? undefined : { opacity: 0.55 }}>
                  <td className="strong">{u.login_id} {u.id === me.id && <span className="tag">You</span>}</td>
                  <td className="muted">{u.email}</td>
                  <td>
                    <select value={u.role} disabled={busy === u.id} onChange={(e) => update(u, { role: e.target.value })} aria-label={`Role for ${u.login_id}`}>
                      {Object.entries(ROLE_LABEL).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                    </select>
                  </td>
                  <td className="muted">{fmtDate(u.created_at?.slice(0, 10))}</td>
                  <td><label className="switch" aria-label={`${u.login_id} active`}><input type="checkbox" checked={u.active} disabled={busy === u.id} onChange={(e) => update(u, { active: e.target.checked })} /><i /></label></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!paged.loading && !paged.rows.length && <Empty icon="user" title="No users" />}
        <Pager p={paged} />
      </div>
      <p className="muted small" style={{ display: 'flex', gap: 8, alignItems: 'center' }}><Icon name="alert" size={14} />The last active administrator can't be demoted or deactivated.</p>
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}
