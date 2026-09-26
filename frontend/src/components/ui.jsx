import { useEffect, useState } from 'react'

export const STATUS_LABEL = { draft: 'Draft', waiting: 'Waiting', ready: 'Ready', done: 'Done', cancelled: 'Cancelled' }

export const Status = ({ value }) => <span className={`badge ${value}`}>{STATUS_LABEL[value] || value}</span>

export function Steps({ flow, current }) {
  const idx = flow.indexOf(current)
  return (
    <div className="steps">
      {flow.map((s, i) => (
        <span key={s} className={`step ${s === current ? 'on' : ''} ${i < idx ? 'past' : ''}`}>{STATUS_LABEL[s]}</span>
      ))}
      {current === 'cancelled' && <span className="step on cancelled">Cancelled</span>}
    </div>
  )
}

export function ViewToggle({ view, setView }) {
  return (
    <div className="toggle">
      <button className={view === 'list' ? 'on' : ''} onClick={() => setView('list')}>☰ List</button>
      <button className={view === 'kanban' ? 'on' : ''} onClick={() => setView('kanban')}>▦ Kanban</button>
    </div>
  )
}

export function Search({ value, onChange, placeholder = 'Search reference or contact…' }) {
  return <input className="search" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
}

export function Toast({ msg, kind = 'info', onClose }) {
  useEffect(() => {
    if (!msg) return
    const t = setTimeout(onClose, 5000)
    return () => clearTimeout(t)
  }, [msg])
  if (!msg) return null
  return <div className={`toast ${kind}`} onClick={onClose}>{msg}</div>
}

export function useToast() {
  const [t, setT] = useState({ msg: '', kind: 'info' })
  return [t, (msg, kind = 'info') => setT({ msg, kind }), () => setT({ msg: '', kind: 'info' })]
}

export const money = (n) => `${Number(n).toLocaleString('en-IN')} Rs`
export const num = (n) => Number(n).toLocaleString('en-IN', { maximumFractionDigits: 3 })
