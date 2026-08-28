import { createContext, ReactNode, useCallback, useContext, useState } from 'react'

type Kind = 'info' | 'ok' | 'error'
interface Note { id: number; kind: Kind; text: string }

const Ctx = createContext<(text: string, kind?: Kind) => void>(() => {})
export const useToast = () => useContext(Ctx)

export function ToastHost({ children }: { children: ReactNode }) {
  const [notes, setNotes] = useState<Note[]>([])

  const push = useCallback((text: string, kind: Kind = 'info') => {
    const id = Date.now() + Math.random()
    setNotes((n) => [...n, { id, kind, text }])
    window.setTimeout(() => setNotes((n) => n.filter((x) => x.id !== id)),
      kind === 'error' ? 7000 : 3200)
  }, [])

  return (
    <Ctx.Provider value={push}>
      {children}
      <div style={{
        position: 'fixed', top: 14, left: '50%', transform: 'translateX(-50%)',
        zIndex: 300, display: 'flex', flexDirection: 'column', gap: 8,
        width: 'min(420px, calc(100vw - 28px))', pointerEvents: 'none',
      }}>
        {notes.map((n) => (
          <div key={n.id}
               className={`notice ${n.kind === 'error' ? 'danger' : n.kind === 'ok' ? 'accent' : ''}`}
               style={{
                 margin: 0, textAlign: 'center',
                 background: 'var(--glass-strong)',
                 backdropFilter: 'blur(30px) saturate(180%)',
                 WebkitBackdropFilter: 'blur(30px) saturate(180%)',
                 boxShadow: '0 12px 36px rgba(0,0,0,.42)',
               }}>
            {n.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
