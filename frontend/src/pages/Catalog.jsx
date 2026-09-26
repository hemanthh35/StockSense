import { Fragment, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useApi, useDebounced } from '../hooks'
import { Search, Toast, useToast, money, num } from '../components/ui.jsx'

const emptyP = { name: '', sku: '', category_id: '', uom: 'Unit', unit_cost: 0, reorder_min: 0, reorder_qty: 0, initial_stock: 0, initial_location_id: '' }

export function Products() {
  const [params] = useSearchParams()
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('')
  const dq = useDebounced(q)
  const { data, reload } = useApi('/products', { q: dq, category_id: cat })
  const cats = useApi('/categories')
  const locs = useApi('/locations', { internal_only: true }).data || []
  const [form, setForm] = useState(params.get('new') ? { ...emptyP } : null)
  const [newCat, setNewCat] = useState('')
  const [toast, notify, close] = useToast()

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const save = async (e) => {
    e.preventDefault()
    try {
      const body = {
        ...form,
        category_id: form.category_id ? Number(form.category_id) : null,
        initial_location_id: form.initial_location_id ? Number(form.initial_location_id) : null,
        unit_cost: Number(form.unit_cost), reorder_min: Number(form.reorder_min),
        reorder_qty: Number(form.reorder_qty), initial_stock: Number(form.initial_stock),
      }
      if (form.id) await api(`/products/${form.id}`, { method: 'PUT', body })
      else await api('/products', { method: 'POST', body })
      setForm(null); reload(); notify('Product saved', 'ok')
    } catch (x) { notify(x.message, 'error') }
  }
  const addCat = async () => {
    if (!newCat.trim()) return
    const c = await api('/categories', { method: 'POST', body: { name: newCat } })
    await cats.reload(); setForm({ ...form, category_id: c.id }); setNewCat('')
  }

  return (
    <>
      <div className="head">
        <h1>Products</h1>
        <div className="filters">
          <button className="btn primary" onClick={() => setForm({ ...emptyP })}>New Product</button>
          <Search value={q} onChange={setQ} placeholder="Search name or SKU…" />
          <select value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="">All categories</option>
            {(cats.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
      </div>

      {form && (
        <form className="card form2" onSubmit={save}>
          <label>Name<input value={form.name} onChange={set('name')} required /></label>
          <label>SKU / Code<input value={form.sku} onChange={set('sku')} required /></label>
          <label>Category
            <select value={form.category_id} onChange={set('category_id')}>
              <option value="">None</option>
              {(cats.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label>New category
            <span className="inline"><input value={newCat} onChange={(e) => setNewCat(e.target.value)} /><button type="button" className="btn" onClick={addCat}>Add</button></span>
          </label>
          <label>Unit of Measure<input value={form.uom} onChange={set('uom')} /></label>
          <label>Unit cost (Rs)<input type="number" min="0" step="any" value={form.unit_cost} onChange={set('unit_cost')} /></label>
          <label>Reorder when stock ≤<input type="number" min="0" step="any" value={form.reorder_min} onChange={set('reorder_min')} /></label>
          <label>Reorder quantity<input type="number" min="0" step="any" value={form.reorder_qty} onChange={set('reorder_qty')} /></label>
          {!form.id && (
            <>
              <label>Initial stock (optional)<input type="number" min="0" step="any" value={form.initial_stock} onChange={set('initial_stock')} /></label>
              <label>Initial location
                <select value={form.initial_location_id} onChange={set('initial_location_id')}>
                  <option value="">Default</option>
                  {locs.map((l) => <option key={l.id} value={l.id}>{l.full_name}</option>)}
                </select>
              </label>
            </>
          )}
          <div className="rowgap full">
            <button className="btn primary">Save</button>
            <button type="button" className="btn" onClick={() => setForm(null)}>Discard</button>
          </div>
        </form>
      )}

      <div className="card">
        <table className="clickable">
          <thead><tr><th>SKU</th><th>Name</th><th>Category</th><th>UoM</th><th>Unit cost</th><th>On hand</th><th>Reorder at</th></tr></thead>
          <tbody>
            {(data || []).map((p) => (
              <tr key={p.id} onClick={() => setForm({ ...p, category_id: p.category_id || '' })}>
                <td>{p.sku}</td><td>{p.name}</td><td>{p.category || '—'}</td><td>{p.uom}</td>
                <td>{money(p.unit_cost)}</td>
                <td className={p.on_hand <= 0 ? 'red' : p.low_stock ? 'amber' : ''}>{num(p.on_hand)}{p.low_stock && ' ⚠'}</td>
                <td>{num(p.reorder_min)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}

export function Stock() {
  const [q, setQ] = useState('')
  const [wh, setWh] = useState('')
  const dq = useDebounced(q)
  const { data, reload } = useApi('/stock', { q: dq, warehouse_id: wh })
  const whs = useApi('/warehouses').data || []
  const [edit, setEdit] = useState(null) // {product_id, location_id, counted_qty}
  const [toast, notify, close] = useToast()

  const submit = async () => {
    try {
      const r = await api('/stock/adjust', { method: 'POST', body: { ...edit, counted_qty: Number(edit.counted_qty) } })
      notify(`Stock updated (${r.reference}): ${num(r.before)} → ${num(r.after)}`, 'ok')
      setEdit(null); reload()
    } catch (x) { notify(x.message, 'error') }
  }

  return (
    <>
      <div className="head">
        <h1>Stock</h1>
        <div className="filters">
          <Search value={q} onChange={setQ} placeholder="Search product or SKU…" />
          <select value={wh} onChange={(e) => setWh(e.target.value)}>
            <option value="">All warehouses</option>
            {whs.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </div>
      </div>
      <p className="muted">This page contains the warehouse details & location. Enter the counted quantity to update stock — the difference is logged in Move History.</p>
      <div className="card">
        <table>
          <thead><tr><th>Product</th><th>Per unit cost</th><th>On hand</th><th>Free to Use</th><th /></tr></thead>
          <tbody>
            {(data || []).map((r) => (
              <Fragment key={r.product_id}>
                <tr>
                  <td>{r.name} <span className="muted small">{r.sku}</span></td>
                  <td>{money(r.unit_cost)}</td>
                  <td className={r.on_hand <= 0 ? 'red' : r.low_stock ? 'amber' : ''}>{num(r.on_hand)}</td>
                  <td>{num(r.free_to_use)}</td>
                  <td />
                </tr>
                {r.locations.map((l) => (
                  <tr key={`${r.product_id}-${l.location_id}`} className="sub">
                    <td>↳ {l.location}</td><td />
                    <td>{num(l.on_hand)}</td><td>{num(l.free_to_use)}</td>
                    <td>
                      {edit?.product_id === r.product_id && edit?.location_id === l.location_id ? (
                        <span className="inline">
                          <input type="number" min="0" step="any" value={edit.counted_qty} autoFocus onChange={(e) => setEdit({ ...edit, counted_qty: e.target.value })} />
                          <button className="btn primary" onClick={submit}>Apply</button>
                          <button className="btn" onClick={() => setEdit(null)}>✕</button>
                        </span>
                      ) : (
                        <a onClick={() => setEdit({ product_id: r.product_id, location_id: l.location_id, counted_qty: l.on_hand })}>Update</a>
                      )}
                    </td>
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}
