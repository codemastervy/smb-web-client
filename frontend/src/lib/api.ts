/** Typed client for the smb-web-client API. */

export interface FailureInfo {
  kind: string
  title: string
  message: string
  target: string
  underlying: string | null
  suggests_editing_connection: boolean
  suggests_recovery_app: boolean
}

export class ApiError extends Error {
  constructor(public status: number, message: string,
              public failure?: FailureInfo) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: init?.body instanceof FormData ? undefined
      : { 'Content-Type': 'application/json' },
    ...init,
  })

  if (res.status === 401) {
    // Distinguish "you are not signed in to this web app" from "the SMB server
    // rejected your credentials" -- both are 401 but they mean opposite things.
    let body: any = null
    try { body = await res.json() } catch { /* no body */ }
    if (body?.detail && typeof body.detail === 'object') {
      throw new ApiError(401, body.detail.message, body.detail as FailureInfo)
    }
    window.dispatchEvent(new CustomEvent('smbweb:unauthenticated'))
    throw new ApiError(401, 'Not signed in')
  }

  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    let failure: FailureInfo | undefined
    try {
      const body = await res.json()
      if (body?.detail && typeof body.detail === 'object') {
        failure = body.detail as FailureInfo
        message = failure.message
      } else if (typeof body?.detail === 'string') {
        message = body.detail
      }
    } catch { /* body was not JSON */ }
    throw new ApiError(res.status, message, failure)
  }

  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const get = <T,>(p: string) => request<T>(p)
const post = <T,>(p: string, body?: unknown) => request<T>(p, {
  method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const patch = <T,>(p: string, body: unknown) =>
  request<T>(p, { method: 'PATCH', body: JSON.stringify(body) })
const put = <T,>(p: string, body: unknown) =>
  request<T>(p, { method: 'PUT', body: JSON.stringify(body) })
const del = <T,>(p: string) => request<T>(p, { method: 'DELETE' })

// ---------------------------------------------------------------- types

export interface ServerStatus {
  state: 'idle' | 'connected' | 'connecting' | 'failed'
  connectedAt?: number
  username?: string
  failure?: FailureInfo
}

export interface Server {
  id: string
  name: string
  host: string
  port: number
  shareName: string
  username: string
  domain: string
  saveCredentials: boolean
  hasSavedPassword: boolean
  passwordRecoverable: boolean
  subtitle: string
  createdAt: number | null
  status?: ServerStatus
}

export interface Entry {
  name: string
  path: string
  isDir: boolean
  size: number | null
  modified: number
  created: number | null
  hidden: boolean
  readOnly: boolean
}

export interface Listing {
  serverId: string
  path: string
  entries: Entry[]
  truncated?: boolean
  query?: string
}

export interface Transfer {
  id: string
  fileName: string
  direction: 'upload' | 'download' | 'copy' | 'move' | 'delete'
  destinationLabel: string
  transferredBytes: number
  totalBytes: number | null
  state: 'waiting' | 'active' | 'completed' | 'cancelled' | 'failed'
  startedAt: number
  finishedAt: number | null
  error: string | null
}

export interface Preferences {
  defaultViewMode: 'list' | 'grid'
  defaultSortField: 'name' | 'dateModified' | 'size' | 'type'
  defaultSortDirection: 'ascending' | 'descending'
  recursiveSearch: boolean
  showHiddenFiles: boolean
  recoveryLinkName: string
  recoveryLinkUrl: string
}

export interface ServerInput {
  name: string; host: string; port: number; shareName: string
  username: string; password: string; domain: string; saveCredentials: boolean
}

// ---------------------------------------------------------------- endpoints

export const api = {
  authStatus: () => get<{ authRequired: boolean; configured: boolean; authenticated: boolean }>('/api/auth/status'),
  login: (password: string) => post<{ authenticated: boolean }>('/api/auth/login', { password }),
  logout: () => post('/api/auth/logout'),
  health: () => get<{ status: string; role: string; credentialEncryption: boolean }>('/api/health'),

  servers: () => get<{ servers: Server[] }>('/api/servers'),
  createServer: (body: ServerInput) => post<Server>('/api/servers', body),
  updateServer: (id: string, body: Partial<ServerInput>) => patch<Server>(`/api/servers/${id}`, body),
  deleteServer: (id: string) => del(`/api/servers/${id}`),
  connect: (id: string, password?: string) =>
    post<{ serverId: string; status: ServerStatus }>(`/api/servers/${id}/connect`, { password: password ?? null }),
  disconnect: (id: string) => post<{ status: ServerStatus }>(`/api/servers/${id}/disconnect`),
  testConnection: (body: ServerInput) =>
    post<{ ok: boolean; failure?: FailureInfo }>('/api/servers/test', body),

  list: (serverId: string, path: string, showHidden = false) =>
    get<Listing>(`/api/files/list?serverId=${encodeURIComponent(serverId)}&path=${encodeURIComponent(path)}&showHidden=${showHidden}`),
  search: (serverId: string, path: string, q: string, recursive = false, showHidden = false) =>
    get<Listing>(`/api/files/search?serverId=${encodeURIComponent(serverId)}&path=${encodeURIComponent(path)}&q=${encodeURIComponent(q)}&recursive=${recursive}&showHidden=${showHidden}`),
  mkdir: (serverId: string, parent: string, name: string) =>
    post<Entry>('/api/files/mkdir', { serverId, parent, name }),
  rename: (serverId: string, path: string, newName: string) =>
    post<Entry>('/api/files/rename', { serverId, path, newName }),
  copy: (serverId: string, sources: string[], destination: string) =>
    post<{ copied: unknown[]; failed: Array<{ source: string; error: string }> }>('/api/files/copy', { serverId, sources, destination }),
  move: (serverId: string, sources: string[], destination: string) =>
    post<{ moved: unknown[]; failed: Array<{ source: string; error: string }> }>('/api/files/move', { serverId, sources, destination }),
  remove: (serverId: string, paths: string[]) =>
    post<{ deleted: string[]; failed: Array<{ path: string; error: string }> }>('/api/files/delete', { serverId, paths }),
  downloadUrl: (serverId: string, path: string, inline = false) =>
    `/api/files/download?serverId=${encodeURIComponent(serverId)}&path=${encodeURIComponent(path)}&inline=${inline}`,

  transfers: () => get<{ transfers: Transfer[] }>('/api/transfers'),
  clearTransfers: () => post<{ cleared: number }>('/api/transfers/clear'),

  preferences: () => get<Preferences>('/api/preferences'),
  savePreferences: (p: Preferences) => put<Preferences>('/api/preferences', p),
}

/** Upload with real progress, which fetch() cannot report. */
export function uploadFile(
  serverId: string, path: string, file: File,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<{ name: string; path: string; size: number }> {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('serverId', serverId)
    form.append('path', path)
    form.append('file', file)

    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/files/upload')
    xhr.withCredentials = true
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)) }
        catch { reject(new ApiError(xhr.status, 'malformed server response')) }
      } else {
        let message = `${xhr.status}`
        let failure: FailureInfo | undefined
        try {
          const body = JSON.parse(xhr.responseText)
          if (body?.detail && typeof body.detail === 'object') {
            failure = body.detail; message = failure!.message
          } else if (typeof body?.detail === 'string') { message = body.detail }
        } catch { /* not JSON */ }
        reject(new ApiError(xhr.status, message, failure))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'network error during upload'))
    xhr.onabort = () => reject(new ApiError(0, 'upload cancelled'))
    signal?.addEventListener('abort', () => xhr.abort())
    xhr.send(form)
  })
}
