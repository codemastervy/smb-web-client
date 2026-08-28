export function bytes(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return '—'
  if (value === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const exp = Math.min(Math.floor(Math.log(Math.abs(value)) / Math.log(1024)), units.length - 1)
  return `${(value / Math.pow(1024, exp)).toFixed(exp === 0 ? 0 : digits)} ${units[exp]}`
}

export function fileDate(epoch: number): string {
  if (!epoch) return '—'
  const date = new Date(epoch * 1000)
  const sameYear = date.getFullYear() === new Date().getFullYear()
  return date.toLocaleDateString(undefined, {
    month: 'short', day: 'numeric',
    year: sameYear ? undefined : 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export function iconFor(entry: { isDir: boolean; name: string }): string {
  if (entry.isDir) return '📁'
  const ext = entry.name.split('.').pop()?.toLowerCase() ?? ''
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'heic', 'bmp', 'svg', 'avif'].includes(ext)) return '🖼️'
  if (['mp4', 'mkv', 'mov', 'avi', 'webm', 'm4v'].includes(ext)) return '🎬'
  if (['mp3', 'flac', 'wav', 'aac', 'm4a', 'ogg'].includes(ext)) return '🎵'
  if (ext === 'pdf') return '📕'
  if (['zip', 'tar', 'gz', 'bz2', 'xz', '7z', 'rar'].includes(ext)) return '🗜️'
  if (['txt', 'md', 'log', 'json', 'yml', 'yaml', 'conf', 'ini', 'csv'].includes(ext)) return '📄'
  if (['iso', 'img', 'dmg'].includes(ext)) return '💿'
  return '📦'
}

export function previewKind(name: string): 'image' | 'video' | 'audio' | 'pdf' | 'text' | null {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', 'avif'].includes(ext)) return 'image'
  if (['mp4', 'webm', 'mov', 'm4v'].includes(ext)) return 'video'
  if (['mp3', 'wav', 'ogg', 'flac', 'm4a'].includes(ext)) return 'audio'
  if (ext === 'pdf') return 'pdf'
  if (['txt', 'md', 'log', 'json', 'yml', 'yaml', 'conf', 'ini', 'csv', 'sh', 'py', 'js', 'ts'].includes(ext)) return 'text'
  return null
}

/** Emoji standing in for the native app's SF Symbol on the failure screen. */
export function failureGlyph(kind: string): string {
  switch (kind) {
    case 'timed_out':
    case 'host_unreachable': return '📡'
    case 'connection_refused': return '⛔'
    case 'authentication_failed': return '🔑'
    case 'share_not_found':
    case 'not_found': return '🔍'
    case 'permission_denied': return '🔒'
    case 'out_of_space': return '💾'
    case 'invalid_configuration': return '⚙️'
    default: return '⚠️'
  }
}
