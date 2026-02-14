import { createContext, useEffect, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"

/** Context providing the popup document body so Radix portals (Popover, Dialog, etc.) render in the correct document. */
export const PopoutContainerContext = createContext<HTMLElement | undefined>(undefined)

interface PopoutWindowProps {
  popupWindow: Window
  title: string
  onClose: () => void
  children: ReactNode
}

export default function PopoutWindow({ popupWindow, title, onClose, children }: PopoutWindowProps) {
  const [popoutRoot, setPopoutRoot] = useState<HTMLElement | null>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    const popup = popupWindow
    if (popup.closed) return

    const popupDoc = popup.document
    const parentHead = document.head

    // Idempotent setup — skip if already initialized (StrictMode re-mount)
    let root = popupDoc.getElementById("popout-root") as HTMLElement | null
    if (!root) {
      popupDoc.title = title

      // Copy stylesheets from parent into popup head
      for (const node of Array.from(parentHead.querySelectorAll('style, link[rel="stylesheet"]'))) {
        popupDoc.head.appendChild(node.cloneNode(true))
      }

      // Copy dark mode class from parent <html>
      popupDoc.documentElement.className = document.documentElement.className

      // Create root container in popup body
      root = popupDoc.createElement("div")
      root.id = "popout-root"
      root.className = "bg-background text-foreground min-h-screen"
      popupDoc.body.appendChild(root)
    }
    setPopoutRoot(root)

    // Watch parent <head> for dynamically injected styles (CodeMirror, HMR)
    const headObserver = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const added of Array.from(mutation.addedNodes)) {
          if (added instanceof HTMLStyleElement || (added instanceof HTMLLinkElement && added.rel === "stylesheet")) {
            popupDoc.head.appendChild(added.cloneNode(true))
          }
        }
      }
    })
    headObserver.observe(parentHead, { childList: true })

    // Watch parent <html> class for dark mode toggles
    const htmlObserver = new MutationObserver(() => {
      popupDoc.documentElement.className = document.documentElement.className
    })
    htmlObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] })

    // Notify parent when user closes popup via browser X button
    const handleUnload = () => onCloseRef.current()
    popup.addEventListener("beforeunload", handleUnload)

    // Close popup if parent page navigates away
    const handlePageHide = () => { if (!popup.closed) popup.close() }
    window.addEventListener("pagehide", handlePageHide)

    return () => {
      headObserver.disconnect()
      htmlObserver.disconnect()
      popup.removeEventListener("beforeunload", handleUnload)
      window.removeEventListener("pagehide", handlePageHide)
      // NO popup.close() here — parent manages popup lifecycle imperatively
    }
  }, [popupWindow, title])

  if (!popoutRoot) return null

  return createPortal(
    <PopoutContainerContext.Provider value={popoutRoot}>
      {children}
    </PopoutContainerContext.Provider>,
    popoutRoot,
  )
}
