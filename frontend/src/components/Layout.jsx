import { useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Icon, LogoMark } from './icons.jsx'
import { Menu } from './ui.jsx'

const cls = ({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')

function GroupTrigger({ label, active, open, toggle }) {
  return (
    <button className={`nav-link ${active ? 'active' : ''} ${open ? 'open' : ''}`} onClick={toggle}>
      {label}
      <Icon name="down" size={14} className="caret" />
    </button>
  )
}

const MenuItem = ({ to, icon, title, desc }) => (
  <NavLink to={to} className="menu-item">
    <span className="mi-icon"><Icon name={icon} size={17} /></span>
    <span><b>{title}</b>{desc && <small>{desc}</small>}</span>
  </NavLink>
)

export default function Layout({ user, onLogout }) {
  const nav = useNavigate()
  const { pathname } = useLocation()
  const [mobile, setMobile] = useState(false)

  return (
    <>
      <header className="topbar no-print">
        <div className="topbar-in">
          <Link to="/" className="brand" onClick={() => setMobile(false)}>
            <LogoMark size={28} />
            <span>StockSense</span>
          </Link>
          <button className="icon-btn mobile-only" onClick={() => setMobile((m) => !m)} aria-label="Menu"><Icon name={mobile ? 'x' : 'menu'} size={20} /></button>

          <nav className={mobile ? 'open' : ''} onClick={() => setMobile(false)}>
            <NavLink to="/" end className={cls}>Dashboard</NavLink>
            <Menu trigger={(open, toggle) => <GroupTrigger label="Operations" active={pathname.startsWith('/operations')} open={open} toggle={toggle} />}>
              <MenuItem to="/operations/receipts" icon="receive" title="Receipts" desc="Incoming stock from vendors" />
              <MenuItem to="/operations/deliveries" icon="deliver" title="Deliveries" desc="Outgoing stock to customers" />
              <MenuItem to="/operations/transfers" icon="swap" title="Internal transfers" desc="Move stock between locations" />
              <MenuItem to="/operations/adjustments" icon="sliders" title="Adjustments" desc="Reconcile counted quantities" />
            </Menu>
            <NavLink to="/products" className={cls}>Products</NavLink>
            <NavLink to="/stock" className={cls}>Stock</NavLink>
            <NavLink to="/moves" className={cls}>Move History</NavLink>
            <Menu trigger={(open, toggle) => <GroupTrigger label="Settings" active={pathname.startsWith('/settings')} open={open} toggle={toggle} />}>
              <MenuItem to="/settings/warehouses" icon="warehouse" title="Warehouse" desc="Names, codes and addresses" />
              <MenuItem to="/settings/locations" icon="pin" title="Locations" desc="Racks, rooms and stock areas" />
            </Menu>
          </nav>

          <Menu
            align="right"
            trigger={(_, toggle) => (
              <button className="user-btn" onClick={toggle} aria-label="Account">
                <span className="avatar">{user.login_id[0].toUpperCase()}</span>
                <span className="user-name">{user.login_id}</span>
                <Icon name="down" size={14} className="caret" />
              </button>
            )}
          >
            <div className="menu-head"><b>{user.login_id}</b><small>{user.email}</small></div>
            <NavLink to="/profile" className="menu-item slim"><Icon name="user" size={16} />My Profile</NavLink>
            <a className="menu-item slim danger" onClick={() => { onLogout(); nav('/login') }}><Icon name="logout" size={16} />Log out</a>
          </Menu>
        </div>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </>
  )
}
