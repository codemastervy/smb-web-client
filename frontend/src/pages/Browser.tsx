import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api, ApiError, Entry, FailureInfo, Listing, Preferences, Server, uploadFile,
} from '../lib/api'
import { bytes, fileDate, iconFor, previewKind } from '../lib/format'
import { ContextMenu, MenuItem, useLongPress } from '../components/ContextMenu'
import { Modal } from '../components/Modal'
import { Preview } from '../components/Preview'
import { useToast } from '../components/Toast'

interface Props {
  server: Server
  prefs: Preferences
  onFailure: (failure: FailureInfo, serverId: string) => void
  onMenu: () => void
  onOpenTransfers: () => void
  refreshTransfers: () => void
}

interface Upload { id: number; name: string; progress: number }

export function Browser({ server, prefs, onFailure, onMenu, onOpenTransfers,
                          refreshTransfers }: Props) {
  const [path, setPath] = useState('/')
  const [listing, setListing] = useState<Listing | null>(null)
  const [loading, setLoading] = useState(false)

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [view, setView] = useState(prefs.defaultViewMode)
  const [sortField, setSortField] = useState(prefs.defaultSortField)
  const [ascending, setAscending] = useState(prefs.defaultSortDirection === 'ascending')
  const [showHidden, setShowHidden] = useState(prefs.showHiddenFiles)
  const [recursive, setRecursive] = useState(prefs.recursiveSearch)

  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)

  const [menu, setMenu] = useState<{ x: number; y: number; entry: Entry | null } | null>(null)
  const [renaming, setRenaming] = useState<Entry | null>(null)
  const [newFolder, setNewFolder] = useState(false)
  const [preview, setPreview] = useState<Entry | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string[] | null>(null)
  const [clipboard, setClipboard] = useState<{ mode: 'copy' | 'cut'; paths: string[] } | null>(null)
  const [uploads, setUploads] = useState<Upload[]>([])

  const fileInput = useRef<HTMLInputElement>(null)
  const toast = useToast()

  // Reset to the share root whenever the selected server changes.
  useEffect(() => { setPath('/'); setQuery(''); setSelected(new Set()) }, [server.id])
  useEffect(() => {
    setView(prefs.defaultViewMode)
    setSortField(prefs.defaultSortField)
    setAscending(prefs.defaultSortDirection === 'ascending')
    setShowHidden(prefs.showHiddenFiles)
    setRecursive(prefs.recursiveSearch)
  }, [prefs])

  const handle = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.failure) {
      onFailure(e.failure, server.id)
      return true
    }
    toast(e instanceof Error ? e.message : 'Something went wrong', 'error')
    return false
  }, [onFailure, server.id, toast])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setListing(await api.list(server.id, path, showHidden))
      setSearching(false)
    } catch (e) {
      setListing(null)
      handle(e)
    } finally { setLoading(false) }
  }, [server.id, path, showHidden, handle])

  useEffect(() => { void load() }, [load])

  // Debounced search, so typing does not fire a tree walk per keystroke.
  useEffect(() => {
    if (!query.trim()) { if (searching) void load(); return }
    const timer = window.setTimeout(async () => {
      setLoading(true); setSearching(true)
      try {
        setListing(await api.search(server.id, path, query, recursive, showHidden))
      } catch (e) { handle(e) } finally { setLoading(false) }
    }, 340)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, recursive, server.id, path, showHidden])

  const entries = useMemo(() => {
    const list = [...(listing?.entries ?? [])]
    const dir = ascending ? 1 : -1
    list.sort((a, b) => {
      // Directories always lead, whatever the sort — same rule as the native app.
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1
      switch (sortField) {
        case 'size': return dir * ((a.size ?? 0) - (b.size ?? 0))
        case 'dateModified': return dir * (a.modified - b.modified)
        case 'type': {
          const ax = a.name.split('.').pop() ?? ''
          const bx = b.name.split('.').pop() ?? ''
          return ax === bx
            ? a.name.localeCompare(b.name, undefined, { numeric: true })
            : dir * ax.localeCompare(bx)
        }
        default:
          return dir * a.name.localeCompare(b.name, undefined, { numeric: true })
      }
    })
    return list
  }, [listing, sortField, ascending])

  function toggleSelect(p: string, additive: boolean) {
    setSelected((cur) => {
      const next = additive ? new Set(cur) : new Set<string>()
      if (cur.has(p) && additive) next.delete(p)
      else next.add(p)
      return next
    })
  }

  function open(entry: Entry) {
    if (entry.isDir) { setPath(entry.path); setQuery(''); setSelected(new Set()); return }
    if (previewKind(entry.name)) { setPreview(entry); return }
    window.location.href = api.downloadUrl(server.id, entry.path)
  }

  // ------------------------------------------------------------ operations

  async function doDelete(paths: string[]) {
    try {
      const r = await api.remove(server.id, paths)
      if (r.failed.length) toast(`${r.failed.length} item(s) failed: ${r.failed[0].error}`, 'error')
      if (r.deleted.length) toast(`Deleted ${r.deleted.length} item(s)`, 'ok')
      setSelected(new Set()); void load()
    } catch (e) { handle(e) }
  }

  async function paste() {
    if (!clipboard) return
    try {
      const r = clipboard.mode === 'copy'
        ? await api.copy(server.id, clipboard.paths, path)
        : await api.move(server.id, clipboard.paths, path)
      const failed = r.failed ?? []
      if (failed.length) toast(`${failed.length} item(s) failed: ${failed[0].error}`, 'error')
      else toast(clipboard.mode === 'copy' ? 'Copied' : 'Moved', 'ok')
      if (clipboard.mode === 'cut') setClipboard(null)
      void load(); refreshTransfers()
    } catch (e) { handle(e) }
  }

  async function handleFiles(files: FileList | null) {
    if (!files?.length) return
    onOpenTransfers()
    for (const file of Array.from(files)) {
      const id = Date.now() + Math.random()
      setUploads((u) => [...u, { id, name: file.name, progress: 0 }])
      try {
        await uploadFile(server.id, path, file, (fraction) => {
          setUploads((u) => u.map((x) => x.id === id ? { ...x, progress: fraction } : x))
          refreshTransfers()
        })
      } catch (e) {
        handle(e)
      } finally {
        setUploads((u) => u.filter((x) => x.id !== id))
      }
    }
    void load(); refreshTransfers()
  }

  // ------------------------------------------------------------ menu

  function menuItems(entry: Entry | null): MenuItem[] {
    if (!entry) {
      return [
        { label: 'New folder', icon: '📁', onSelect: () => setNewFolder(true) },
        { label: 'Upload files', icon: '⬆️', onSelect: () => fileInput.current?.click() },
        {
          label: clipboard ? `Paste ${clipboard.paths.length} item(s)` : 'Paste',
          icon: '📋', disabled: !clipboard, separatorBefore: true,
          onSelect: () => void paste(),
        },
        { label: 'Refresh', icon: '🔄', onSelect: () => void load() },
      ]
    }

    const targets = selected.has(entry.path) ? [...selected] : [entry.path]
    const many = targets.length > 1
    const items: MenuItem[] = []

    if (entry.isDir) {
      items.push({ label: 'Open', icon: '📂', onSelect: () => open(entry) })
    } else {
      items.push({
        label: 'Download', icon: '⬇️',
        onSelect: () => { window.location.href = api.downloadUrl(server.id, entry.path) },
      })
      if (previewKind(entry.name)) {
        items.push({ label: 'Preview', icon: '👁️', onSelect: () => setPreview(entry) })
      }
    }

    items.push(
      { label: 'Rename', icon: '✏️', separatorBefore: true, disabled: many,
        onSelect: () => setRenaming(entry) },
      { label: `Copy${many ? ` (${targets.length})` : ''}`, icon: '📄',
        onSelect: () => { setClipboard({ mode: 'copy', paths: targets }); toast('Ready to paste') } },
      { label: `Cut${many ? ` (${targets.length})` : ''}`, icon: '✂️',
        onSelect: () => { setClipboard({ mode: 'cut', paths: targets }); toast('Ready to move') } },
      { label: `Delete${many ? ` (${targets.length})` : ''}`, icon: '🗑️',
        danger: true, separatorBefore: true,
        onSelect: () => setConfirmDelete(targets) },
    )
    return items
  }

  const crumbs = path.split('/').filter(Boolean)

  return (
    <>
      <header className="topbar">
        <button className="btn ghost icon menu-btn" onClick={onMenu} aria-label="Open menu">☰</button>
        <div className="crumbs">
          <button className="crumb" onClick={() => setPath('/')}>{server.shareName || server.name}</button>
          {crumbs.map((part, i) => {
            const target = '/' + crumbs.slice(0, i + 1).join('/')
            const last = i === crumbs.length - 1
            return (
              <span key={target} className="row" style={{ gap: 2 }}>
                <span className="crumb-sep">/</span>
                <button className={`crumb ${last ? 'current' : ''}`}
                        onClick={() => setPath(target)}>{part}</button>
              </span>
            )
          })}
        </div>
        <span className="spacer" />
        <button className={`btn sm ${view === 'list' ? 'primary' : ''}`}
                onClick={() => setView('list')} aria-label="List view">☰</button>
        <button className={`btn sm ${view === 'grid' ? 'primary' : ''}`}
                onClick={() => setView('grid')} aria-label="Grid view">▦</button>
      </header>

      <div className="content"
           onContextMenu={(e) => {
             if ((e.target as HTMLElement).closest('.file-row, .file-tile')) return
             e.preventDefault()
             setMenu({ x: e.clientX, y: e.clientY, entry: null })
           }}>

        <div className="row wrap" style={{ marginBottom: 13 }}>
          <input className="input" style={{ flex: '1 1 180px', minWidth: 150 }}
                 placeholder={recursive ? 'Search subfolders…' : 'Search this folder…'}
                 value={query} onChange={(e) => setQuery(e.target.value)} />
          <button className={`btn sm ${recursive ? 'primary' : ''}`}
                  onClick={() => setRecursive((r) => !r)}
                  title="Search subfolders">⌘</button>
          <select className="select" style={{ width: 'auto' }} value={sortField}
                  onChange={(e) => setSortField(e.target.value as typeof sortField)}>
            <option value="name">Name</option>
            <option value="dateModified">Date</option>
            <option value="size">Size</option>
            <option value="type">Type</option>
          </select>
          <button className="btn sm" onClick={() => setAscending((a) => !a)}>
            {ascending ? '↑' : '↓'}
          </button>
          <button className="btn sm" onClick={() => setShowHidden((h) => !h)}
                  title="Toggle hidden files">{showHidden ? '👁️' : '🙈'}</button>
          <button className="btn sm" onClick={() => setNewFolder(true)}>New folder</button>
          <button className="btn sm primary" onClick={() => fileInput.current?.click()}>Upload</button>
          <input ref={fileInput} type="file" multiple hidden
                 onChange={(e) => { void handleFiles(e.target.files); e.target.value = '' }} />
        </div>

        {uploads.length > 0 && (
          <div className="notice accent">
            Uploading {uploads.length} file(s) —{' '}
            {Math.round((uploads.reduce((s, u) => s + u.progress, 0) / uploads.length) * 100)}%
          </div>
        )}

        {selected.size > 0 && (
          <div className="selection-bar">
            <strong>{selected.size} selected</strong>
            <span className="spacer" />
            <button className="btn sm" onClick={() => { setClipboard({ mode: 'copy', paths: [...selected] }); toast('Ready to paste') }}>Copy</button>
            <button className="btn sm" onClick={() => { setClipboard({ mode: 'cut', paths: [...selected] }); toast('Ready to move') }}>Cut</button>
            {clipboard && <button className="btn sm" onClick={() => void paste()}>Paste here</button>}
            <button className="btn sm danger" onClick={() => setConfirmDelete([...selected])}>Delete</button>
            <button className="btn sm ghost" onClick={() => setSelected(new Set())}>Clear</button>
          </div>
        )}

        {searching && listing?.truncated && (
          <div className="notice warn">
            Showing the first {listing.entries.length} matches — narrow the search.
          </div>
        )}

        {loading ? (
          <div className="empty"><span className="spin" /></div>
        ) : entries.length === 0 ? (
          <div className="empty">
            <span className="glyph">{searching ? '🔍' : '📂'}</span>
            {searching ? 'Nothing matched that search.' : 'This folder is empty.'}
          </div>
        ) : view === 'list' ? (
          <div className="glass file-list">
            {entries.map((entry) => (
              <Row key={entry.path} entry={entry} selected={selected.has(entry.path)}
                   onOpen={() => open(entry)}
                   onSelect={(additive) => toggleSelect(entry.path, additive)}
                   onMenu={(x, y) => setMenu({ x, y, entry })} />
            ))}
          </div>
        ) : (
          <div className="file-grid">
            {entries.map((entry) => (
              <Tile key={entry.path} entry={entry} selected={selected.has(entry.path)}
                    onOpen={() => open(entry)}
                    onSelect={(additive) => toggleSelect(entry.path, additive)}
                    onMenu={(x, y) => setMenu({ x, y, entry })} />
            ))}
          </div>
        )}
      </div>

      {menu && (
        <ContextMenu x={menu.x} y={menu.y} items={menuItems(menu.entry)}
                     onClose={() => setMenu(null)} />
      )}

      {newFolder && (
        <NamePrompt title="New folder" label="Folder name" initial="New folder"
                    confirm="Create" onClose={() => setNewFolder(false)}
                    onSubmit={async (name) => {
                      try { await api.mkdir(server.id, path, name); toast('Folder created', 'ok'); void load() }
                      catch (e) { handle(e) }
                      setNewFolder(false)
                    }} />
      )}

      {renaming && (
        <NamePrompt title="Rename" label="New name" initial={renaming.name}
                    confirm="Rename" onClose={() => setRenaming(null)}
                    onSubmit={async (name) => {
                      try { await api.rename(server.id, renaming.path, name); toast('Renamed', 'ok'); void load() }
                      catch (e) { handle(e) }
                      setRenaming(null)
                    }} />
      )}

      {confirmDelete && (
        <Modal title={`Delete ${confirmDelete.length} item${confirmDelete.length === 1 ? '' : 's'}?`}
               subtitle="This removes them from the server. It cannot be undone."
               onClose={() => setConfirmDelete(null)}
               actions={<>
                 <button className="btn" onClick={() => setConfirmDelete(null)}>Cancel</button>
                 <button className="btn danger" onClick={() => { void doDelete(confirmDelete); setConfirmDelete(null) }}>Delete</button>
               </>}>
          <ul className="mono" style={{ margin: 0, paddingLeft: 18, maxHeight: 200, overflow: 'auto' }}>
            {confirmDelete.slice(0, 20).map((p) => <li key={p}>{p}</li>)}
            {confirmDelete.length > 20 && <li>…and {confirmDelete.length - 20} more</li>}
          </ul>
        </Modal>
      )}

      {preview && (
        <Preview serverId={server.id} entry={preview} onClose={() => setPreview(null)} />
      )}
    </>
  )
}

