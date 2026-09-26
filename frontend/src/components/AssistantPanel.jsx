import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Icon } from './icons.jsx'

const PATH = { IN: 'receipts', OUT: 'deliveries', INT: 'transfers', ADJ: 'adjustments' }
const IDEAS = [
  'What is running low?',
  'Which deliveries are late?',
  'Give me a business summary',
  'Which products will run out soon?',
]

/** **bold** and line breaks only; everything else is shown as plain text. */
function Text({ children }) {
  return String(children).split('\n').map((line, i) => (
    <p key={i}>{line.split(/(\*\*[^*]+\*\*)/g).map((s, j) => (s.startsWith('**') && s.endsWith('**') ? <b key={j}>{s.slice(2, -2)}</b> : s))}</p>
  ))
}

function Proposal({ p, state, onConfirm, onCancel }) {
  const r = state?.result
  return (
    <div className={`ai-proposal ${state?.status || ''}`}>
      <div className="ai-prop-title"><Icon name="check" size={14} />Proposed change</div>
      <p>{p.summary}</p>
      {!state && (
        <div className="ai-prop-actions">
          <button className="btn primary sm" onClick={onConfirm}>Confirm</button>
          <button className="btn sm" onClick={onCancel}>Cancel</button>
        </div>
      )}
      {state?.status === 'working' && <small className="muted">Working…</small>}
      {state?.status === 'done' && (
        <small className="ai-ok">
          Done{r?.reference && r?.id && PATH[r.type] ? <> — <Link className="link" to={`/operations/${PATH[r.type]}/${r.id}`}>{r.reference}</Link></> : r?.reference ? ` — ${r.reference}` : ''}
        </small>
      )}
      {state?.status === 'cancelled' && <small className="muted">Cancelled</small>}
      {state?.status === 'error' && <small className="ai-err">{state.error}</small>}
    </div>
  )
}

/** Floating chat. The assistant only proposes changes; nothing happens until the person presses Confirm. */
export default function AssistantPanel({ open, onClose }) {
  const [info, setInfo] = useState(null)
  const [msgs, setMsgs] = useState([]) // {role, content, pending?}
  const [acts, setActs] = useState({}) // action id -> state
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef()
  const input = useRef()

  useEffect(() => { if (open && !info) api('/assistant/status').then(setInfo).catch(() => setInfo({ enabled: false })) }, [open, info])
  useEffect(() => { if (open) setTimeout(() => input.current?.focus(), 60) }, [open])
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [msgs, busy, acts])
  useEffect(() => {
    if (!open) return
    const h = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, onClose])

  if (!open) return null

  const send = async (q) => {
    const content = (q ?? text).trim()
    if (!content || busy) return
    const next = [...msgs, { role: 'user', content }]
    setMsgs(next)
    setText('')
    setBusy(true)
    try {
      const body = { messages: next.slice(-12).map(({ role, content }) => ({ role, content })) }
      const out = await api('/assistant/chat', { method: 'POST', body })
      setMsgs([...next, { role: 'assistant', content: out.reply, pending: out.pending }])
    } catch (e) {
      setMsgs([...next, { role: 'assistant', content: e.message, error: true }])
    } finally { setBusy(false) }
  }

  const act = async (id, verb) => {
    setActs((a) => ({ ...a, [id]: { status: 'working' } }))
    try {
      const out = await api(`/assistant/actions/${id}/${verb}`, { method: 'POST' })
      setActs((a) => ({ ...a, [id]: { status: verb === 'confirm' ? 'done' : 'cancelled', result: out.result } }))
    } catch (e) {
      setActs((a) => ({ ...a, [id]: { status: 'error', error: e.message } }))
    }
  }

  return (
    <aside className="ai-panel no-print" role="dialog" aria-label="Assistant">
      <header>
        <span className="ai-spark"><Icon name="spark" size={16} /></span>
        <div><b>Assistant</b><small>Ask about stock, or tell it what to prepare</small></div>
        <button className="icon-btn" onClick={() => { setMsgs([]); setActs({}) }} aria-label="New chat" title="New chat"><Icon name="refresh" size={16} /></button>
        <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={18} /></button>
      </header>
      <div className="ai-body">
        {info && !info.enabled && <div className="hint-box">The assistant isn't set up yet. An administrator needs to add a <span className="mono">GROQ_API_KEY</span> to the server settings.</div>}
        {info?.enabled && !msgs.length && (
          <div className="ai-empty">
            <p>Hi! I can look things up and prepare changes for you to approve.</p>
            <div className="ai-ideas">{IDEAS.map((i) => <button key={i} onClick={() => send(i)}>{i}</button>)}</div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`ai-msg ${m.role} ${m.error ? 'error' : ''}`}>
            <div className="ai-bubble"><Text>{m.content}</Text></div>
            {m.pending?.map((p) => <Proposal key={p.id} p={p} state={acts[p.id]} onConfirm={() => act(p.id, 'confirm')} onCancel={() => act(p.id, 'cancel')} />)}
          </div>
        ))}
        {busy && <div className="ai-msg assistant"><div className="ai-bubble ai-typing"><i /><i /><i /></div></div>}
        <div ref={end} />
      </div>
      <form className="ai-input" onSubmit={(e) => { e.preventDefault(); send() }}>
        <input ref={input} value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} placeholder={info?.enabled === false ? 'Assistant is off' : 'Ask anything about your stock…'} disabled={info?.enabled === false} />
        <button className="btn primary" disabled={busy || !text.trim() || info?.enabled === false} aria-label="Send"><Icon name="arrowright" size={16} /></button>
      </form>
    </aside>
  )
}
