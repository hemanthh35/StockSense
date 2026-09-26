import { useEffect, useRef, useState } from 'react'
import { Icon } from './icons.jsx'

const FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'qr_code', 'itf']
export const cameraScanSupported = () => typeof window !== 'undefined' && 'BarcodeDetector' in window && !!navigator.mediaDevices?.getUserMedia

/**
 * Reads a barcode with the phone or laptop camera (where the browser supports it), and always offers a text box:
 * a USB / Bluetooth scanner types the code and presses Enter, so it works there too.
 */
export default function Scanner({ onDetect, hint = 'Point the camera at a barcode, or type / scan the code.' }) {
  const video = useRef()
  const input = useRef()
  const [err, setErr] = useState('')
  const [text, setText] = useState('')
  const camera = cameraScanSupported()

  useEffect(() => {
    input.current?.focus()
    if (!camera) return
    let stream, timer, live = true, last = ''
    const detector = new window.BarcodeDetector({ formats: FORMATS })
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }).then(async (s) => {
      if (!live) { s.getTracks().forEach((t) => t.stop()); return }
      stream = s
      video.current.srcObject = s
      await video.current.play().catch(() => {})
      timer = setInterval(async () => {
        try {
          const found = await detector.detect(video.current)
          const code = found[0]?.rawValue
          if (code && code !== last) { last = code; navigator.vibrate?.(60); onDetect(code) }
          if (!code) last = ''
        } catch { /* a frame that can't be read is fine, try the next one */ }
      }, 350)
    }).catch(() => setErr('The camera is blocked or not available. You can still type or scan the code below.'))
    return () => { live = false; clearInterval(timer); stream?.getTracks().forEach((t) => t.stop()) }
  }, [camera]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="scanner">
      {camera && !err && <div className="scan-view"><video ref={video} muted playsInline /><i className="scan-line" /></div>}
      {(err || !camera) && <div className="hint-box"><Icon name="alert" size={16} /><span>{err || 'This browser can\'t read barcodes with the camera. Use a barcode scanner, or type the code below.'}</span></div>}
      <form className="scan-input" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { onDetect(text.trim()); setText('') } }}>
        <Icon name="scan" size={18} />
        <input ref={input} value={text} onChange={(e) => setText(e.target.value)} placeholder="Barcode or SKU" inputMode="text" autoComplete="off" />
        <button className="btn primary">Find</button>
      </form>
      <small className="muted">{hint}</small>
    </div>
  )
}
