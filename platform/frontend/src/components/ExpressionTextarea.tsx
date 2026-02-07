import { useRef, useCallback } from "react"
import { Textarea } from "@/components/ui/textarea"
import VariablePicker from "@/components/VariablePicker"
import type { WorkflowDetail } from "@/types/models"

interface ExpressionTextareaProps {
  value: string
  onChange: (value: string) => void
  slug: string
  nodeId: string
  workflow: WorkflowDetail
  placeholder?: string
  rows?: number
  className?: string
}

export default function ExpressionTextarea({
  value,
  onChange,
  slug,
  nodeId,
  workflow,
  placeholder,
  rows,
  className = "",
}: ExpressionTextareaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleInsert = useCallback(
    (expr: string) => {
      const el = textareaRef.current
      if (!el) {
        onChange(value + expr)
        return
      }

      const start = el.selectionStart
      const end = el.selectionEnd
      const before = value.slice(0, start)
      const after = value.slice(end)
      const newValue = before + expr + after
      onChange(newValue)

      // Restore cursor after the inserted expression
      requestAnimationFrame(() => {
        el.focus()
        const pos = start + expr.length
        el.setSelectionRange(pos, pos)
      })
    },
    [value, onChange],
  )

  return (
    <div className="relative">
      <Textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        className={className}
      />
      <div className="absolute top-1 right-1">
        <VariablePicker
          slug={slug}
          nodeId={nodeId}
          workflow={workflow}
          onInsert={handleInsert}
        />
      </div>
    </div>
  )
}
