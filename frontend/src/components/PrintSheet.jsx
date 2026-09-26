import { money, num } from './ui.jsx'

const date = (d) => new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })

/** Which paper documents make sense for each kind of operation. */
export function sheetsFor(op) {
  if (!op) return []
  if (op.type === 'OUT') return [{ id: 'challan', label: 'Delivery challan' }, { id: 'invoice', label: 'Tax invoice' }, { id: 'picklist', label: 'Pick list' }]
  if (op.type === 'IN') return [{ id: 'challan', label: 'Goods receipt note' }]
  if (op.type === 'INT') return [{ id: 'picklist', label: 'Transfer slip' }]
  return []
}

const TITLE = {
  challan: (op) => (op.type === 'IN' ? 'Goods Receipt Note' : 'Delivery Challan'),
  invoice: () => 'Tax Invoice',
  picklist: (op) => (op.type === 'INT' ? 'Transfer Slip' : 'Pick List'),
}

/** A clean paper layout. It is invisible on screen and takes over the page only while printing (see .print-sheet in the CSS). */
export default function PrintSheet({ op, kind }) {
  if (!op || !kind) return null
  const party = op.party || (op.contact ? { name: op.contact } : null)
  const lines = op.lines || []
  const invoice = kind === 'invoice'
  const totalQty = lines.reduce((s, l) => s + l.quantity, 0)

  return (
    <section className="print-sheet" aria-hidden="true">
      <div className="ps-head">
        <div><b className="ps-brand">StockSense</b><span>{op.warehouse?.name}</span></div>
        <div className="ps-title"><h1>{TITLE[kind](op)}</h1><span className="mono">{op.reference}</span></div>
      </div>

      <div className="ps-meta">
        {party && op.type !== 'INT' && (
          <div>
            <small>{op.type === 'IN' ? 'Supplier' : 'Bill to / Ship to'}</small>
            <b>{party.name}</b>
            {party.address && <span>{party.address}</span>}
            {party.gstin && <span>GSTIN {party.gstin}{party.state ? ` · ${party.state}` : ''}</span>}
          </div>
        )}
        <div>
          <small>Date</small><b>{date(op.schedule_date || new Date())}</b>
          <small>Status</small><b style={{ textTransform: 'capitalize' }}>{op.status}</b>
        </div>
        <div>
          <small>From</small><b>{op.source_location?.name}</b>
          <small>To</small><b>{op.dest_location?.name}</b>
        </div>
      </div>

      <table>
        <thead>
          {kind === 'picklist' && <tr><th style={{ width: 34 }}>✓</th><th>Product</th><th className="num">Quantity</th><th>Notes</th></tr>}
          {kind === 'challan' && <tr><th style={{ width: 34 }}>#</th><th>Product</th><th className="num">Quantity</th></tr>}
          {invoice && <tr><th style={{ width: 34 }}>#</th><th>Product</th><th className="num">Qty</th><th className="num">Rate</th><th className="num">Tax</th><th className="num">Amount</th></tr>}
        </thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={l.id}>
              <td>{kind === 'picklist' ? '☐' : i + 1}</td>
              <td>{l.product}</td>
              <td className="num">{num(l.quantity)}</td>
              {kind === 'picklist' && <td>{l.short ? `Short by ${num(l.missing)}` : ''}</td>}
              {invoice && (<>
                <td className="num">{money(l.unit_price)}</td>
                <td className="num">{l.tax_name ? `${l.tax_name}` : '—'}</td>
                <td className="num">{money(l.subtotal)}</td>
              </>)}
            </tr>
          ))}
        </tbody>
        <tfoot>
          {!invoice && <tr><td /><td className="num">Total quantity</td><td className="num">{num(totalQty)}</td>{kind === 'picklist' && <td />}</tr>}
        </tfoot>
      </table>

      {invoice && (
        <div className="ps-totals">
          <div><span>Subtotal</span><b>{money(op.subtotal)}</b></div>
          {op.tax_breakdown?.map((g) => <div key={g.name}><span>{g.name} on {money(g.base)}</span><b>{money(g.amount)}</b></div>)}
          <div className="grand"><span>Total</span><b>{money(op.total)}</b></div>
        </div>
      )}

      {kind !== 'picklist' && (
        <div className="ps-sign">
          <div><span /><small>{op.type === 'IN' ? 'Received by' : 'Prepared by'}</small></div>
          <div><span /><small>{op.type === 'IN' ? 'Delivered by' : 'Received by (name, signature, date)'}</small></div>
        </div>
      )}
      {kind === 'picklist' && <div className="ps-sign"><div><span /><small>Picked by</small></div><div><span /><small>Checked by</small></div></div>}
      <p className="ps-foot">Computer generated document · {op.reference} · printed {date(new Date())}</p>
    </section>
  )
}
