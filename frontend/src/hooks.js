import { useCallback, useEffect, useState } from 'react'
import { api } from './api'

export function useApi(path, params, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const key = JSON.stringify(params || {})
  const reload = useCallback(() => {
    api(path, { params }).then((d) => { setData(d); setError('') }).catch((e) => setError(e.message))
    // eslint-disable-next-line
  }, [path, key])
  useEffect(() => { reload() }, [reload, ...deps])
  return { data, error, reload, setData }
}

export function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}