// ------------------------------------------------------------------ pieces

function Row({ entry, selected, onOpen, onSelect, onMenu }: {
  entry: Entry; selected: boolean
  onOpen: () => void; onSelect: (additive: boolean) => void
  onMenu: (x: number, y: number) => void
}) {
  const press = useLongPress(onMenu)
  return (
    <div className={`file-row ${selected ? 'selected' : ''}`} {...press}
         onClick={(e) => onSelect(e.metaKey || e.ctrlKey || e.shiftKey)}
         onDoubleClick={onOpen}>
      <span style={{ fontSize: 17 }}>{iconFor(entry)}</span>
      <span className="name">
        <button onClick={(e) => { e.stopPropagation(); onOpen() }}>{entry.name}</button>
        {entry.readOnly && <span className="badge">read-only</span>}
      </span>
      <span className="size">{entry.isDir ? '—' : bytes(entry.size)}</span>
      <span className="date">{fileDate(entry.modified)}</span>
      <button className="btn ghost icon"
              onClick={(e) => { e.stopPropagation(); onMenu(e.clientX, e.clientY) }}
              aria-label={`Actions for ${entry.name}`}>⋯</button>
    </div>
  )
}

function Tile({ entry, selected, onOpen, onSelect, onMenu }: {
  entry: Entry; selected: boolean
  onOpen: () => void; onSelect: (additive: boolean) => void
  onMenu: (x: number, y: number) => void
}) {
  const press = useLongPress(onMenu)
  return (
    <div className={`file-tile ${selected ? 'selected' : ''}`} {...press}
         onClick={(e) => onSelect(e.metaKey || e.ctrlKey || e.shiftKey)}
         onDoubleClick={onOpen}>
      <div className="glyph">{iconFor(entry)}</div>
      <div className="label">{entry.name}</div>
    </div>
  )
}

function NamePrompt({ title, label, initial, confirm, onClose, onSubmit }: {
  title: string; label: string; initial: string; confirm: string
  onClose: () => void; onSubmit: (name: string) => void
}) {
  const [value, setValue] = useState(initial)
  return (
    <Modal title={title} onClose={onClose}
           actions={<>
             <button className="btn" onClick={onClose}>Cancel</button>
             <button className="btn primary" disabled={!value.trim()}
                     onClick={() => onSubmit(value.trim())}>{confirm}</button>
           </>}>
      <div className="field">
        <label htmlFor="np">{label}</label>
        <input id="np" className="input" value={value} autoFocus
               onChange={(e) => setValue(e.target.value)}
               onKeyDown={(e) => { if (e.key === 'Enter' && value.trim()) onSubmit(value.trim()) }} />
      </div>
    </Modal>
  )
}
