import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Modal, num } from './ui.jsx'
import Scanner from './Scanner.jsx'

/** Scan (or type) a code: see the product's stock, and correct a count on the spot. */
export default function ScanLookup({ onClose }) {
  const [item, setItem] = useState(null)
  const [error, setError] = useState('')
  const [counts, setCounts] = useState({})
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const find = async (code) => {
    setError(''); setMsg(''); setCounts({})
    try { setItem(await api('/products/lookup', { params: { code } })) } catch (e) { setItem(null); setError(e.message) }
  }

  const apply = async (loc) => {
    const qty = counts[loc.location_id]
    if (qty === '' || qty == null || Number.isNaN(Number(qty))) return
    setBusy(true); setMsg('')
    try {
      await api('/stock/adjust', { method: 'POST', body: { product_id: item.product_id, location_id: loc.location_id, counted_qty: Number(qty) } })
      setMsg(`Counted ${num(Number(qty))} at ${loc.location}.`)
      await find(item.sku)
      setMsg(`Counted ${num(Number(qty))} at ${loc.location}.`)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <Modal title="Scan a product" subtitle="Look up stock, or fix a count." onClose={onClose} width={480}>
      <Scanner onDetect={find} />
      {error && <div className="banner" role="alert" style={{ marginTop: 14 }}>{error}</div>}
      {item && (
        <div className="card card-pad scan-result">
          <div className="scan-title">
            <div><b>{item.name}</b><small className="mono">{item.sku}{item.barcode ? ` · ${item.barcode}` : ''}</small></div>
            <div className="scan-qty"><b className={item.on_hand <= 0 ? 'neg' : ''}>{num(item.on_hand)}</b><small>on hand{item.incoming ? ` · ${num(item.incoming)} coming` : ''}</small></div>
          </div>
          {item.locations.length === 0 && <p className="muted small">No stock at any location yet.</p>}
          {item.locations.map((l) => (
            <div key={l.location_id} className="scan-loc">
              <span>{l.location}<small>{num(l.on_hand)} now</small></span>
              <input type="number" min="0" step="any" placeholder="Counted" value={counts[l.location_id] ?? ''} onChange={(e) => setCounts({ ...counts, [l.location_id]: e.target.value })} />
              <button className="btn sm" disabled={busy || counts[l.location_id] === undefined || counts[l.location_id] === ''} onClick={() => apply(l)}>Set</button>
            </div>
          ))}
          {msg && <p className="ai-ok">{msg}</p>}
          <Link className="link small" to={`/products?q=${encodeURIComponent(item.sku)}`} onClick={onClose}>Open in products</Link>
        </div>
      )}
    </Modal>
  )
}
