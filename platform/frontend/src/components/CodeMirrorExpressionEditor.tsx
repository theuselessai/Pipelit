import { useRef, useCallback } from "react"
import CodeMirrorEditor, { getCMView, type CodeMirrorLanguage } from "@/components/CodeMirrorEditor"
import VariablePicker from "@/components/VariablePicker"
import type { WorkflowDetail } from "@/types/models"

interface CodeMirrorExpressionEditorProps {
  value: string
  onChange: (value: string) => void
  slug: string
  nodeId: string
  workflow: WorkflowDetail
  language?: CodeMirrorLanguage
  placeholder?: string
  className?: string
  readOnly?: boolean
}

export default function CodeMirrorExpressionEditor({
  value,
  onChange,
  slug,
  nodeId,
  workflow,
  language = "text",
  placeholder,
  className = "",
  readOnly = false,
}: CodeMirrorExpressionEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  const handleInsert = useCallback(
    (expr: string) => {
      // Find the CodeMirrorEditor's container (first child of our wrapper)
      const cmContainer = containerRef.current?.querySelector("[class*='cm-']")?.closest("div") ?? containerRef.current?.firstElementChild as HTMLDivElement | null
      const view = getCMView(cmContainer as HTMLDivElement)
      if (!view) {
        // Fallback: append to end
        onChange(value + expr)
        return
      }

      const { from, to } = view.state.selection.main
      view.dispatch({
        changes: { from, to, insert: expr },
        selection: { anchor: from + expr.length },
      })
      view.focus()
    },
    [value, onChange],
  )

  return (
    <div ref={containerRef} className="relative flex flex-col flex-1">
      <div className="absolute top-1 right-1 z-10">
        <VariablePicker
          slug={slug}
          nodeId={nodeId}
          workflow={workflow}
          onInsert={handleInsert}
        />
      </div>
      <CodeMirrorEditor
        value={value}
        onChange={onChange}
        language={language}
        placeholder={placeholder}
        className={`flex-1 [&_.cm-editor]:h-full [&_.cm-scroller]:overflow-auto ${className}`}
        readOnly={readOnly}
      />
    </div>
  )
}
