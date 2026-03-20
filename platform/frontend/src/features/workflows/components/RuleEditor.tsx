import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Trash2, Plus } from "lucide-react"
import type { Rule, SwitchRule } from "@/types/models"

const OPERATOR_OPTIONS = [
  { group: "Universal", options: [
    { value: "exists", label: "Exists" },
    { value: "does_not_exist", label: "Does not exist" },
    { value: "is_empty", label: "Is empty" },
    { value: "is_not_empty", label: "Is not empty" },
  ]},
  { group: "String", options: [
    { value: "equals", label: "Equals" },
    { value: "not_equals", label: "Not equals" },
    { value: "contains", label: "Contains" },
    { value: "not_contains", label: "Not contains" },
    { value: "starts_with", label: "Starts with" },
    { value: "not_starts_with", label: "Not starts with" },
    { value: "ends_with", label: "Ends with" },
    { value: "not_ends_with", label: "Not ends with" },
    { value: "matches_regex", label: "Matches regex" },
    { value: "not_matches_regex", label: "Not matches regex" },
  ]},
  { group: "Number", options: [
    { value: "gt", label: "Greater than" },
    { value: "lt", label: "Less than" },
    { value: "gte", label: "Greater or equal" },
    { value: "lte", label: "Less or equal" },
  ]},
  { group: "Datetime", options: [
    { value: "after", label: "After" },
    { value: "before", label: "Before" },
    { value: "after_or_equal", label: "After or equal" },
    { value: "before_or_equal", label: "Before or equal" },
  ]},
  { group: "Boolean", options: [
    { value: "is_true", label: "Is true" },
    { value: "is_false", label: "Is false" },
  ]},
  { group: "Array", options: [
    { value: "length_eq", label: "Length equals" },
    { value: "length_neq", label: "Length not equals" },
    { value: "length_gt", label: "Length greater than" },
    { value: "length_lt", label: "Length less than" },
    { value: "length_gte", label: "Length greater or equal" },
    { value: "length_lte", label: "Length less or equal" },
  ]},
]

const UNARY_OPERATORS = new Set(["exists", "does_not_exist", "is_empty", "is_not_empty", "is_true", "is_false"])

export function generateRuleId(): string {
  return "r_" + Math.random().toString(36).slice(2, 8)
}

/** Parse a full field path like "node_outputs.cat_1.category" into { sourceNodeId, outputField }. */
export function parseFieldPath(field: string): { sourceNodeId: string; outputField: string } {
  if (!field || !field.startsWith("node_outputs.")) return { sourceNodeId: "", outputField: field }
  const rest = field.slice("node_outputs.".length)
  const dotIdx = rest.indexOf(".")
  if (dotIdx === -1) return { sourceNodeId: rest, outputField: "" }
  return { sourceNodeId: rest.slice(0, dotIdx), outputField: rest.slice(dotIdx + 1) }
}

export function buildFieldPath(sourceNodeId: string, outputField: string): string {
  if (!sourceNodeId) return outputField
  return `node_outputs.${sourceNodeId}${outputField ? "." + outputField : ""}`
}

interface RuleEditorProps<T extends Rule> {
  rules: T[]
  onChange: (rules: T[]) => void
  upstreamNodes: string[]
  /** Show per-rule label field (switch mode) */
  showLabel?: boolean
  /** Show source node dropdown per rule (switch mode — source is part of field path) */
  showSourceNode?: boolean
  /** Show fallback toggle */
  showFallback?: boolean
  enableFallback?: boolean
  onFallbackChange?: (v: boolean) => void
  /** Title for the rules section */
  title?: string
  /** Empty state message */
  emptyMessage?: string
}

