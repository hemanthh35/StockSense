import { useState } from 'react'
import { useApi, useDebounced, usePaged } from '../hooks'
import { Empty, ExportButton, PageHeader, Pager, SearchInput, TableSkeleton, Toast, money, num, usePager, useToast } from '../components/ui.jsx'

const Tile = ({ label, value, tone, hint }) => (
  <div className="card tile">
    <small>{label}</small>
    <b className={tone}>{value}</b>
    {hint && <span className="muted small">{hint}</span>}
  </div>
)

/** Stock valuation and delivery margin: the two "what is my stock worth / what did I earn" views. */
export default function StockReports({ view, tabs }) {
  const isValuation = view === 'valuation'
  const [q, setQ] = useState('')
  const [wh, setWh] = useState('')
  const [days, setDays] = useState(30)
  const dq = useDebounced(q)
  const whs = useApi('/warehouses').data || []
  const [toast, notify, close] = useToast()
  const params = isValuation ? { q: dq, warehouse_id: wh } : { days, warehouse_id: wh }
  const pager = usePaged(isValuation ? '/reports/valuation' : '/reports/margin', params, { size: 10, deps: [view] })
  const data = pager.data
  const rows = pager.rows
  const t = data?.totals
  const maxCat = Math.max(...(data?.by_category || []).map((c) => c.value), 1)

  return (
    <>
      <PageHeader
        title="Stock"
        subtitle={isValuation
          ? 'What the stock on your shelves is worth, at weighted-average purchase cost.'
          : 'Revenue against cost for deliveries you have validated. Tax is excluded.'}
        actions={<ExportButton path={isValuation ? '/export/valuation.csv' : '/export/margin.csv'} params={params} filename={isValuation ? 'stock-valuation.csv' : `margin-${days}d.csv`} onError={(m) => notify(m, 'error')} />}
      />
      {tabs}

      {isValuation ? (
        <div className="tiles">
          <Tile label="Stock value" value={t ? money(t.value) : '…'} hint="at average cost" />
          <Tile label="At sales price" value={t ? money(t.retail_value) : '…'} hint="if all of it sold" />
          <Tile label="Potential margin" value={t ? money(t.potential_margin) : '…'} tone="pos" />
          <Tile label="Units on hand" value={t ? num(t.on_hand) : '…'} />
        </div>
      ) : (
        <div className="tiles">
          <Tile label="Revenue" value={t ? money(t.revenue) : '…'} hint={`last ${days} days`} />
          <Tile label="Cost of goods" value={t ? money(t.cost) : '…'} />
          <Tile label="Margin" value={t ? money(t.margin) : '…'} tone={t && t.margin < 0 ? 'neg' : 'pos'} />
          <Tile label="Margin %" value={t ? `${t.margin_pct}%` : '…'} />
        </div>
      )}

      {isValuation && data?.by_category?.length > 1 && (
        <div className="card card-pad bars">
          <h3>Value by category</h3>
          {data.by_category.map((c) => (
            <div key={c.category} className="bar-row">
              <span>{c.category}</span>
              <span className="track"><i style={{ width: `${(c.value / maxCat) * 100}%` }} /></span>
              <b>{money(c.value)}</b>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <div className="toolbar">
          {isValuation ? <SearchInput value={q} onChange={setQ} placeholder="Search product or SKU" /> : (
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option><option value={365}>Last 12 months</option>
            </select>
          )}
          <select value={wh} onChange={(e) => setWh(e.target.value)}>
            <option value="">All warehouses</option>
            {whs.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </div>
        <div className="table-wrap">
          {isValuation ? (
            <table>
              <thead><tr><th>Product</th><th>Category</th><th className="num">On hand</th><th className="num">Avg cost</th><th className="num">Stock value</th><th className="num">Sales price</th><th className="num">At sales price</th></tr></thead>
              <tbody>
                {pager.loading && !rows.length && <TableSkeleton cols={7} />}
                {rows.map((r) => (
                  <tr key={r.product_id}>
                    <td className="strong">{r.name}<span className="sub mono">{r.sku}</span></td>
                    <td>{r.category ? <span className="tag">{r.category}</span> : <span className="dim">—</span>}</td>
                    <td className="num">{num(r.on_hand)}</td>
                    <td className="num muted">{money(r.avg_cost)}</td>
                    <td className="num strong">{money(r.value)}</td>
                    <td className="num muted">{money(r.sales_price)}</td>
                    <td className="num">{money(r.retail_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table>
              <thead><tr><th>Product</th><th className="num">Quantity</th><th className="num">Revenue</th><th className="num">Cost</th><th className="num">Margin</th><th className="num">Margin %</th></tr></thead>
              <tbody>
                {pager.loading && !rows.length && <TableSkeleton cols={6} />}
                {rows.map((r) => (
                  <tr key={r.product_id}>
                    <td className="strong">{r.name}<span className="sub mono">{r.sku}</span></td>
                    <td className="num">{num(r.quantity)}</td>
                    <td className="num">{money(r.revenue)}</td>
                    <td className="num muted">{money(r.cost)}</td>
                    <td className={`num strong ${r.margin < 0 ? 'neg' : 'pos'}`}>{money(r.margin)}</td>
                    <td className="num">{r.margin_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {!pager.loading && !rows.length && (
          <Empty icon="box" title={isValuation ? 'No stock to value' : 'No completed deliveries'} hint={isValuation ? 'Receive stock and it shows up here.' : `Validate a delivery and its margin appears here.`} />
        )}
        <Pager p={pager} />
      </div>
      <Toast msg={toast.msg} kind={toast.kind} onClose={close} />
    </>
  )
}
