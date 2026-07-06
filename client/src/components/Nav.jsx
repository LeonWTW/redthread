import { Link, NavLink, useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import Logo from './Logo.jsx'

// Shared top nav for every screen except Login. The app has exactly five
// screens (Inbox, Triage, Library, Report Editor, Export Preview) plus the
// Capture utility page; unbuilt screens render a placeholder route.
const LINKS = [
  { to: '/inbox', label: 'Inbox' },
  { to: '/triage', label: 'Triage' },
  { to: '/library', label: 'Library' },
  { to: '/reports', label: 'Report' },
  { to: '/export', label: 'Export' },
  { to: '/', label: 'Capture' },
]

export default function Nav() {
  const navigate = useNavigate()

  async function onLogout() {
    try {
      await api('/api/logout', { method: 'POST' })
    } catch {
      // Session may already be gone; either way, go to login.
    }
    navigate('/login')
  }

  return (
    <nav className="topnav" aria-label="Main navigation">
      <Link to="/" className="nav-brand" aria-label="RedThread home">
        <Logo size={22} withWordmark />
      </Link>
      {LINKS.map((link) => (
        <NavLink
          key={link.to}
          to={link.to}
          end={link.to === '/'}
          className={({ isActive }) => (isActive ? 'nav-link nav-active' : 'nav-link')}
        >
          {link.label}
        </NavLink>
      ))}
      <button type="button" className="nav-logout" onClick={onLogout}>
        Logout
      </button>
    </nav>
  )
}
