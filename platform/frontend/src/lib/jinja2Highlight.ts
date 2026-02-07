import { ViewPlugin, Decoration, EditorView } from "@codemirror/view"
import type { ViewUpdate, DecorationSet } from "@codemirror/view"
import type { Extension, Range } from "@codemirror/state"

const bracketDeco = Decoration.mark({ class: "cm-jinja2-bracket" })
const contentDeco = Decoration.mark({ class: "cm-jinja2-content" })

// Captures: (open bracket) (inner content) (close bracket)
// Handles {{ }}, {% %}, {# #} with whitespace-control variants
const JINJA2_RE = /(\{\{-?|{%-?|\{#-?)([\s\S]*?)(-?\}\}|-?%\}|-?#\})/g

function buildDecorations(view: EditorView): DecorationSet {
  const ranges: Range<Decoration>[] = []
  for (const { from, to } of view.visibleRanges) {
    const text = view.state.doc.sliceString(from, to)
    JINJA2_RE.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = JINJA2_RE.exec(text)) !== null) {
      const openStart = from + m.index
      const openEnd = openStart + m[1].length
      const innerStart = openEnd
      const innerEnd = innerStart + m[2].length
      const closeStart = innerEnd
      const closeEnd = closeStart + m[3].length

      ranges.push(bracketDeco.range(openStart, openEnd))
      if (innerEnd > innerStart) {
        ranges.push(contentDeco.range(innerStart, innerEnd))
      }
      ranges.push(bracketDeco.range(closeStart, closeEnd))
    }
  }
  return Decoration.set(ranges, true)
}

const jinja2Plugin = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet
    constructor(view: EditorView) {
      this.decorations = buildDecorations(view)
    }
    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged) {
        this.decorations = buildDecorations(update.view)
      }
    }
  },
  { decorations: (v) => v.decorations },
)

export const jinja2Highlight: Extension = jinja2Plugin
