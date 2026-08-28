import { useCallback, useEffect, useState } from 'react'
import {
  api, ApiError, FailureInfo, Preferences, Server, Transfer,
} from './lib/api'
import { ToastHost, useToast } from './components/Toast'
import { ContextMenu, MenuItem, useLongPress } from './components/ContextMenu'
import { FailureScreen } from './components/FailureScreen'
import { Modal } from './components/Modal'
import { ServerForm } from './components/ServerForm'
import { TransfersPanel } from './components/TransfersPanel'
import { Browser } from './pages/Browser'
import { Settings } from './pages/Settings'
import { Login } from './pages/Login'

type Auth = 'checking' | 'in' | 'out'

const DEFAULT_PREFS: Preferences = {
  defaultViewMode: 'list', defaultSortField: 'name',
  defaultSortDirection: 'ascending', recursiveSearch: false,
  showHiddenFiles: false, recoveryLinkName: '', recoveryLinkUrl: '',
}

export default function App() {
  const [auth, setAuth] = useState<Auth>('checking')

  useEffect(() => {
    api.authStatus()
      .then((s) => setAuth(s.authenticated ? 'in' : 'out'))
      .catch(() => setAuth('out'))
  }, [])

  useEffect(() => {
    const onUnauth = () => setAuth('out')
    window.addEventListener('smbweb:unauthenticated', onUnauth)
    return () => window.removeEventListener('smbweb:unauthenticated', onUnauth)
  }, [])

  if (auth === 'checking') {
    return <div style={{ display: 'grid', placeItems: 'center', height: '100vh' }}>
      <span className="spin" />
    </div>
  }
  if (auth === 'out') return <Login onSuccess={() => setAuth('in')} />

  return <ToastHost><Workspace onSignOut={() => setAuth('out')} /></ToastHost>
}

