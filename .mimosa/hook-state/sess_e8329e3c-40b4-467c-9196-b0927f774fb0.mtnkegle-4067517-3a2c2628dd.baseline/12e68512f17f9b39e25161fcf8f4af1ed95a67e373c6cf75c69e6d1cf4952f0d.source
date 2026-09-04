import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  Box,
  Download,
  HardDrive,
  Menu,
  Moon,
  Search,
  Settings,
  Sun,
  X,
} from 'lucide-react'
import { NavLink, useNavigate } from 'react-router-dom'

interface ShellProps {
  children: ReactNode
  activeDownloads: number
}

const links = [
  { to: '/models', label: 'Models', icon: Box },
  { to: '/local', label: 'Local library', icon: HardDrive },
  { to: '/downloads', label: 'Downloads', icon: Download },
]

export default function Shell({ children, activeDownloads }: ShellProps) {
  const navigate = useNavigate()
  const searchInput = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [theme, setTheme] = useState<'light' | 'dark'>(() =>
    localStorage.getItem('hugginghack-theme') === 'dark' ? 'dark' : 'light',
  )

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('hugginghack-theme', theme)
  }, [theme])

  useEffect(() => {
    function focusSearch(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null
      const isTyping = target?.matches('input, textarea, select, [contenteditable="true"]')
      if (event.key === '/' && !isTyping) {
        event.preventDefault()
        searchInput.current?.focus()
      }
    }
    window.addEventListener('keydown', focusSearch)
    return () => window.removeEventListener('keydown', focusSearch)
  }, [])

  function search(event: FormEvent) {
    event.preventDefault()
    navigate(`/models?search=${encodeURIComponent(query.trim())}`)
    setMobileOpen(false)
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/models" className="brand" aria-label="HuggingHack home">
            <img src="/hugginghack-mark.svg" alt="" className="brand-mark" />
            <span className="brand-name">HuggingHack</span>
            <span className="brand-local">local</span>
          </NavLink>

          <form className="global-search" onSubmit={search} role="search">
            <Search size={17} aria-hidden="true" />
            <input
              ref={searchInput}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search models on the Hub"
              aria-label="Search models on Hugging Face"
            />
            <kbd>/</kbd>
          </form>

          <nav className="primary-nav" aria-label="Primary navigation">
            {links.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} className={({ isActive }) => (isActive ? 'active' : '')}>
                <Icon size={16} aria-hidden="true" />
                <span>{label}</span>
                {to === '/downloads' && activeDownloads > 0 && (
                  <span className="nav-count">{activeDownloads}</span>
                )}
              </NavLink>
            ))}
            <NavLink to="/settings" aria-label="Settings">
              <Settings size={17} aria-hidden="true" />
              <span className="desktop-hidden-label">Settings</span>
            </NavLink>
          </nav>

          <button
            type="button"
            className="icon-button theme-toggle"
            onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
            aria-label={theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}
          >
            {theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}
          </button>
          <button
            type="button"
            className="icon-button mobile-menu-button"
            onClick={() => setMobileOpen(!mobileOpen)}
            aria-label="Toggle navigation"
            aria-expanded={mobileOpen}
          >
            {mobileOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
        {mobileOpen && (
          <div className="mobile-panel">
            <form className="mobile-search" onSubmit={search}>
              <Search size={17} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search the Hub"
              />
            </form>
            {links.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} onClick={() => setMobileOpen(false)}>
                <Icon size={18} />
                {label}
                {to === '/downloads' && activeDownloads > 0 && (
                  <span className="nav-count">{activeDownloads}</span>
                )}
              </NavLink>
            ))}
            <NavLink to="/settings" onClick={() => setMobileOpen(false)}>
              <Settings size={18} />
              Settings
            </NavLink>
          </div>
        )}
      </header>
      <main>{children}</main>
    </div>
  )
}
