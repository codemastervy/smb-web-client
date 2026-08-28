import { useState } from 'react'
import { FailureInfo } from '../lib/api'
import { failureGlyph } from '../lib/format'

interface Props {
  failure: FailureInfo
  serverId: string | null
  recoveryLink: { name: string; url: string } | null
  onEditConnection: () => void
  onRetry: () => Promise<void>
  onOpenSettings: () => void
  onDismiss: () => void
}

/**
 * Full-screen failure modal, ported from the native app's
 * `ConnectionFailureView`.
 *
 * Button order follows what is most likely to fix *this* failure: the backend
 * reports whether editing the connection or opening a VPN/tunnel is the
 * plausible remedy, and the prominent action changes accordingly. A rejected
 * password leads with Edit Connection; a timeout leads with the recovery link;
 * Retry takes the prominent slot only when neither applies.
 */
export function FailureScreen({
  failure, serverId, recoveryLink,
  onEditConnection, onRetry, onOpenSettings, onDismiss,
}: Props) {
  const [retrying, setRetrying] = useState(false)

  const hasRecovery = !!recoveryLink?.url
  const recoveryIsProminent = failure.suggests_recovery_app && hasRecovery
  const editIsProminent = !!serverId && failure.suggests_editing_connection
  // Retry only claims the prominent slot when nothing more specific has.
  const retryIsProminent = !recoveryIsProminent && !editIsProminent

  function openRecovery() {
    if (!recoveryLink?.url) return
    // A browser cannot launch an arbitrary app the way the native app could
    // with a URL scheme. Opening in a new tab is the honest web equivalent --
    // see the README's note on this platform difference.
    window.open(recoveryLink.url, '_blank', 'noopener,noreferrer')
  }

  return (
    <div className="failure-screen" data-testid="failureModal">
      <div className="failure-card">
        <div className="failure-glyph" aria-hidden="true">
          {failureGlyph(failure.kind)}
        </div>
        <h2>{failure.title}</h2>
        <p>{failure.message}</p>

        {failure.underlying && (
          <details className="tech">
            <summary>Technical details</summary>
            <pre>{failure.underlying}</pre>
          </details>
        )}

        <div className="failure-actions">
          {recoveryIsProminent && (
            <button className="btn primary" onClick={openRecovery}
                    data-testid="failureModal.recoveryApp">
              ↗ Open {recoveryLink!.name || 'Recovery Link'}
            </button>
          )}

          {editIsProminent && (
            <button className="btn primary" onClick={onEditConnection}
                    data-testid="failureModal.editConnection">
              ✏️ Edit Connection
            </button>
          )}

          <button className={`btn ${retryIsProminent ? 'primary' : ''}`}
                  disabled={retrying}
                  data-testid="failureModal.retry"
                  onClick={async () => {
                    setRetrying(true)
                    // Deliberately no dismiss here: the parent clears the
                    // failure on success and replaces it on a fresh failure.
                    // Dismissing would swallow the new failure and leave an
                    // empty browser with no explanation.
                    try { await onRetry() } finally { setRetrying(false) }
                  }}>
            {retrying ? <span className="spin" /> : '↻ Retry'}
          </button>

          {!!serverId && !editIsProminent && (
            <button className="btn" onClick={onEditConnection}
                    data-testid="failureModal.editConnection">
              ✏️ Edit Connection
            </button>
          )}

          {!recoveryIsProminent && hasRecovery && (
            <button className="btn" onClick={openRecovery}
                    data-testid="failureModal.recoveryApp">
              ↗ Open {recoveryLink!.name || 'Recovery Link'}
            </button>
          )}

          <button className="btn" onClick={onOpenSettings}
                  data-testid="failureModal.openSettings">
            ⚙️ Open Settings
          </button>

          <button className="btn ghost" onClick={onDismiss}
                  data-testid="failureModal.dismiss"
                  style={{ marginTop: 2 }}>
            Dismiss
          </button>
        </div>
      </div>
    </div>
  )
}
