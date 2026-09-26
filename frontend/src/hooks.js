import { useCallback, useEffect, useRef, useState } from 'react'
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

/**
 * Server-side pagination. Fetches one page at a time (`?page=&page_size=`) and returns an object shaped like
 * usePager()'s, so `<Pager p={paged} />` works unchanged. Changing any filter jumps back to page 1, and the
 * previous page stays on screen while the next one loads (no flicker).
 */
export function usePaged(path, params = {}, { size: initialSize = 25, deps = [], enabled = true } = {}) {
  const [size, setSize] = useState(initialSize)
  const [pageState, setPageState] = useState({ fk: '', page: 1 })
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const filterKey = JSON.stringify({ path, params, size, deps })
  const page = pageState.fk === filterKey ? pageState.page : 1 // a new filter always starts at page 1
  const seq = useRef(0)

  const setPage = useCallback((n) => setPageState({ fk: filterKey, page: n }), [filterKey])

  useEffect(() => {
    if (!enabled) return
    const mine = ++seq.current
    setLoading(true)
    api(path, { params: { ...params, page, page_size: size } })
      .then((d) => { if (mine === seq.current) { setData(d); setError('') } })
      .catch((e) => { if (mine === seq.current) setError(e.message) })
      .finally(() => { if (mine === seq.current) setLoading(false) })
    // eslint-disable-next-line
  }, [filterKey, page, tick, enabled])

  const total = data?.total ?? 0
  const pages = data?.pages ?? 1
  return {
    rows: data?.items ?? [],
    data,
    loading,
    error,
    reload: () => setTick((t) => t + 1),
    // pager interface
    page: Math.min(page, pages), setPage, size, setSize: (n) => setSize(n), total, pages,
  }
}
