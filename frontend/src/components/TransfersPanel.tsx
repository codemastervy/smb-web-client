import { Transfer } from '../lib/api'
import { bytes } from '../lib/format'

const GLYPH: Record<string, string> = {
  upload: '⬆️', download: '⬇️', copy: '📄', move: '➡️', delete: '🗑️',
}

export function TransfersPanel({ transfers, onClose, onClear }: {
  transfers: Transfer[]; onClose: () => void; onClear: () => void
}) {
  const active = transfers.filter((t) => t.state === 'active')

  return (
    <div className="transfers-panel">
      <div className="row" style={{ marginBottom: 10 }}>
        <strong style={{ fontSize: 14 }}>Transfers</strong>
        {active.length > 0 && <span className="badge accent">{active.length} active</span>}
        <span className="spacer" />
        <button className="btn sm ghost" onClick={onClear}>Clear</button>
        <button className="btn sm ghost" onClick={onClose} aria-label="Close">✕</button>
      </div>

      {transfers.length === 0 ? (
        <div className="hint" style={{ padding: '10px 0' }}>Nothing yet.</div>
      ) : transfers.map((t) => {
        const fraction = t.totalBytes && t.totalBytes > 0
          ? Math.min(1, t.transferredBytes / t.totalBytes) : null
        return (
          <div className="transfer-row" key={t.id}>
            <div className="row">
              <span>{GLYPH[t.direction] ?? '📦'}</span>
              <span className="truncate" style={{ flex: 1, fontSize: 13 }}>{t.fileName}</span>
              <span className="hint">
                {t.state === 'active'
                  ? (fraction !== null ? `${Math.round(fraction * 100)}%`
                    : bytes(t.transferredBytes))
                  : t.state === 'completed' ? '✓'
                    : t.state === 'failed' ? '✕' : t.state}
              </span>
            </div>

            {t.state === 'active' && (
              // No Content-Length means no percentage is knowable, so show an
              // indeterminate bar rather than a fake one.
              <div className={`progress ${fraction === null ? 'indeterminate' : ''}`}>
                <span style={{ width: `${(fraction ?? 0) * 100}%` }} />
              </div>
            )}

            <div className="hint" style={{ marginTop: 2 }}>
              {t.destinationLabel}
              {t.totalBytes ? ` · ${bytes(t.totalBytes)}` : ''}
            </div>
            {t.error && (
              <div className="hint" style={{ color: 'var(--danger)' }}>{t.error}</div>
            )}
          </div>
        )
      })}
    </div>
  )
}
