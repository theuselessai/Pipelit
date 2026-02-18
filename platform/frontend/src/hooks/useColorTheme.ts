import { useSyncExternalStore, useCallback, useEffect } from "react"
import { COLOR_THEMES, type ColorThemeKey } from "@/lib/colorThemes"

const STORAGE_KEY = "colorTheme"

// NOTE: This app is strictly CSR (Vite SPA) — no SSR. Module-level
// localStorage/document access is safe and matches useEditorTheme.ts.

// All CSS variable names we override — used for cleanup
const OVERRIDE_VARS = [
  "primary",
  "primary-foreground",
  "secondary",
  "secondary-foreground",
  "chart-1",
  "chart-2",
  "chart-3",
  "chart-4",
  "chart-5",
  "sidebar-primary",
  "sidebar-primary-foreground",
]

function applyColorTheme(themeKey: ColorThemeKey) {
  const el = document.documentElement
  const isDark = el.classList.contains("dark")
  const theme = COLOR_THEMES[themeKey]
  const vars = isDark ? theme.dark : theme.light

  // Clear all previous overrides
  for (const name of OVERRIDE_VARS) {
    el.style.removeProperty(`--color-${name}`)
    el.style.removeProperty(`--${name}`)
  }

  // Apply new overrides (skip for "default" which has empty maps)
  for (const [name, value] of Object.entries(vars)) {
    el.style.setProperty(`--color-${name}`, value)
    el.style.setProperty(`--${name}`, value)
  }
}

// Shared external store so all useColorTheme() instances stay in sync
let currentTheme: ColorThemeKey = (() => {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored && stored in COLOR_THEMES) return stored as ColorThemeKey
  return "yellow"
})()

const listeners = new Set<() => void>()

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function getSnapshot(): ColorThemeKey {
  return currentTheme
}

function setThemeStore(key: ColorThemeKey) {
  localStorage.setItem(STORAGE_KEY, key)
  currentTheme = key
  applyColorTheme(key)
  listeners.forEach((l) => l())
}

export function useColorTheme() {
  const colorTheme = useSyncExternalStore(subscribe, getSnapshot)

  const setColorTheme = useCallback((key: ColorThemeKey) => {
    setThemeStore(key)
  }, [])

  // Apply on mount
  useEffect(() => {
    applyColorTheme(currentTheme)
  }, [])

  // Re-apply when light/dark mode changes (watch for .dark class on <html>)
  useEffect(() => {
    const observer = new MutationObserver(() => {
      applyColorTheme(colorTheme)
    })
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    })
    return () => observer.disconnect()
  }, [colorTheme])

  return { colorTheme, setColorTheme }
}
