import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, getToken, setToken } from './api'
import Layout from './components/Layout.jsx'
import { Forgot, Login, Signup } from './pages/Auth.jsx'
import Dashboard from './pages/Dashboard.jsx'
import { OperationList } from './pages/Operations.jsx'
import OperationDetail from './pages/OperationDetail.jsx'
import { Products, Stock } from './pages/Catalog.jsx'
import MoveHistory from './pages/MoveHistory.jsx'
import { Locations, Profile, Warehouses } from './pages/Settings.jsx'
import Taxes from './pages/Taxes.jsx'

export default function App() {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(!getToken())

  useEffect(() => {
    if (!getToken()) return
    api('/auth/me').then(setUser).catch(() => setToken(null)).finally(() => setReady(true))
  }, [])

  const onAuth = ({ token, user }) => { setToken(token); setUser(user) }
  const logout = () => { setToken(null); setUser(null) }

  if (!ready) return <div className="center muted">Loading…</div>

  if (!user)
    return (
      <Routes>
        <Route path="/login" element={<Login onAuth={onAuth} />} />
        <Route path="/signup" element={<Signup onAuth={onAuth} />} />
        <Route path="/forgot" element={<Forgot />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )

  return (
    <Routes>
      <Route element={<Layout user={user} onLogout={logout} />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/operations/:kind" element={<OperationList />} />
        <Route path="/operations/:kind/:id" element={<OperationDetail user={user} />} />
        <Route path="/products" element={<Products />} />
        <Route path="/stock" element={<Stock />} />
        <Route path="/moves" element={<MoveHistory />} />
        <Route path="/settings/warehouses" element={<Warehouses />} />
        <Route path="/settings/locations" element={<Locations />} />
        <Route path="/settings/taxes" element={<Taxes />} />
        <Route path="/profile" element={<Profile user={user} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
