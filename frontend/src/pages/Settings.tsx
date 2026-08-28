import { useEffect, useState } from 'react'
import { api, Preferences, Server } from '../lib/api'
import { useToast } from '../components/Toast'

export function Settings({ servers, prefs, onPrefs, onEditServer, onAddServer,
                           onDeleteServer, onClose }: {
  servers: Server[]
  prefs: Preferences
  onPrefs: (p: Preferences) => void
  onEditServer: (s: Server) => void
  onAddServer: () => void
  onDeleteServer: (s: Server) => void
  onClose: () => void
}) {
  const [draft, setDraft] = useState<Preferences>(prefs)
  const [encryption, setEncryption] = useState<boolean | null>(null)
  const toast = useToast()

  useEffect(() => { setDraft(prefs) }, [prefs])
  useEffect(() => {
    api.health().then((h) => setEncryption(h.credentialEncryption)).catch(() => {})
  }, [])

  function update<K extends keyof Preferences>(key: K, value: Preferences[K]) {
    const next = { ...draft, [key]: value }
    setDraft(next)
    api.savePreferences(next).then(onPrefs)
      .catch(() => toast('Could not save settings', 'error'))
  }

  return (
    <div className="content">
      <div className="row" style={{ marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 19 }}>Settings</h2>
        <span className="spacer" />
        <button className="btn" onClick={onClose}>Done</button>
      </div>

      {/* ------------------------------------------------ browsing */}
      <div className="glass" style={{ padding: 16, marginBottom: 14 }}>
        <div className="row" style={{ marginBottom: 12 }}>
          <strong>Browsing defaults</strong>
        </div>

        <div className="field">
          <label>Default view</label>
          <select className="select" value={draft.defaultViewMode}
                  onChange={(e) => update('defaultViewMode', e.target.value as 'list' | 'grid')}>
            <option value="list">List</option>
            <option value="grid">Grid</option>
          </select>
        </div>

        <div className="row" style={{ gap: 10, alignItems: 'flex-start' }}>
          <div className="field" style={{ flex: 1 }}>
            <label>Sort by</label>
            <select className="select" value={draft.defaultSortField}
                    onChange={(e) => update('defaultSortField', e.target.value as Preferences['defaultSortField'])}>
              <option value="name">Name</option>
              <option value="dateModified">Date Modified</option>
              <option value="size">Size</option>
              <option value="type">Type</option>
            </select>
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label>Direction</label>
            <select className="select" value={draft.defaultSortDirection}
                    onChange={(e) => update('defaultSortDirection', e.target.value as 'ascending' | 'descending')}>
              <option value="ascending">Ascending</option>
              <option value="descending">Descending</option>
            </select>
          </div>
        </div>

        <label className="check">
          <input type="checkbox" checked={draft.recursiveSearch}
                 onChange={(e) => update('recursiveSearch', e.target.checked)} />
          <span>Search subfolders by default
            <span className="hint"> — slower on large shares</span></span>
        </label>
        <label className="check">
          <input type="checkbox" checked={draft.showHiddenFiles}
                 onChange={(e) => update('showHiddenFiles', e.target.checked)} />
          <span>Show hidden files</span>
        </label>
      </div>

      {/* ------------------------------------------------ recovery link */}
      <div className="glass" style={{ padding: 16, marginBottom: 14 }}>
        <div className="row" style={{ marginBottom: 8 }}><strong>Recovery link</strong></div>
        <p className="hint" style={{ marginTop: 0 }}>
          Offered on the failure screen when a server can't be reached — normally
          your VPN or tunnel provider's web console.
        </p>
        <div className="notice warn">
          <strong>Platform difference from the native app.</strong> The iOS/Mac
          app launches a VPN app directly with a URL scheme like{' '}
          <span className="mono">tailscale://</span>. A browser cannot do that
          reliably: custom schemes are blocked or silently ignored in most
          contexts, and there is no way to detect whether the app opened. So this
          is a plain <span className="mono">https://</span> link opened in a new
          tab. Use your provider's web admin page.
        </div>

        <div className="field">
          <label htmlFor="rl-name">Button label</label>
          <input id="rl-name" className="input" value={draft.recoveryLinkName}
                 placeholder="Tailscale"
                 onChange={(e) => update('recoveryLinkName', e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="rl-url">URL</label>
          <input id="rl-url" className="input" value={draft.recoveryLinkUrl}
                 placeholder="https://login.tailscale.com/admin/machines"
                 autoCapitalize="none" autoCorrect="off" spellCheck={false}
                 onChange={(e) => update('recoveryLinkUrl', e.target.value)} />
        </div>
        {draft.recoveryLinkUrl && (
          <button className="btn sm"
                  onClick={() => window.open(draft.recoveryLinkUrl, '_blank', 'noopener,noreferrer')}>
            Test link
          </button>
        )}
      </div>

      {/* ------------------------------------------------ servers */}
      <div className="glass" style={{ padding: 16, marginBottom: 14 }}>
        <div className="row" style={{ marginBottom: 12 }}>
          <strong>Saved servers</strong>
          <span className="spacer" />
          <button className="btn sm primary" onClick={onAddServer}>Add</button>
        </div>

        {servers.length === 0 ? (
          <div className="hint">No servers saved yet.</div>
        ) : (
          <div className="stack">
            {servers.map((s) => (
              <div className="row" key={s.id}
                   style={{ padding: '9px 11px', border: '1px solid var(--edge)',
                            borderRadius: 12 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 570 }}>{s.name}</div>
                  <div className="hint truncate">{s.subtitle}</div>
                </div>
                {s.hasSavedPassword && (
                  <span className={`badge ${s.passwordRecoverable ? '' : 'warn'}`}>
                    {s.passwordRecoverable ? '🔒 saved' : '⚠ unreadable'}
                  </span>
                )}
                <button className="btn sm" onClick={() => onEditServer(s)}>Edit</button>
                <button className="btn sm danger" onClick={() => onDeleteServer(s)}>Remove</button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ------------------------------------------------ about */}
      <div className="glass" style={{ padding: 16 }}>
        <div className="row" style={{ marginBottom: 8 }}><strong>About</strong></div>
        <p className="hint" style={{ marginTop: 0 }}>
          <strong>smb-web-client</strong> is an SMB <em>client</em>. It connects
          out to file servers. It does not host or create shares, and it does not
          manage this machine's disks.
        </p>
        <div className="row">
          <span className="hint">Credential encryption</span>
          <span className="spacer" />
          <span className={`badge ${encryption ? 'ok' : 'warn'}`}>
            {encryption === null ? '…' : encryption ? 'active' : 'unavailable'}
          </span>
        </div>
      </div>
    </div>
  )
}
