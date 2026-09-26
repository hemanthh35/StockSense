import { NavLink, Outlet, useNavigate } from 'react-router-dom'

const cls = ({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')

export default function Layout({ user, onLogout }) {
  const nav = useNavigate()
  return (
    <>
      <header className="topbar no-print">
        <div className="brand">StockSense</div>
        <nav>
          <NavLink to="/" end className={cls}>Dashboard</NavLink>
          <div className="dropdown">
            <span className="nav-link">Operations ▾</span>
            <div className="menu">
              <NavLink to="/operations/receipts">Receipts</NavLink>
              <NavLink to="/operations/deliveries">Delivery</NavLink>
              <NavLink to="/operations/transfers">Internal Transfers</NavLink>
              <NavLink to="/operations/adjustments">Adjustment</NavLink>
            </div>
          </div>
          <NavLink to="/products" className={cls}>Products</NavLink>
          <NavLink to="/stock" className={cls}>Stock</NavLink>
          <NavLink to="/moves" className={cls}>Move History</NavLink>
          <div className="dropdown">
            <span className="nav-link">Settings ▾</span>
            <div className="menu">
              <NavLink to="/settings/warehouses">Warehouse</NavLink>
              <NavLink to="/settings/locations">Locations</NavLink>
            </div>
          </div>
        </nav>
        <div className="dropdown right">
          <span className="avatar" title={user.login_id}>{user.login_id[0].toUpperCase()}</span>
          <div className="menu right">
            <NavLink to="/profile">My Profile</NavLink>
            <a onClick={() => { onLogout(); nav('/login') }}>Logout</a>
          </div>
        </div>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </>
  )
}
