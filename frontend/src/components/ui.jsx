import { useEffect, useRef, useState } from 'react'
import { Icon } from './icons.jsx'

export const STATUS_LABEL = { draft: 'Draft', waiting: 'Waiting', ready: 'Ready', done: 'Done', cancelled: 'Cancelled' }
export const money = (n) => `₹${Number(n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
export const num = (n) => Number(n).toLocaleString('en-IN', { maximumFractionDigits: 3 })
export const fmtDate = (s) => (s ? new Date(s + 'T00:00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—')

export const Status = ({ value }) => <span className={`badge ${value}`}>{STATUS_LABEL[value] || value}</span>

export function PageHeader({ title, subtitle, actions, back }) {
  return (
    <div className="ph">
      <div>
        {back}
        <h1>{title}</h1>
        {subtitle && <p className="ph-sub">{subtitle}</p>}
      </div>
      {actions && <div className="ph-actions">{actions}</div>}
    </div>
  )
}

export function Stepper({ flow, current }) {
  const idx = flow.indexOf(current)
  return (
    <ol className="stepper">
      {flow.map((s, i) => {
        const state = current === 'cancelled' ? 'idle' : i < idx || current === 'done' ? 'past' : i === idx ? 'on' : 'idle'
        return (
          <li key={s} className={state}>
            <span className="dot">{state === 'past' ? <Icon name="check" size={12} /> : i + 1}</span>
            {STATUS_LABEL[s]}
          </li>
        )
      })}
      {current === 'cancelled' && <li className="on cancelled"><span className="dot"><Icon name="x" size={12} /></span>Cancelled</li>}
    </ol>
  )
}

export function Segmented({ value, onChange, options }) {
  return (
    <div className="segmented" role="tablist">
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={value === o.value} className={value === o.value ? 'on' : ''} onClick={() => onChange(o.value)} title={o.label}>
          {o.icon && <Icon name={o.icon} size={16} />}
          <span>{o.label}</span>
        </button>
      ))}
    </div>
  )
}

export function SearchInput({ value, onChange, placeholder = 'Search reference or contact' }) {
  return (
    <div className="searchbox">
      <Icon name="search" size={16} />
      <input value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      {value && <button className="clear" onClick={() => onChange('')} aria-label="Clear"><Icon name="x" size={14} /></button>}
    </div>
  )
}

/* ---------- pagination ---------- */
export function usePager(rows, initial = 10) {
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(initial)
  const total = rows.length
  const pages = Math.max(1, Math.ceil(total / size))
  useEffect(() => { setPage(1) }, [total, size])
  const cur = Math.min(page, pages)
  return { page: cur, setPage, size, setSize, total, pages, slice: rows.slice((cur - 1) * size, cur * size) }
}

function pageList(cur, pages) {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1)
  const out = [1]
  if (cur > 3) out.push('…')
  for (let p = Math.max(2, cur - 1); p <= Math.min(pages - 1, cur + 1); p++) out.push(p)
  if (cur < pages - 2) out.push('…r')
  out.push(pages)
  return out
}

export function Pager({ p, sizes = [10, 25, 50] }) {
  if (!p.total) return null
  const from = (p.page - 1) * p.size + 1
  const to = Math.min(p.page * p.size, p.total)
  return (
    <div className="pager">
      <div className="pager-info">
        Showing <b>{from}–{to}</b> of <b>{p.total}</b>
      </div>
      <div className="pager-ctrl">
        <label className="pager-size">
          Rows
          <select value={p.size} onChange={(e) => p.setSize(Number(e.target.value))}>
            {sizes.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <div className="pager-btns">
          <button className="pg" disabled={p.page === 1} onClick={() => p.setPage(p.page - 1)} aria-label="Previous page"><Icon name="left" size={16} /></button>
          {pageList(p.page, p.pages).map((n, i) =>
            typeof n === 'string' ? <span key={i} className="pg gap">…</span> : (
              <button key={i} className={`pg ${n === p.page ? 'on' : ''}`} onClick={() => p.setPage(n)}>{n}</button>
            )
          )}
          <button className="pg" disabled={p.page === p.pages} onClick={() => p.setPage(p.page + 1)} aria-label="Next page"><Icon name="right" size={16} /></button>
        </div>
      </div>
    </div>
  )
}

/* ---------- overlays ---------- */
export function Modal({ title, subtitle, onClose, children, footer, width = 620 }) {
  useEffect(() => {
    const h = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: width }} role="dialog" aria-modal="true">
        <div className="modal-head">
          <div>
            <h3>{title}</h3>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={18} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

export function Menu({ trigger, children, align = 'left' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef()
  useEffect(() => {
    const h = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false)
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  return (
    <div className="menu-root" ref={ref}>
      {trigger(open, () => setOpen((o) => !o))}
      {open && <div className={`menu ${align}`} onClick={() => setOpen(false)}>{children}</div>}
    </div>
  )
}

export function Empty({ icon = 'inbox', title, hint, action }) {
  return (
    <div className="empty">
      <span className="empty-icon"><Icon name={icon} size={22} /></span>
      <b>{title}</b>
      {hint && <p>{hint}</p>}
      {action}
    </div>
  )
}

export function TableSkeleton({ cols = 4, rows = 6 }) {
  return (
    <>
      {Array.from({ length: rows }, (_, r) => (
        <tr key={r} className="skeleton-row">
          {Array.from({ length: cols }, (_, c) => <td key={c}><span className="skeleton" style={{ width: `${45 + ((r * 13 + c * 29) % 45)}%` }} /></td>)}
        </tr>
      ))}
    </>
  )
}

export function Toast({ msg, kind = 'info', onClose }) {
  useEffect(() => {
    if (!msg) return
    const t = setTimeout(onClose, 5000)
    return () => clearTimeout(t)
  }, [msg])
  if (!msg) return null
  const icon = kind === 'error' ? 'alert' : kind === 'ok' ? 'check' : 'clock'
  return (
    <div className={`toast ${kind}`} role="status" onClick={onClose}>
      <Icon name={icon} size={18} />
      <span>{msg}</span>
    </div>
  )
}

export function useToast() {
  const [t, setT] = useState({ msg: '', kind: 'info' })
  return [t, (msg, kind = 'info') => setT({ msg, kind }), () => setT({ msg: '', kind: 'info' })]
}

export const Field = ({ label, hint, children, className = '' }) => (
  <label className={`field ${className}`}>
    <span className="field-label">{label}</span>
    {children}
    {hint && <span className="field-hint">{hint}</span>}
  </label>
)