export default function RuleEditor<T extends Rule>({
  rules,
  onChange,
  upstreamNodes,
  showLabel = false,
  showSourceNode = false,
  showFallback = false,
  enableFallback = false,
  onFallbackChange,
  title = "Rules",
  emptyMessage = "No rules defined.",
}: RuleEditorProps<T>) {
  const addRule = () => {
    const defaultField = showSourceNode && upstreamNodes.length === 1 ? buildFieldPath(upstreamNodes[0], "") : ""
    const newRule = { id: generateRuleId(), field: defaultField, operator: "equals", value: "", ...(showLabel ? { label: "" } : {}) } as T
    onChange([...rules, newRule])
  }

  const removeRule = (id: string) => {
    onChange(rules.filter((r) => r.id !== id))
  }

  const updateRule = (id: string, patch: Partial<T>) => {
    onChange(rules.map((r) => r.id === id ? { ...r, ...patch } : r))
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label className="text-xs font-semibold">{title}</Label>
        <Button
          variant="outline"
          size="sm"
          className="h-6 px-2 text-xs"
          onClick={addRule}
        >
          <Plus className="h-3 w-3 mr-1" />
          Add Rule
        </Button>
      </div>
      {rules.length === 0 && (
        <p className="text-xs text-muted-foreground text-center py-2">{emptyMessage}</p>
      )}
      {rules.map((rule, idx) => (
        <div key={rule.id} className="border rounded-md p-2 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">Rule {idx + 1}</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-5 w-5 p-0"
              onClick={() => removeRule(rule.id)}
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
          {showLabel && (
            <div className="space-y-1">
              <Label className="text-[10px]">Label</Label>
              <Input
                value={(rule as unknown as SwitchRule).label ?? ""}
                onChange={(e) => updateRule(rule.id, { label: e.target.value } as unknown as Partial<T>)}
                className="text-xs h-7"
                placeholder="e.g. Good"
              />
            </div>
          )}
          {showSourceNode ? (
            <>
              <div className="space-y-1">
                <Label className="text-[10px]">Source Node</Label>
                {upstreamNodes.length > 0 ? (
                  <Select
                    value={parseFieldPath(rule.field).sourceNodeId || (upstreamNodes.length === 1 ? upstreamNodes[0] : "")}
                    onValueChange={(v) => updateRule(rule.id, { field: buildFieldPath(v, parseFieldPath(rule.field).outputField) } as Partial<T>)}
                  >
                    <SelectTrigger className="text-xs h-7 font-mono"><SelectValue placeholder="Select source node" /></SelectTrigger>
                    <SelectContent>
                      {upstreamNodes.map((nid) => (
                        <SelectItem key={nid} value={nid} className="text-xs font-mono">{nid}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    value={parseFieldPath(rule.field).sourceNodeId}
                    onChange={(e) => updateRule(rule.id, { field: buildFieldPath(e.target.value, parseFieldPath(rule.field).outputField) } as Partial<T>)}
                    className="text-xs h-7 font-mono"
                    placeholder="node_id"
                  />
                )}
              </div>
              <div className="space-y-1">
                <Label className="text-[10px]">Output Field</Label>
                <Input
                  value={parseFieldPath(rule.field).outputField}
                  onChange={(e) => updateRule(rule.id, { field: buildFieldPath(parseFieldPath(rule.field).sourceNodeId, e.target.value) } as Partial<T>)}
                  className="text-xs h-7 font-mono"
                  placeholder="e.g. category"
                />
              </div>
            </>
          ) : (
            <div className="space-y-1">
              <Label className="text-[10px]">Field</Label>
              <Input
                value={rule.field}
                onChange={(e) => updateRule(rule.id, { field: e.target.value } as Partial<T>)}
                className="text-xs h-7 font-mono"
                placeholder="e.g. name, status"
              />
            </div>
          )}
          <div className="space-y-1">
            <Label className="text-[10px]">Operator</Label>
            <Select
              value={rule.operator}
              onValueChange={(v) => updateRule(rule.id, { operator: v } as Partial<T>)}
            >
              <SelectTrigger className="text-xs h-7"><SelectValue /></SelectTrigger>
              <SelectContent>
                {OPERATOR_OPTIONS.map((group) => (
                  <div key={group.group}>
                    <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground">{group.group}</div>
                    {group.options.map((op) => (
                      <SelectItem key={op.value} value={op.value} className="text-xs">{op.label}</SelectItem>
                    ))}
                  </div>
                ))}
              </SelectContent>
            </Select>
          </div>
          {!UNARY_OPERATORS.has(rule.operator) && (
            <div className="space-y-1">
              <Label className="text-[10px]">Value</Label>
              <Input
                value={rule.value}
                onChange={(e) => updateRule(rule.id, { value: e.target.value } as Partial<T>)}
                className="text-xs h-7"
                placeholder="comparison value"
              />
            </div>
          )}
        </div>
      ))}
      {showFallback && (
        <div className="flex items-center justify-between pt-1">
          <div>
            <Label className="text-xs">Fallback Route</Label>
            <p className="text-[10px] text-muted-foreground">Route to "other" when no rules match</p>
          </div>
          <Switch checked={enableFallback} onCheckedChange={onFallbackChange} />
        </div>
      )}
    </div>
  )
}
