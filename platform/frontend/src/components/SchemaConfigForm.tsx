import { useMemo } from "react"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"

/**
 * Renders a node's configuration form from its `config_schema`, rather than
 * from a form hand-written per node type.
 *
 * Node types derived from a binary catalog are not knowable at build time —
 * their operations and parameters come from a file this repository does not
 * contain — so a hand-written form is not an option for them. It was never a
 * good option for the built-ins either: `mailbox_action`'s form is ~130 lines of
 * per-operation field tables in NodeDetailsPanel, and that is the cost per node
 * type of doing it by hand.
 *
 * The schema shape this reads is what `schemas/binary_catalogs.py` emits: an
 * `operation` enum, plus an `x-operations` sidecar mapping each operation to its
 * own summary and JSON Schema for parameters. The sidecar exists because JSON
 * Schema has nowhere to say "and when operation is X, these are the fields".
 */

type Json = Record<string, unknown>

interface OperationSpec {
  summary?: string
  params?: Json
  session_required?: boolean
  timeout_default_s?: number
}

export interface SchemaConfigFormProps {
  schema: Json
  value: Record<string, unknown>
  onChange: (next: Record<string, unknown>) => void
}

/** True when this schema is one this form can drive. */
export function isOperationSchema(schema: unknown): boolean {
  return Boolean(schema && typeof schema === "object" && "x-operations" in (schema as Json))
}

function FieldLabel({ name, spec, required }: { name: string; spec: Json; required: boolean }) {
  const title = (spec.title as string) ?? name
  return (
    <Label className="text-xs">
      {title}
      {required && <span className="text-destructive ml-0.5">*</span>}
    </Label>
  )
}

function ScalarField({
  name, spec, required, value, onChange,
}: {
  name: string; spec: Json; required: boolean
  value: unknown; onChange: (v: unknown) => void
}) {
  const type = spec.type as string | undefined
  const enumValues = spec.enum as string[] | undefined
  const description = spec.description as string | undefined

  return (
    <div className="space-y-1">
      {type === "boolean" ? (
        <div className="flex items-center justify-between">
          <FieldLabel name={name} spec={spec} required={required} />
          <Switch checked={Boolean(value)} onCheckedChange={onChange} />
        </div>
      ) : enumValues ? (
        <>
          <FieldLabel name={name} spec={spec} required={required} />
          <Select value={(value as string) ?? ""} onValueChange={onChange}>
            <SelectTrigger className="text-xs h-7"><SelectValue placeholder="—" /></SelectTrigger>
            <SelectContent>
              {enumValues.map((v) => <SelectItem key={v} value={v}>{v}</SelectItem>)}
            </SelectContent>
          </Select>
        </>
      ) : (
        <>
          <FieldLabel name={name} spec={spec} required={required} />
          <Input
            className="text-xs h-7"
            value={value === undefined || value === null ? "" : String(value)}
            placeholder={type && type !== "string" ? type : undefined}
            onChange={(e) => onChange(e.target.value)}
          />
        </>
      )}
      {description && <p className="text-[10px] text-muted-foreground">{description}</p>}
    </div>
  )
}

export default function SchemaConfigForm({ schema, value, onChange }: SchemaConfigFormProps) {
  const operations = (schema["x-operations"] ?? {}) as Record<string, OperationSpec>
  const binary = schema["x-binary"] as string | undefined
  const ids = useMemo(() => Object.keys(operations).sort(), [operations])

  const selected = (value.operation as string) ?? ""
  const op = operations[selected]
  const params = (op?.params ?? {}) as Json
  const properties = (params.properties ?? {}) as Record<string, Json>
  const required = new Set((params.required as string[]) ?? [])

  const set = (key: string, v: unknown) => onChange({ ...value, [key]: v })

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <Label className="text-xs font-semibold">Operation</Label>
        <Select
          value={selected}
          onValueChange={(next) => {
            // Parameters belong to the operation that declared them. Carrying
            // them across a change would leave the node holding fields the new
            // operation never accepts, which fails at call time rather than here.
            const keep: Record<string, unknown> = { operation: next }
            for (const k of ["session", "env"]) if (value[k] !== undefined) keep[k] = value[k]
            onChange(keep)
          }}
        >
          <SelectTrigger className="text-xs h-7">
            <SelectValue placeholder={`Choose an operation${binary ? ` from ${binary}` : ""}`} />
          </SelectTrigger>
          <SelectContent>
            {ids.map((id) => <SelectItem key={id} value={id}>{id}</SelectItem>)}
          </SelectContent>
        </Select>
        {op?.summary && <p className="text-[10px] text-muted-foreground">{op.summary}</p>}
      </div>

      {selected && (
        <>
          <div className="space-y-1">
            <Label className="text-xs">
              Session
              {op?.session_required && <span className="text-destructive ml-0.5">*</span>}
            </Label>
            <Input
              className="text-xs h-7"
              value={(value.session as string) ?? ""}
              placeholder={op?.session_required ? "required by this operation" : "not required"}
              onChange={(e) => set("session", e.target.value)}
            />
            <p className="text-[10px] text-muted-foreground">
              Identity handle held by the binary. Pipelit stores no credentials of its own.
            </p>
          </div>

          <div className="space-y-1">
            <Label className="text-xs">Environment</Label>
            <Input
              className="text-xs h-7"
              value={(value.env as string) ?? ""}
              onChange={(e) => set("env", e.target.value)}
            />
          </div>

          {Object.entries(properties).map(([name, spec]) => (
            <ScalarField
              key={name}
              name={name}
              spec={spec}
              required={required.has(name)}
              value={value[name]}
              onChange={(v) => set(name, v)}
            />
          ))}

          {Object.keys(properties).length === 0 && (
            <p className="text-[10px] text-muted-foreground">This operation takes no parameters.</p>
          )}

          {op?.timeout_default_s !== undefined && (
            <p className="text-[10px] text-muted-foreground">
              Times out after {op.timeout_default_s}s, including any verification the
              operation performs internally.
            </p>
          )}
        </>
      )}
    </div>
  )
}
