import React, { Fragment, ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'

export interface MenuItem {
  label: string
  icon?: string
  danger?: boolean
  separatorBefore?: boolean
  disabled?: boolean
  onSelect: () => void
}

export function ContextMenu({ x, y, items, onClose }: {
  x: number; y: number; items: MenuItem[]; onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x, y })

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    // Keep it on screen -- a long-press near the bottom of a phone is the
    // common case, and a menu that opens off-screen is unusable.
    setPos({
      x: Math.max(8, Math.min(x, window.innerWidth - r.width - 8)),
      y: Math.max(8, Math.min(y, window.innerHeight - r.height - 8)),
    })
  }, [x, y])

  useEffect(() => {
    const dismiss = () => onClose()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('mousedown', dismiss, true)
    document.addEventListener('scroll', dismiss, true)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', dismiss, true)
      document.removeEventListener('scroll', dismiss, true)
      document.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  return (
    <div className="context-menu" ref={ref} style={{ left: pos.x, top: pos.y }}
         onMouseDown={(e) => e.stopPropagation()}>
      {items.map((item, i) => (
        <Fragment key={i}>
          {item.separatorBefore && i > 0 && <hr />}
          <button className={item.danger ? 'danger' : ''} disabled={item.disabled}
                  onClick={() => { item.onSelect(); onClose() }}>
            <span style={{ width: 17 }}>{item.icon}</span>{item.label}
          </button>
        </Fragment>
      ))}
    </div>
  )
}

/** Right-click on a pointer device, long-press on a touch device. */
export function useLongPress(onTrigger: (x: number, y: number) => void) {
  const timer = useRef<number>()
  const origin = useRef({ x: 0, y: 0 })
  const cancel = () => window.clearTimeout(timer.current)

  return {
    onContextMenu: (e: React.MouseEvent) => {
      e.preventDefault()
      onTrigger(e.clientX, e.clientY)
    },
    onTouchStart: (e: React.TouchEvent) => {
      const t = e.touches[0]
      origin.current = { x: t.clientX, y: t.clientY }
      timer.current = window.setTimeout(() => onTrigger(t.clientX, t.clientY), 480)
    },
    onTouchMove: (e: React.TouchEvent) => {
      const t = e.touches[0]
      // A scroll must not become a long-press.
      if (Math.hypot(t.clientX - origin.current.x,
                     t.clientY - origin.current.y) > 10) cancel()
    },
    onTouchEnd: cancel,
    onTouchCancel: cancel,
  }
}

export function Wrap({ children }: { children: ReactNode }) { return <>{children}</> }
