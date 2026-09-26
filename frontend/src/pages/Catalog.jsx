import { Fragment, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useApi, useDebounced } from '../hooks'
import { Icon } from '../components/icons.jsx'
import CategoryManager from '../components/CategoryManager.jsx'
import { Empty, Field, Modal, PageHeader, Pager, SearchInput, TableSkeleton, Toast, money, num, usePager, useToast } from '../components/ui.jsx'

const emptyP = { name: '', sku: '', category_id: '', uom: 'Unit', unit_cost: 0, hsn_code: '', tax_id: '', reorder_min: 0, reorder_qty: 0, initial_stock: 0, initial_location_id: '' }

export function Products() {
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('')
  const dq = useDebounced(q)
  const { data, reload } = useApi('/products', { q: dq, category_id: cat })
  const cats = useApi('/categories')
  const locs = useApi('/locations', { internal_only: true }).data || []
  const taxes = useApi('/taxes').data || []
  const [form, setForm] = useState(params.get('new') ? { ...emptyP } : null)
  const [newCat, setNewCat] = useState('')
  const [manageCats, setManageCats] = useState(false)
  const [toast, notify, close] = useToast()
  const rows = data || []
  const pager = usePager(rows)

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const catDefault = (cats.data || []).find((c) => c.id === Number(form?.category_id))?.default_tax_id
  const autoTax = taxes.find((t) => t.id === catDefault) || taxes.find((t) => t.is_default)
  const closeForm = () => { setForm(null); if (params.get('new')) setParams({}) }
  const save = async (e) => {
    e.preventDefault()
    try {
      const body = {
        ...form,
        category_id: form.category_id ? Number(form.category_id) : null,
        tax_id: form.tax_id === '' ? null : Number(form.tax_id),
        hsn_code: form.hsn_code || null,
        initial_location_id: form.initial_location_id ? Number(form.initial_location_id) : null,
        unit_cost: Number(form.unit_cost), reorder_min: Number(form.reorder_min),
        reorder_qty: Number(form.reorder_qty), initial_stock: Number(form.initial_stock),
      }
      if (form.id) await api(`/products/${form.id}`, { method: 'PUT', body })
      else await api('/products', { method: 'POST', body })
      closeForm(); reload(); notify('Product saved', 'ok')
    } catch (x) { notify(x.message, 'error') }
  }
  const addCat = async () => {
    if (!newCat.trim()) return
    const c = await api('/categories', { method: 'POST', body: { name: newCat } })
    await cats.reload(); setForm({ ...form, category_id: c.id }); setNewCat('')
  }

  return (
    <>
      <PageHeader
        title="Products"
        subtitle="Your catalogue — SKUs, categories, costs and reorder rules."
        actions={<>
          <button className="btn" onClick={() => setManageCats(true)}><Icon name="tag" size={16} />Categories</button>
          <button className="btn primary" onClick={() => setForm({ ...emptyP })}><Icon name="plus" size={16} />New product</button>
        </>}
      />
      <div className="card">
        <div className="toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search name or SKU" />
          <select value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="">All categories</option>
            {(cats.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div className="table-wrap">
          <table className="rows">
            <thead><tr><th>Product</th><th>Category</th><th>UoM</th><th>Tax</th><th className="num">Unit cost</th><th className="num">On hand</th><th className="num">Reorder at</th></tr></thead>
            <tbody>
              {!data && <TableSkeleton cols={7} />}
              {pager.slice.map((p) => (
                <tr key={p.id} onClick={() => setForm({ ...p, category_id: p.category_id || '', tax_id: p.tax_id || 0, hsn_code: p.hsn_code || '' })}>
                  <td className="strong">{p.name}<span className="sub mono">{p.sku}</span></td>
                  <td>{p.category ? <span className="tag">{p.category}</span> : <span className="dim">—</span>}</td>
                  <td className="muted">{p.uom}</td>
                  <td>{p.tax ? <span className="tax-tag">{p.tax.name}</span> : <span className="tax-tag none">No tax</span>}</td>
                  <td className="num">{money(p.unit_cost)}</td>
                  <td className={`num ${p.on_hand <= 0 ? 'neg' : p.low_stock ? 'warn' : ''}`}>{num(p.on_hand)}</td>
                  <td className="num muted">{num(p.reorder_min)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && !rows.length && <Empty icon="box" title={q || cat ? 'No matches' : 'No products yet'} hint={q || cat ? 'Try a different search.' : 'Add your first product to start tracking stock.'} />}
        <Pager p={pager} />
      </div>

      {manageCats && (
        <CategoryManager
          categories={cats.data || []}
          onChanged={async () => { await cats.reload(); reload() }}
          onClose={() => { setManageCats(false); if (cat && !(cats.data || []).some((c) => String(c.id) === String(cat))) setCat('') }}
          notify={notify}
        />
      )}

      {form && (
        <Modal
          title={form.id ? 'Edit product' : 'New product'}
          subtitle={form.id ? form.sku : 'Add an item to the catalogue.'}
          onClose={closeForm}
          footer={<><button className="btn" onClick={closeForm}>Discard</button><button className="btn primary" form="product-form">Save product</button></>}
        >
          <form id="product-form" className="form-grid" onSubmit={save}>
            <Field label="Name"><input value={form.name} onChange={set('name')} required autoFocus /></Field>
            <Field label="SKU / code"><input value={form.sku} onChange={set('sku')} required className="mono" /></Field>
            <Field label="Category">
              <select value={form.category_id} onChange={set('category_id')}>
                <option value="">None</option>
                {(cats.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
            <Field label="Add a category">
              <div className="inline"><input value={newCat} onChange={(e) => setNewCat(e.target.value)} placeholder="New category name" /><button type="button" className="btn" onClick={addCat}>Add</button></div>
            </Field>
            <Field label="Unit of measure"><input value={form.uom} onChange={set('uom')} /></Field>
            <Field label="Unit price (₹)" hint="Pre-fills every order line"><div className="prefix"><span>₹</span><input type="number" min="0" step="any" value={form.unit_cost} onChange={set('unit_cost')} /></div></Field>
            <Field label="Tax" hint="Applied automatically on receipts and deliveries">
              <select value={form.tax_id} onChange={set('tax_id')}>
                <option value="">Automatic — {autoTax ? autoTax.name : 'no tax'}</option>
                <option value={0}>No tax</option>
                {taxes.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </Field>
            <Field label="HSN / SAC code" hint="Optional"><input value={form.hsn_code} onChange={set('hsn_code')} className="mono" inputMode="numeric" /></Field>
            <Field label="Reorder when stock ≤"><input type="number" min="0" step="any" value={form.reorder_min} onChange={set('reorder_min')} /></Field>
            <Field label="Reorder quantity"><input type="number" min="0" step="any" value={form.reorder_qty} onChange={set('reorder_qty')} /></Field>
            {!form.id && (
              <>
                <Field label="Initial stock" hint="Optional — logged as an adjustment"><input type="number" min="0" step="any" value={form.initial_stock} onChange={set('initial_stock')} /></Field>
                <Field label="Initial location">
                  <select value={form.initial_location_id} onChange={set('initial_location_id')}>
                    <option value="">Default</option>
                    {locs.map((l) => <option key={l.id} value={l.id}>{l.full_name}</option>)}
                  </select>
                </Field>
              </>
            )}
          </form>
        </Modal>
      )}
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
  const [edit, setEdit] = useState(null)
  const [toast, notify, close] = useToast()
  const rows = data || []
  const pager = usePager(rows)

  const diff = edit ? Number(edit.counted_qty || 0) - edit.current : 0
  const submit = async (e) => {
    e.preventDefault()
    try {
      const r = await api('/stock/adjust', { method: 'POST', body: { product_id: edit.product_id, location_id: edit.location_id, counted_qty: Number(edit.counted_qty) } })
      notify(diff === 0 ? 'Count matches — no change' : `Stock updated (${r.reference}): ${num(r.before)} → ${num(r.after)}`, 'ok')
      setEdit(null); reload()
    } catch (x) { notify(x.message, 'error') }
  }

  return (
    <>
      <PageHeader title="Stock" subtitle="Available inventory by product and location. Enter a physical count to correct a quantity — the difference is logged in Move History." />
      <div className="card">
        <div className="toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search product or SKU" />
          <select value={wh} onChange={(e) => setWh(e.target.value)}>
            <option value="">All warehouses</option>
            {whs.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Product</th><th className="num">Per unit cost</th><th className="num">On hand</th><th className="num">Free to use</th><th style={{ width: 110 }} /></tr></thead>
            <tbody>
              {!data && <TableSkeleton cols={5} />}
              {pager.slice.map((r) => (
                <Fragment key={r.product_id}>
                  <tr>
                    <td className="strong">{r.name}<span className="sub mono">{r.sku}</span></td>
                    <td className="num">{money(r.unit_cost)}</td>
                    <td className={`num strong ${r.on_hand <= 0 ? 'neg' : r.low_stock ? 'warn' : ''}`}>{num(r.on_hand)}</td>
                    <td className="num">{num(r.free_to_use)}</td>
                    <td />
                  </tr>
                  {r.locations.map((l) => (
                    <tr key={l.location_id} className="subrow">
                      <td><span className="mono">{l.location}</span></td><td />
                      <td className="num">{num(l.on_hand)}</td><td className="num">{num(l.free_to_use)}</td>
                      <td className="num"><button className="btn sm" onClick={() => setEdit({ product_id: r.product_id, name: r.name, location_id: l.location_id, location: l.location, current: l.on_hand, counted_qty: l.on_hand })}>Update</button></td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {data && !rows.length && <Empty icon="box" title="No stock to show" hint="Add products or change the filters." />}
        <Pager p={pager} sizes={[5, 10, 25]} />
      </div>

      {edit && (
        <Modal
          width={440}
          title="Update stock"
          subtitle={`${edit.name} · ${edit.location}`}
          onClose={() => setEdit(null)}
          footer={<><button className="btn" onClick={() => setEdit(null)}>Cancel</button><button className="btn primary" form="adjust-form">Apply count</button></>}
        >
          <form id="adjust-form" className="stack" onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Field label="Currently on hand"><input disabled value={num(edit.current)} /></Field>
            <Field label="Counted quantity"><input type="number" min="0" step="any" autoFocus value={edit.counted_qty} onChange={(e) => setEdit({ ...edit, counted_qty: e.target.value })} /></Field>
            <div className="muted">Difference <span className={`diff ${diff > 0 ? 'pos' : diff < 0 ? 'neg' : ''}`}>{diff > 0 ? '+' : ''}{num(diff)}</span></div>
          </form>
        </Modal>
      )}
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}
