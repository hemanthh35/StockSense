import { useState } from 'react'
import { api } from '../api'
import { Icon } from './icons.jsx'
import { Modal } from './ui.jsx'

/** Add, rename and delete product categories. A category still in use can't be deleted. */
export default function CategoryManager({ categories, onChanged, onClose, notify }) {
  const [name, setName] = useState('')
  const [edits, setEdits] = useState({})
  const [confirm, setConfirm] = useState(null)

  const run = async (fn, ok) => {
    try { await fn(); await onChanged(); if (ok) notify(ok, 'ok') } catch (e) { notify(e.message, 'error') }
  }
  const add = (e) => {
    e.preventDefault()
    if (!name.trim()) return
    run(() => api('/categories', { method: 'POST', body: { name } }), 'Category added').then(() => setName(''))
  }
  const rename = (c) => {
    const next = (edits[c.id] ?? c.name).trim()
    if (!next || next === c.name) { setEdits((s) => ({ ...s, [c.id]: undefined })); return }
    run(() => api(`/categories/${c.id}`, { method: 'PUT', body: { name: next } }), 'Category renamed').then(() => setEdits((s) => ({ ...s, [c.id]: undefined })))
  }
  const remove = (c) => run(() => api(`/categories/${c.id}`, { method: 'DELETE' }), 'Category deleted').then(() => setConfirm(null))

  return (
    <Modal
      width={520}
      title="Categories"
      subtitle="Group products for filtering and default taxes."
      onClose={onClose}
      footer={<button className="btn primary" onClick={onClose}>Done</button>}
    >
      <form className="inline" onSubmit={add} style={{ marginBottom: 16 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New category name" />
        <button className="btn primary" disabled={!name.trim()}><Icon name="plus" size={16} />Add</button>
      </form>
      <ul className="catlist">
        {categories.map((c) => (
          <li key={c.id}>
            <input
              value={edits[c.id] ?? c.name}
              onChange={(e) => setEdits({ ...edits, [c.id]: e.target.value })}
              onBlur={() => rename(c)}
              onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') setEdits({ ...edits, [c.id]: undefined }) }}
              aria-label={`Rename ${c.name}`}
            />
            <span className="muted small">{c.products} product{c.products === 1 ? '' : 's'}</span>
            {confirm === c.id ? (
              <span className="inline">
                <button className="btn danger sm" onClick={() => remove(c)}>Delete</button>
                <button className="btn sm" onClick={() => setConfirm(null)}>Keep</button>
              </span>
            ) : (
              <button
                className="icon-btn line-x"
                disabled={c.products > 0}
                title={c.products > 0 ? 'Move its products to another category first' : 'Delete category'}
                aria-label={`Delete ${c.name}`}
                onClick={() => setConfirm(c.id)}
              ><Icon name="x" size={16} /></button>
            )}
          </li>
        ))}
        {!categories.length && <li className="muted">No categories yet.</li>}
      </ul>
    </Modal>
  )
}
