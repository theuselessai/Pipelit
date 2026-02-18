import { useSyncExternalStore, useCallback, useMemo } from "react"
import type { Extension } from "@codemirror/state"
import { oneDark } from "@codemirror/theme-one-dark"
import { vscodeDark, vscodeLight } from "@uiw/codemirror-theme-vscode"
import { abcdef } from "@fsegurai/codemirror-theme-abcdef"
import { abyss } from "@fsegurai/codemirror-theme-abyss"
import { gruvboxDark } from "@fsegurai/codemirror-theme-gruvbox-dark"
import { gruvboxLight } from "@fsegurai/codemirror-theme-gruvbox-light"
import { monokai } from "@fsegurai/codemirror-theme-monokai"
import { githubDark } from "@fsegurai/codemirror-theme-github-dark"
import { githubLight } from "@fsegurai/codemirror-theme-github-light"
import { catppuccinMocha } from "@fsegurai/codemirror-theme-catppuccin-mocha"
import { tokyoNightStorm } from "@fsegurai/codemirror-theme-tokyo-night-storm"

export const EDITOR_THEMES: Record<string, { label: string; extension: Extension }> = {
  oneDark: { label: "One Dark", extension: oneDark },
  vscodeDark: { label: "VS Code Dark", extension: vscodeDark },
  vscodeLight: { label: "VS Code Light", extension: vscodeLight },
  abcdef: { label: "ABCDEF", extension: abcdef },
  abyss: { label: "Abyss", extension: abyss },
  gruvboxDark: { label: "Gruvbox Dark", extension: gruvboxDark },
  gruvboxLight: { label: "Gruvbox Light", extension: gruvboxLight },
  monokai: { label: "Monokai", extension: monokai },
  githubDark: { label: "GitHub Dark", extension: githubDark },
  githubLight: { label: "GitHub Light", extension: githubLight },
  catppuccinMocha: { label: "Catppuccin Mocha", extension: catppuccinMocha },
  tokyoNightStorm: { label: "Tokyo Night Storm", extension: tokyoNightStorm },
}

export type EditorThemeKey = keyof typeof EDITOR_THEMES

const STORAGE_KEY = "editorTheme"

// Shared external store so all useEditorTheme() instances stay in sync
let currentTheme: EditorThemeKey = (() => {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored && stored in EDITOR_THEMES) return stored as EditorThemeKey
  return "oneDark"
})()

const listeners = new Set<() => void>()

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function getSnapshot(): EditorThemeKey {
  return currentTheme
}

function setThemeStore(key: EditorThemeKey) {
  localStorage.setItem(STORAGE_KEY, key)
  currentTheme = key
  listeners.forEach((l) => l())
}

export function useEditorTheme() {
  const editorTheme = useSyncExternalStore(subscribe, getSnapshot)

  const setEditorTheme = useCallback((key: EditorThemeKey) => {
    setThemeStore(key)
  }, [])

  const editorThemeExtension = useMemo(() => {
    return EDITOR_THEMES[editorTheme]?.extension ?? oneDark
  }, [editorTheme])

  return { editorTheme, setEditorTheme, editorThemeExtension }
}
