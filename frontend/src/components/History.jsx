import { useEffect, useState } from 'react'
import { api } from '../api'
import { ago, fmtDateTime } from './ui.jsx'
import { Icon } from './icons.jsx'

const VERB = {
  create: 'created', update: 'edited', todo: 'marked To do', check: 'checked availability', pick: 'picked', pack: 'packed',
  validate: 'validated', cancel: 'cancelled', duplicate: 'duplicated', archive: 'archived', restore: 'restored', delete: 'deleted',
}

const show = (v) => (v === null || v === undefined || v === '' ? '—' : String(v))

/** Who did what to this record, newest first. `refreshKey` reloads it after an action. */
export default function History({ path, refreshKey }) {
  const [rows, setRows] = useState(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let live = true
    api(path).then((d) => live && setRows(d)).catch(() => live && setRows([]))
    return () => { live = false }
  }, [path, refreshKey])

  if (!rows || !rows.length) return null
  return (
    <div className="card no-print">
      <button className="card-head history-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <h3>Activity <span className="muted small">· {rows.length}</span></h3>
        <Icon name="down" size={16} className={open ? 'flip' : ''} />
      </button>
      {open && (
        <ul className="history">
          {rows.map((a) => (
            <li key={a.id}>
              <span className="who">{a.user || 'System'}</span>
              <span>{VERB[a.action] || a.action}{a.detail ? <> — <span className="muted">{a.detail}</span></> : null}</span>
              <time title={fmtDateTime(a.at)}>{ago(a.at)}</time>
              {a.changes && (
                <span className="changes">
                  {Object.entries(a.changes).map(([k, [o, n]]) => <span key={k}><b>{k.replace(/_/g, ' ')}</b> {show(o)} → {show(n)}</span>)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
