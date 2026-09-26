import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, getToken, setToken } from './api'
import { atLeast, ROLE_LABEL } from './perm.js'
import Layout from './components/Layout.jsx'
import { Icon } from './components/icons.jsx'
import { Empty } from './components/ui.jsx'
import Activity from './pages/Activity.jsx'
import { Forgot, Login, Signup } from './pages/Auth.jsx'
import Dashboard from './pages/Dashboard.jsx'
import { OperationList } from './pages/Operations.jsx'
import OperationDetail from './pages/OperationDetail.jsx'
import { Products, Stock } from './pages/Catalog.jsx'
import Contacts from './pages/Contacts.jsx'
import MoveHistory from './pages/MoveHistory.jsx'
import { Locations, Warehouses } from './pages/Settings.jsx'
import Profile from './pages/Profile.jsx'
import Taxes from './pages/Taxes.jsx'
import Users from './pages/Users.jsx'

/** The server enforces permissions; this just shows a friendly page instead of a screen full of errors. */
function Guard({ user, role, children }) {
  if (atLeast(user, role)) return children
  return <Empty icon="lock" title="You don't have access to this page" hint={`It needs the ${ROLE_LABEL[role].toLowerCase()} role. You are signed in as ${ROLE_LABEL[user.role].toLowerCase()}.`} />
}

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

  const admin = (el) => <Guard user={user} role="admin">{el}</Guard>
  return (
    <Routes>
      <Route element={<Layout user={user} onLogout={logout} />}>
        <Route path="/" element={<Dashboard user={user} />} />
        <Route path="/operations/:kind" element={<OperationList user={user} />} />
        <Route path="/operations/:kind/:id" element={<OperationDetail user={user} />} />
        <Route path="/products" element={<Products user={user} />} />
        <Route path="/stock" element={<Stock />} />
        <Route path="/contacts" element={<Contacts user={user} />} />
        <Route path="/moves" element={<MoveHistory />} />
        <Route path="/settings/warehouses" element={admin(<Warehouses />)} />
        <Route path="/settings/locations" element={admin(<Locations />)} />
        <Route path="/settings/taxes" element={admin(<Taxes />)} />
        <Route path="/settings/users" element={admin(<Users me={user} />)} />
        <Route path="/activity" element={<Guard user={user} role="manager"><Activity /></Guard>} />
        <Route path="/profile" element={<Profile user={user} onUserChange={setUser} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
