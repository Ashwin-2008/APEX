import { NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useStudent } from '../context/StudentContext'
import { LoadingState } from '../components'

const links = [
  ['Dashboard', '/dashboard'], ['Practice', '/practice'], ['Progress', '/progress'], ['Mistakes', '/mistakes'], ['Profile', '/profile'], ['Project Review', '/project-review'], ['Research Lab', '/project-review/research-lab'],
]

export function AppLayout() {
  const { student, ready, leave } = useStudent()
  const location = useLocation()
  if (!ready) return <LoadingState label="Restoring your learning space…" />
  if (!student) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <div className="app-shell">
    <aside className="sidebar"><NavLink className="brand" to="/dashboard">MISTIQ<span>2.0</span></NavLink><nav aria-label="Main navigation">{links.map(([label, to]) => <NavLink key={to} to={to} className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>{label}</NavLink>)}</nav><div className="research-nav"><span>EXPLORE</span><NavLink to="/research" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>Research</NavLink></div><div className="sidebar-footer"><span className="avatar">{student.name.slice(0, 1).toUpperCase()}</span><div className="sidebar-person"><strong>{student.name}</strong><span>Development profile</span></div><button className="icon-button" aria-label="Leave profile" onClick={leave}>↗</button></div></aside>
    <header className="mobile-header"><NavLink className="brand" to="/dashboard">MISTIQ<span>2.0</span></NavLink><button className="mobile-logout" onClick={leave}>Exit profile</button></header>
    <main className="main-content"><div className="showcase-ribbon">Showcase Mode <span>· Synthetic Data</span></div><Outlet /></main>
    <nav className="mobile-nav" aria-label="Mobile navigation">{links.slice(0, 5).map(([label, to]) => <NavLink key={to} to={to} className={({ isActive }) => isActive ? 'mobile-link active' : 'mobile-link'}><span>{label === 'Dashboard' ? '⌂' : label === 'Practice' ? '✎' : label === 'Progress' ? '↗' : label === 'Mistakes' ? '◎' : '○'}</span>{label}</NavLink>)}</nav>
  </div>
}
