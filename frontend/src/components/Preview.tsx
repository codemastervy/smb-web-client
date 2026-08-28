import { useEffect, useState } from 'react'
import { api, Entry } from '../lib/api'
import { bytes, previewKind } from '../lib/format'
import { Modal } from './Modal'

export function Preview({ serverId, entry, onClose }: {
  serverId: string; entry: Entry; onClose: () => void
}) {
  const kind = previewKind(entry.name)
  const url = api.downloadUrl(serverId, entry.path, true)
  const [text, setText] = useState<string | null>(null)

  useEffect(() => {
    if (kind !== 'text') return
    let cancelled = false
    fetch(url, { credentials: 'same-origin' })
      .then((r) => r.blob())
      // Cap it: a multi-gigabyte log must not be pulled into the tab.
      .then((b) => b.slice(0, 512 * 1024).text())
      .then((t) => { if (!cancelled) setText(t) })
      .catch(() => { if (!cancelled) setText('Could not read this file.') })
    return () => { cancelled = true }
  }, [url, kind])

  return (
    <Modal title={entry.name} subtitle={bytes(entry.size)} onClose={onClose}
           actions={<>
             <a className="btn" href={api.downloadUrl(serverId, entry.path)}>Download</a>
             <button className="btn primary" onClick={onClose}>Close</button>
           </>}>
      <div style={{ display: 'grid', placeItems: 'center', minHeight: 130 }}>
        {kind === 'image' && (
          <img src={url} alt={entry.name}
               style={{ maxWidth: '100%', maxHeight: '58vh', borderRadius: 12 }} />
        )}
        {kind === 'video' && (
          <video src={url} controls playsInline
                 style={{ maxWidth: '100%', maxHeight: '58vh', borderRadius: 12 }} />
        )}
        {kind === 'audio' && <audio src={url} controls style={{ width: '100%' }} />}
        {kind === 'pdf' && (
          <iframe src={url} title={entry.name}
                  style={{ width: '100%', height: '58vh', border: 0, borderRadius: 12 }} />
        )}
        {kind === 'text' && (
          <pre className="mono" style={{
            width: '100%', maxHeight: '58vh', overflow: 'auto', margin: 0,
            background: 'rgba(0,0,0,.25)', padding: 12, borderRadius: 12,
            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
          }}>{text ?? 'Loading…'}</pre>
        )}
        {!kind && (
          <div className="hint" style={{ textAlign: 'center' }}>
            No in-browser preview for this file type.<br />Download it instead.
          </div>
        )}
      </div>
    </Modal>
  )
}
