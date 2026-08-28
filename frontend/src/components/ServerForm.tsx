import { useState } from 'react'
import { api, ApiError, FailureInfo, Server, ServerInput } from '../lib/api'
import { Modal } from './Modal'
import { useToast } from './Toast'

const EMPTY: ServerInput = {
  name: '', host: '', port: 445, shareName: '',
  username: '', password: '', domain: '', saveCredentials: true,
}

export function ServerForm({ server, onClose, onSaved }: {
  server: Server | null
  onClose: () => void
  onSaved: (server: Server) => void
}) {
  const [form, setForm] = useState<ServerInput>(server ? {
    name: server.name === server.host ? '' : server.name,
    host: server.host, port: server.port, shareName: server.shareName,
    username: server.username, password: '', domain: server.domain,
    saveCredentials: server.saveCredentials,
  } : EMPTY)

  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tested, setTested] = useState<{ ok: boolean; failure?: FailureInfo } | null>(null)
  const toast = useToast()

  const set = <K extends keyof ServerInput>(key: K, value: ServerInput[K]) => {
    setForm((f) => ({ ...f, [key]: value }))
    setTested(null)
  }

  const validation = (() => {
    if (!form.host.trim()) return 'Host or IP address is required.'
    if (!form.shareName.trim()) return 'Share name is required.'
    if (form.port < 1 || form.port > 65535) return 'Port must be between 1 and 65535.'
    return null
  })()

  async function test() {
    setTesting(true); setTested(null); setError(null)
    try {
      setTested(await api.testConnection(form))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Test failed')
    } finally { setTesting(false) }
  }

  async function save() {
    setBusy(true); setError(null)
    try {
      const saved = server
        ? await api.updateServer(server.id, form)
        : await api.createServer(form)
      toast(server ? 'Connection updated' : 'Connection saved', 'ok')
      onSaved(saved)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not save')
    } finally { setBusy(false) }
  }

  return (
    <Modal title={server ? `Edit ${server.name}` : 'Add SMB Server'}
           subtitle={server ? server.subtitle : 'Connect to a file server on your network'}
           onClose={onClose}
           actions={<>
             <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
             <button className="btn" onClick={test} disabled={testing || !!validation}>
               {testing ? <span className="spin" /> : 'Test'}
             </button>
             <button className="btn primary" onClick={save} disabled={busy || !!validation}>
               {busy ? <span className="spin" /> : server ? 'Save' : 'Add Server'}
             </button>
           </>}>

      <div className="field">
        <label htmlFor="f-name">Name <span className="hint">(optional)</span></label>
        <input id="f-name" className="input" value={form.name} autoFocus
               placeholder="Defaults to the host name"
               onChange={(e) => set('name', e.target.value)} />
      </div>

      <div className="row" style={{ gap: 10, alignItems: 'flex-start' }}>
        <div className="field" style={{ flex: 3 }}>
          <label htmlFor="f-host">Host or IP</label>
          <input id="f-host" className="input" value={form.host}
                 placeholder="192.168.1.50 or nas.local"
                 autoCapitalize="none" autoCorrect="off" spellCheck={false}
                 onChange={(e) => set('host', e.target.value)} />
        </div>
        <div className="field" style={{ flex: 1, minWidth: 92 }}>
          <label htmlFor="f-port">Port</label>
          <input id="f-port" className="input" type="number" value={form.port}
                 onChange={(e) => set('port', Number(e.target.value) || 445)} />
        </div>
      </div>

      <div className="field">
        <label htmlFor="f-share">Share name</label>
        <input id="f-share" className="input" value={form.shareName}
               placeholder="Documents"
               autoCapitalize="none" autoCorrect="off" spellCheck={false}
               onChange={(e) => set('shareName', e.target.value)} />
        <span className="hint">
          The share, not a path — <span className="mono">smb://host/<b>ShareName</b></span>
        </span>
      </div>

      <div className="field">
        <label htmlFor="f-user">Username</label>
        <input id="f-user" className="input" value={form.username}
               placeholder="Leave blank for guest access"
               autoCapitalize="none" autoCorrect="off" spellCheck={false}
               autoComplete="username"
               onChange={(e) => set('username', e.target.value)} />
      </div>

      <div className="field">
        <label htmlFor="f-pass">
          Password {server?.hasSavedPassword && <span className="hint">(leave blank to keep)</span>}
        </label>
        <input id="f-pass" className="input" type="password" value={form.password}
               autoComplete="new-password"
               onChange={(e) => set('password', e.target.value)} />
        {server?.hasSavedPassword && !server.passwordRecoverable && (
          <span className="hint" style={{ color: 'var(--warn)' }}>
            The saved password can no longer be decrypted (ADMIN_PASSWORD
            changed). Enter it again.
          </span>
        )}
      </div>

      <div className="field">
        <label htmlFor="f-domain">Domain <span className="hint">(optional)</span></label>
        <input id="f-domain" className="input" value={form.domain}
               autoCapitalize="none" autoCorrect="off" spellCheck={false}
               onChange={(e) => set('domain', e.target.value)} />
      </div>

      <label className="check">
        <input type="checkbox" checked={form.saveCredentials}
               onChange={(e) => set('saveCredentials', e.target.checked)} />
        <span>
          Save password
          <span className="hint"> — encrypted at rest. Unticking deletes any password already stored.</span>
        </span>
      </label>

      {tested && (
        <div className={`notice ${tested.ok ? 'accent' : 'danger'}`} style={{ marginTop: 12 }}>
          {tested.ok
            ? '✓ Connected successfully.'
            : <><strong>{tested.failure?.title}</strong><br />{tested.failure?.message}</>}
        </div>
      )}

      {validation && <div className="notice warn" style={{ marginTop: 12 }}>{validation}</div>}
      {error && <div className="notice danger" style={{ marginTop: 12 }}>{error}</div>}
    </Modal>
  )
}
