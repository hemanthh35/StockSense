import { useState } from 'react'
import { api } from '../api'

export const ArchivedTag = () => <span className="tag archived">Archived</span>

/** Archive / restore / delete controls for the footer of an edit dialog.
 *  Archiving keeps history; deleting only works for things that were never used (the server decides). */
export function LifecycleActions({ item, base, name, onDone, notify }) {
  const [confirm, setConfirm] = useState(false)
  const run = async (fn, msg) => {
    try { await fn(); notify(msg, 'ok'); onDone() } catch (e) { notify(e.message, 'error'); setConfirm(false) }
  }
  if (!item.id) return null
  return (
    <span className="lifecycle">
      {item.active === false
        ? <button type="button" className="btn" onClick={() => run(() => api(`${base}/${item.id}/restore`, { method: 'POST' }), `${name} restored`)}>Restore</button>
        : <button type="button" className="btn" onClick={() => run(() => api(`${base}/${item.id}/archive`, { method: 'POST' }), `${name} archived`)}>Archive</button>}
      {confirm ? (
        <>
          <button type="button" className="btn danger" onClick={() => run(() => api(`${base}/${item.id}`, { method: 'DELETE' }), `${name} deleted`)}>Yes, delete</button>
          <button type="button" className="btn ghost" onClick={() => setConfirm(false)}>Keep</button>
        </>
      ) : <button type="button" className="btn danger" onClick={() => setConfirm(true)}>Delete</button>}
    </span>
  )
}
