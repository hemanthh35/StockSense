import { useRef, useState } from 'react'
import { api } from '../api'
import { Icon } from './icons.jsx'
import { Modal } from './ui.jsx'

const SAMPLE = `name,sku,category,uom,unit_cost,hsn_code,tax,reorder_min,reorder_qty,initial_stock
Office Chair,CHAIR001,Furniture,Unit,4200,9401,GST 18%,8,20,30
A4 Paper Ream,PAPER01,Stationery,Ream,320,4802,12,40,100,150
`

const ACTION = { create: ['New', 'ready'], update: ['Update', 'waiting'], error: ['Skipped', 'cancelled'] }

/** Upload a CSV, preview what would happen row by row, then apply. Nothing is written until "Import". */
export default function ProductImport({ onClose, onDone, notify }) {
  const input = useRef()
  const [file, setFile] = useState(null)
  const [text, setText] = useState('')
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const choose = async (f) => {
    if (!f) return
    setError(''); setPreview(null); setFile(f)
    try {
      const t = await f.text()
      setText(t)
      setBusy(true)
      setPreview(await api('/products/import', { method: 'POST', body: { csv: t, dry_run: true } }))
    } catch (e) { setError(e.message) }
    setBusy(false)
  }

  const apply = async () => {
    setBusy(true)
    try {
      const r = await api('/products/import', { method: 'POST', body: { csv: text, dry_run: false } })
      notify(`Imported: ${r.created} new, ${r.updated} updated${r.skipped ? `, ${r.skipped} skipped` : ''}`, 'ok')
      onDone()
    } catch (e) { setError(e.message); setBusy(false) }
  }

  const template = () => {
    const url = URL.createObjectURL(new Blob([SAMPLE], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url; a.download = 'products-template.csv'; a.click()
    URL.revokeObjectURL(url)
  }

  const importable = preview ? preview.created + preview.updated : 0
  return (
    <Modal
      width={720}
      title="Import products"
      subtitle="Upload a CSV. Products are matched by SKU: new SKUs are created, existing ones are updated."
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!importable || busy} onClick={apply}>{busy ? 'Working…' : `Import ${importable || ''} product${importable === 1 ? '' : 's'}`}</button>
        </>
      }
    >
      <div className="dropzone" onClick={() => input.current.click()}>
        <Icon name="upload" size={22} />
        <div>
          <b>{file ? file.name : 'Choose a CSV file'}</b>
          <small>{file ? 'Click to choose a different file' : 'Columns: name, sku (required), category, uom, unit_cost, hsn_code, tax, reorder_min, reorder_qty, initial_stock'}</small>
        </div>
        <input ref={input} type="file" accept=".csv,text/csv" hidden onChange={(e) => choose(e.target.files[0])} />
      </div>
      <p className="small muted" style={{ margin: '10px 0 0' }}>
        <button className="link small" onClick={template}>Download a template</button> · Tax can be a name (<span className="mono">GST 18%</span>), a rate (<span className="mono">18</span>) or <span className="mono">none</span>; leave it blank to use the default. Opening stock is only applied to new products.
      </p>

      {error && <div className="form-error" style={{ marginTop: 14 }}><Icon name="alert" size={16} />{error}</div>}

      {preview && (
        <>
          <div className="import-summary">
            <span className="badge ready">{preview.created} new</span>
            <span className="badge waiting">{preview.updated} to update</span>
            <span className={`badge ${preview.skipped ? 'cancelled' : 'done'}`}>{preview.skipped} skipped</span>
          </div>
          <div className="table-wrap import-table">
            <table>
              <thead><tr><th style={{ width: 60 }}>Row</th><th>SKU</th><th>Name</th><th style={{ width: 100 }}>Result</th></tr></thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.row} className={r.action === 'error' ? 'short' : ''}>
                    <td className="muted">{r.row}</td>
                    <td className="mono">{r.sku || '—'}</td>
                    <td>{r.name || '—'}{r.message && <div className="line-warn"><Icon name="alert" size={13} />{r.message}</div>}</td>
                    <td><span className={`badge ${ACTION[r.action][1]}`}>{ACTION[r.action][0]}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.rows.length >= 200 && <p className="small muted">Showing the first 200 rows.</p>}
        </>
      )}
    </Modal>
  )
}
