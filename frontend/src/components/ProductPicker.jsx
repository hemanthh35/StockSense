import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useDebounced } from '../hooks'

/**
 * Search-as-you-type product selector. It asks the server for a handful of matches instead of loading the
 * whole catalogue, so it stays fast with tens of thousands of products.
 */
export default function ProductPicker({ label, onPick, disabled, placeholder = 'Search product or SKU' }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [cursor, setCursor] = useState(0)
  const dq = useDebounced(q, 200)
  const box = useRef()

  useEffect(() => {
    if (!open) return
    let live = true
    setLoading(true)
    api('/products', { params: { q: dq, page: 1, page_size: 12 } })
      .then((d) => { if (live) { setItems(d.items); setCursor(0) } })
      .catch(() => { if (live) setItems([]) })
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [dq, open])

  useEffect(() => {
    const h = (e) => box.current && !box.current.contains(e.target) && setOpen(false)
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const choose = (p) => { onPick(p); setOpen(false); setQ('') }
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, items.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)) }
    else if (e.key === 'Enter' && open && items[cursor]) { e.preventDefault(); choose(items[cursor]) }
    else if (e.key === 'Escape') setOpen(false)
  }

  return (
    <div className="picker" ref={box}>
      <input
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        disabled={disabled}
        value={open ? q : label || ''}
        placeholder={open ? 'Type to search…' : placeholder}
        onFocus={() => setOpen(true)}
        onChange={(e) => { setQ(e.target.value); setOpen(true) }}
        onKeyDown={onKey}
      />
      {open && (
        <ul className="picker-list" role="listbox">
          {loading && !items.length && <li className="picker-note">Searching…</li>}
          {!loading && !items.length && <li className="picker-note">No products match “{q}”.</li>}
          {items.map((p, i) => (
            <li key={p.id} role="option" aria-selected={i === cursor} className={i === cursor ? 'on' : ''} onMouseEnter={() => setCursor(i)} onMouseDown={(e) => { e.preventDefault(); choose(p) }}>
              <span><b>{p.name}</b><small className="mono">{p.sku}</small></span>
              <span className={`picker-stock ${p.on_hand <= 0 ? 'neg' : ''}`}>{p.on_hand} on hand</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
