import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useDebounced } from '../hooks'
import { atLeast } from '../perm.js'
import { Icon } from './icons.jsx'

const DOC_PATH = { IN: 'receipts', OUT: 'deliveries', INT: 'transfers', ADJ: 'adjustments' }

const PAGES = [
  { label: 'Dashboard', to: '/', icon: 'dashboard' },
  { label: 'Receipts', to: '/operations/receipts', icon: 'receive' },
  { label: 'Deliveries', to: '/operations/deliveries', icon: 'deliver' },
  { label: 'Internal transfers', to: '/operations/transfers', icon: 'swap' },
  { label: 'Adjustments', to: '/operations/adjustments', icon: 'sliders' },
  { label: 'Products', to: '/products', icon: 'box' },
  { label: 'Stock', to: '/stock', icon: 'box' },
  { label: 'Contacts', to: '/contacts', icon: 'user' },
  { label: 'Move history', to: '/moves', icon: 'swap' },
  { label: 'My profile', to: '/profile', icon: 'user' },
  { label: 'Activity log', to: '/activity', icon: 'clock', role: 'manager' },
  { label: 'Warehouses', to: '/settings/warehouses', icon: 'warehouse', role: 'admin' },
  { label: 'Locations', to: '/settings/locations', icon: 'pin', role: 'admin' },
  { label: 'Taxes', to: '/settings/taxes', icon: 'tag', role: 'admin' },
  { label: 'Users', to: '/settings/users', icon: 'user', role: 'admin' },
]
const ACTIONS = [
  { label: 'New receipt', to: '/operations/receipts/new', icon: 'plus', role: 'manager' },
  { label: 'New delivery', to: '/operations/deliveries/new', icon: 'plus', role: 'manager' },
  { label: 'New transfer', to: '/operations/transfers/new', icon: 'plus' },
  { label: 'New product', to: '/products?new=1', icon: 'plus', role: 'manager' },
]

/** Ctrl/Cmd+K: jump to any page, start a new document, or find a product, document or contact. */
export default function CommandPalette({ user, open, onClose }) {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [found, setFound] = useState([])
  const [cursor, setCursor] = useState(0)
  const dq = useDebounced(q, 200)
  const input = useRef()

  useEffect(() => { if (open) { setQ(''); setFound([]); setCursor(0); setTimeout(() => input.current?.focus(), 30) } }, [open])

  useEffect(() => {
    if (!open || dq.trim().length < 2) { setFound([]); return }
    let live = true
    const p = { q: dq, page: 1, page_size: 4 }
    Promise.all([
      api('/products', { params: p }).catch(() => ({ items: [] })),
      api('/operations', { params: p }).catch(() => ({ items: [] })),
      api('/parties', { params: p }).catch(() => ({ items: [] })),
    ]).then(([pr, op, pa]) => {
      if (!live) return
      setFound([
        ...pr.items.map((x) => ({ label: x.name, hint: x.sku, group: 'Product', icon: 'box', to: `/products?q=${encodeURIComponent(x.sku)}` })),
        ...op.items.map((x) => ({ label: x.reference, hint: x.contact || x.type_label, group: 'Document', icon: 'receive', to: `/operations/${DOC_PATH[x.type]}/${x.id}` })),
        ...pa.items.map((x) => ({ label: x.name, hint: x.gstin || '', group: 'Contact', icon: 'user', to: '/contacts' })),
      ])
    })
    return () => { live = false }
  }, [dq, open])

  const items = useMemo(() => {
    const allowed = (x) => !x.role || atLeast(user, x.role)
    const needle = q.trim().toLowerCase()
    const match = (x) => !needle || x.label.toLowerCase().includes(needle)
    return [
      ...ACTIONS.filter(allowed).filter(match).map((x) => ({ ...x, group: 'Create' })),
      ...found,
      ...PAGES.filter(allowed).filter(match).map((x) => ({ ...x, group: 'Go to' })),
    ].slice(0, 14)
  }, [q, found, user])

  if (!open) return null
  const go = (x) => { onClose(); nav(x.to) }
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, items.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)) }
    else if (e.key === 'Enter' && items[cursor]) { e.preventDefault(); go(items[cursor]) }
    else if (e.key === 'Escape') onClose()
  }

  return (
    <div className="overlay palette-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="palette" role="dialog" aria-label="Command palette">
        <div className="palette-input">
          <Icon name="search" size={18} />
          <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setCursor(0) }} onKeyDown={onKey} placeholder="Search products, documents, contacts — or jump to a page" />
          <kbd>Esc</kbd>
        </div>
        <ul className="palette-list">
          {items.map((x, i) => (
            <li key={`${x.group}-${x.to}-${x.label}`} className={i === cursor ? 'on' : ''} onMouseEnter={() => setCursor(i)} onMouseDown={(e) => { e.preventDefault(); go(x) }}>
              <span className="pl-icon"><Icon name={x.icon} size={16} /></span>
              <span className="pl-label">{x.label}{x.hint && <small className="mono">{x.hint}</small>}</span>
              <span className="pl-group">{x.group}</span>
            </li>
          ))}
          {!items.length && <li className="palette-empty">Nothing matches “{q}”.</li>}
        </ul>
        <div className="palette-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>Ctrl</kbd>+<kbd>K</kbd> anywhere</span></div>
      </div>
    </div>
  )
}