function Workspace({ onSignOut }: { onSignOut: () => void }) {
  const [servers, setServers] = useState<Server[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [prefs, setPrefs] = useState<Preferences>(DEFAULT_PREFS)
  const [transfers, setTransfers] = useState<Transfer[]>([])

  const [menuOpen, setMenuOpen] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showTransfers, setShowTransfers] = useState(false)
  const [editing, setEditing] = useState<Server | null>(null)
  const [adding, setAdding] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState<Server | null>(null)
  const [passwordPrompt, setPasswordPrompt] = useState<Server | null>(null)
  const [connecting, setConnecting] = useState<string | null>(null)
  const [failure, setFailure] = useState<{ info: FailureInfo; serverId: string | null } | null>(null)
  const [serverMenu, setServerMenu] = useState<{ x: number; y: number; server: Server } | null>(null)

  const [theme, setTheme] = useState(() => localStorage.getItem('smbweb-theme') ?? 'dark')
  const toast = useToast()

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('smbweb-theme', theme)
  }, [theme])

  const refreshServers = useCallback(async () => {
    try {
      const r = await api.servers()
      setServers(r.servers)
      return r.servers
    } catch { return [] }
  }, [])

  const refreshTransfers = useCallback(() => {
    api.transfers().then((r) => setTransfers(r.transfers)).catch(() => {})
  }, [])

  useEffect(() => { void refreshServers() }, [refreshServers])
  useEffect(() => { api.preferences().then(setPrefs).catch(() => {}) }, [])

  // Poll transfers only while the panel is open or something is in flight --
  // no point waking the server for a panel nobody is looking at.
  useEffect(() => {
    const busy = transfers.some((t) => t.state === 'active')
    if (!showTransfers && !busy) return
    const timer = window.setInterval(refreshTransfers, 900)
    return () => window.clearInterval(timer)
  }, [showTransfers, transfers, refreshTransfers])

  const active = servers.find((s) => s.id === activeId) ?? null
  const recoveryLink = prefs.recoveryLinkUrl
    ? { name: prefs.recoveryLinkName || 'Recovery Link', url: prefs.recoveryLinkUrl }
    : null

  // ------------------------------------------------------------ connecting

  const connect = useCallback(async (server: Server, password?: string) => {
    setConnecting(server.id)
    try {
      await api.connect(server.id, password)
      setActiveId(server.id)
      setFailure(null)
      setMenuOpen(false)
      await refreshServers()
    } catch (e) {
      if (e instanceof ApiError && e.failure) {
        // A profile that deliberately doesn't save its password should prompt
        // rather than present as a failure.
        if (e.failure.kind === 'authentication_failed'
            && !server.saveCredentials && !password) {
          setPasswordPrompt(server)
        } else {
          setFailure({ info: e.failure, serverId: server.id })
        }
      } else {
        toast(e instanceof Error ? e.message : 'Could not connect', 'error')
      }
      await refreshServers()
    } finally { setConnecting(null) }
  }, [refreshServers, toast])

  async function disconnect(server: Server) {
    await api.disconnect(server.id).catch(() => {})
    if (activeId === server.id) setActiveId(null)
    await refreshServers()
  }

  async function removeServer(server: Server) {
    try {
      await api.deleteServer(server.id)
      if (activeId === server.id) setActiveId(null)
      toast(`Removed ${server.name}`, 'ok')
      await refreshServers()
    } catch { toast('Could not remove that server', 'error') }
  }

  function serverMenuItems(server: Server): MenuItem[] {
    const connected = server.status?.state === 'connected'
    return [
      connected
        ? { label: 'Disconnect', icon: '⏹', onSelect: () => void disconnect(server) }
        : { label: 'Connect', icon: '▶️', onSelect: () => void connect(server) },
      { label: 'Edit Connection', icon: '✏️', separatorBefore: true,
        onSelect: () => setEditing(server) },
      { label: 'Remove', icon: '🗑️', danger: true,
        onSelect: () => setConfirmRemove(server) },
    ]
  }

  // ------------------------------------------------------------ render

  return (
    <>
      <div className="shell">
        {menuOpen && <div className="scrim" onClick={() => setMenuOpen(false)} />}

        <aside className={`sidebar glass ${menuOpen ? 'open' : ''}`}>
          <div className="brand">
            <span className="brand-mark">🗄️</span>
            <span>SMB</span>
          </div>

          <div className="sidebar-scroll">
            <div className="section-label">Servers</div>

            {servers.length === 0 ? (
              <div className="hint" style={{ padding: '6px 10px 12px' }}>
                No servers yet. Add one to get started.
              </div>
            ) : servers.map((server) => (
              <ServerRow key={server.id} server={server}
                         active={server.id === activeId}
                         connecting={connecting === server.id}
                         onOpen={() => {
                           if (server.status?.state === 'connected') {
                             setActiveId(server.id); setMenuOpen(false)
                           } else { void connect(server) }
                         }}
                         onMenu={(x, y) => setServerMenu({ x, y, server })} />
            ))}

            <button className="btn wide" style={{ marginTop: 8 }}
                    onClick={() => setAdding(true)}>+ Add Server</button>
          </div>

          <div className="sidebar-foot">
            <button className="btn ghost wide" style={{ justifyContent: 'flex-start' }}
                    onClick={() => { setShowTransfers((v) => !v); refreshTransfers() }}>
              ⇅ Transfers
              {transfers.some((t) => t.state === 'active') &&
                <span className="badge accent" style={{ marginLeft: 'auto' }}>
                  {transfers.filter((t) => t.state === 'active').length}
                </span>}
            </button>
            <button className="btn ghost wide" style={{ justifyContent: 'flex-start' }}
                    onClick={() => { setShowSettings(true); setMenuOpen(false) }}>
              ⚙️ Settings
            </button>
            <button className="btn ghost wide" style={{ justifyContent: 'flex-start' }}
                    onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
              {theme === 'dark' ? '☀️ Light' : '🌙 Dark'}
            </button>
            <button className="btn ghost wide" style={{ justifyContent: 'flex-start' }}
                    onClick={async () => { await api.logout().catch(() => {}); onSignOut() }}>
              🚪 Sign out
            </button>
          </div>
        </aside>

        <main className="main glass">
          {showSettings ? (
            <Settings servers={servers} prefs={prefs} onPrefs={setPrefs}
                      onEditServer={(s) => setEditing(s)}
                      onAddServer={() => setAdding(true)}
                      onDeleteServer={(s) => setConfirmRemove(s)}
                      onClose={() => setShowSettings(false)} />
          ) : active && active.status?.state === 'connected' ? (
            <Browser server={active} prefs={prefs}
                     onFailure={(info, serverId) => setFailure({ info, serverId })}
                     onMenu={() => setMenuOpen(true)}
                     onOpenTransfers={() => setShowTransfers(true)}
                     refreshTransfers={refreshTransfers} />
          ) : (
            <>
              <header className="topbar">
                <button className="btn ghost icon menu-btn" onClick={() => setMenuOpen(true)}
                        aria-label="Open menu">☰</button>
                <h1>SMB</h1>
              </header>
              <div className="content">
                <div className="empty">
                  <span className="glyph">🗄️</span>
                  {servers.length === 0
                    ? <>No servers yet.<br />
                        <span className="hint">Add a connection to start browsing.</span></>
                    : <>Select a server to connect.<br />
                        <span className="hint">Choose one from the sidebar.</span></>}
                  <div style={{ marginTop: 18 }}>
                    <button className="btn primary" onClick={() => setAdding(true)}>
                      + Add Server
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </main>
      </div>

      {/* ------------------------------------------------ overlays */}

      {serverMenu && (
        <ContextMenu x={serverMenu.x} y={serverMenu.y}
                     items={serverMenuItems(serverMenu.server)}
                     onClose={() => setServerMenu(null)} />
      )}

      {(adding || editing) && (
        <ServerForm server={editing}
                    onClose={() => { setAdding(false); setEditing(null) }}
                    onSaved={async (saved) => {
                      setAdding(false); setEditing(null)
                      const list = await refreshServers()
                      const fresh = list.find((s) => s.id === saved.id)
                      if (fresh) void connect(fresh)
                    }} />
      )}

      {passwordPrompt && (
        <PasswordPrompt server={passwordPrompt}
                        onClose={() => setPasswordPrompt(null)}
                        onSubmit={(pw) => {
                          const server = passwordPrompt
                          setPasswordPrompt(null)
                          void connect(server, pw)
                        }} />
      )}

      {confirmRemove && (
        <Modal title={`Remove ${confirmRemove.name}?`}
               subtitle="This deletes the saved connection and its stored password. Nothing on the server is touched."
               onClose={() => setConfirmRemove(null)}
               actions={<>
                 <button className="btn" onClick={() => setConfirmRemove(null)}>Cancel</button>
                 <button className="btn danger"
                         onClick={() => { void removeServer(confirmRemove); setConfirmRemove(null) }}>
                   Remove
                 </button>
               </>}>
          <div className="notice"><span className="mono">{confirmRemove.subtitle}</span></div>
        </Modal>
      )}

      {showTransfers && (
        <TransfersPanel transfers={transfers}
                        onClose={() => setShowTransfers(false)}
                        onClear={async () => {
                          await api.clearTransfers().catch(() => {})
                          refreshTransfers()
                        }} />
      )}

      {failure && (
        <FailureScreen failure={failure.info} serverId={failure.serverId}
                       recoveryLink={recoveryLink}
                       onEditConnection={() => {
                         const server = servers.find((s) => s.id === failure.serverId)
                         setFailure(null)
                         if (server) setEditing(server)
                       }}
                       onRetry={async () => {
                         const server = servers.find((s) => s.id === failure.serverId)
                         if (!server) { setFailure(null); return }
                         setFailure(null)
                         // connect() sets a fresh failure if this attempt also
                         // fails, so the modal reappears with the new reason.
                         await connect(server)
                       }}
                       onOpenSettings={() => { setFailure(null); setShowSettings(true) }}
                       onDismiss={() => setFailure(null)} />
      )}
    </>
  )
}

function ServerRow({ server, active, connecting, onOpen, onMenu }: {
  server: Server; active: boolean; connecting: boolean
  onOpen: () => void; onMenu: (x: number, y: number) => void
}) {
  const press = useLongPress(onMenu)
  const state = connecting ? 'connecting' : (server.status?.state ?? 'idle')

  return (
    <button className={`server-row ${active ? 'active' : ''}`} {...press} onClick={onOpen}>
      <span className={`status-dot ${state}`} aria-hidden="true" />
      <span className="meta">
        <span className="title">{server.name}</span>
        <span className="sub">{server.subtitle}</span>
      </span>
      {connecting && <span className="spin" />}
      <span className="btn ghost icon" role="button" tabIndex={-1}
            aria-label={`Actions for ${server.name}`}
            onClick={(e) => { e.stopPropagation(); onMenu(e.clientX, e.clientY) }}>⋯</span>
    </button>
  )
}

function PasswordPrompt({ server, onClose, onSubmit }: {
  server: Server; onClose: () => void; onSubmit: (password: string) => void
}) {
  const [value, setValue] = useState('')
  return (
    <Modal title={`Password for ${server.name}`}
           subtitle="This connection is set not to save its password."
           onClose={onClose}
           actions={<>
             <button className="btn" onClick={onClose}>Cancel</button>
             <button className="btn primary" disabled={!value}
                     onClick={() => onSubmit(value)}>Connect</button>
           </>}>
      <div className="field">
        <label htmlFor="pp">Password</label>
        <input id="pp" className="input" type="password" value={value} autoFocus
               autoComplete="current-password"
               onChange={(e) => setValue(e.target.value)}
               onKeyDown={(e) => { if (e.key === 'Enter' && value) onSubmit(value) }} />
      </div>
    </Modal>
  )
}
