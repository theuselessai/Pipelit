/* eslint-disable react-refresh/only-export-components */
import { useRef, useEffect, useCallback, useState } from "react"
import { EditorState } from "@codemirror/state"
import { EditorView, keymap, placeholder as cmPlaceholder, ViewUpdate } from "@codemirror/view"
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands"
import { syntaxHighlighting, defaultHighlightStyle, bracketMatching, indentOnInput } from "@codemirror/language"
import { lineNumbers, highlightActiveLineGutter, highlightActiveLine } from "@codemirror/view"
import { oneDark } from "@codemirror/theme-one-dark"
import { json } from "@codemirror/lang-json"
import { python } from "@codemirror/lang-python"
import { javascript } from "@codemirror/lang-javascript"
import { markdown } from "@codemirror/lang-markdown"
import { StreamLanguage } from "@codemirror/language"
import { shell } from "@codemirror/legacy-modes/mode/shell"
import { toml } from "@codemirror/legacy-modes/mode/toml"
import { useTheme } from "@/hooks/useTheme"
import { jinja2Highlight } from "@/lib/jinja2Highlight"

export type CodeMirrorLanguage = "json" | "python" | "javascript" | "bash" | "markdown" | "toml" | "text"

interface CodeMirrorEditorProps {
  value: string
  onChange?: (value: string) => void
  language?: CodeMirrorLanguage
  className?: string
  placeholder?: string
  readOnly?: boolean
}

function getLanguageExtension(lang: CodeMirrorLanguage) {
  switch (lang) {
    case "json": return json()
    case "python": return python()
    case "javascript": return javascript()
    case "bash": return StreamLanguage.define(shell)
    case "markdown": return markdown()
    case "toml": return StreamLanguage.define(toml)
    case "text": return []
  }
}

export default function CodeMirrorEditor({
  value,
  onChange,
  language = "text",
  className = "",
  placeholder = "",
  readOnly = false,
}: CodeMirrorEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const onChangeRef = useRef(onChange)
  const { resolvedTheme } = useTheme()
  const [, setMounted] = useState(false)

  // Keep onChange ref current without recreating the editor
  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  // Create editor
  useEffect(() => {
    if (!containerRef.current) return

    const isDark = resolvedTheme === "dark"

    const updateListener = EditorView.updateListener.of((update: ViewUpdate) => {
      if (update.docChanged && onChangeRef.current) {
        onChangeRef.current(update.state.doc.toString())
      }
    })

    const fillHeightTheme = EditorView.theme({
      "&": { height: "100%" },
      ".cm-scroller": { overflow: "auto" },
    })

    const extensions = [
      lineNumbers(),
      highlightActiveLineGutter(),
      highlightActiveLine(),
      history(),
      bracketMatching(),
      indentOnInput(),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      updateListener,
      getLanguageExtension(language),
      jinja2Highlight,
      EditorView.lineWrapping,
      fillHeightTheme,
      ...(isDark ? [oneDark] : []),
      ...(placeholder ? [cmPlaceholder(placeholder)] : []),
      ...(readOnly ? [EditorState.readOnly.of(true)] : []),
    ].flat()

    const state = EditorState.create({
      doc: value,
      extensions,
    })

    const view = new EditorView({
      state,
      parent: containerRef.current,
    })

    viewRef.current = view
    setMounted(true)

    return () => {
      view.destroy()
      viewRef.current = null
    }
    // Recreate editor when language or theme changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language, resolvedTheme, readOnly])

  // Sync external value changes without recreating editor
  useEffect(() => {
    const view = viewRef.current
    if (!view) return
    const currentValue = view.state.doc.toString()
    if (currentValue !== value) {
      view.dispatch({
        changes: { from: 0, to: currentValue.length, insert: value },
      })
    }
  }, [value])

  // Expose the view via a callback ref for parent components (e.g., insert at cursor)
  const getView = useCallback(() => viewRef.current, [])

  // Attach getView to the container DOM element so parent can access it
  useEffect(() => {
    const el = containerRef.current
    if (el) {
      (el as HTMLDivElement & { _cmGetView?: () => EditorView | null })._cmGetView = getView
    }
  }, [getView])

  return (
    <div
      ref={containerRef}
      className={`border rounded-md overflow-hidden [&_.cm-editor]:outline-none [&_.cm-editor.cm-focused]:outline-none ${className}`}
    />
  )
}

/** Helper to get the EditorView from a CodeMirrorEditor container element */
export function getCMView(container: HTMLDivElement | null): EditorView | null {
  if (!container) return null
  return (container as HTMLDivElement & { _cmGetView?: () => EditorView | null })._cmGetView?.() ?? null
}
