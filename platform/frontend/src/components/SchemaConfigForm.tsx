import { useMemo } from "react"
import { usePluginEnvironments, usePluginSessions } from "@/api/plugins"
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
  name, spec, required, value, onChange, options,
}: {
  name: string; spec: Json; required: boolean
  value: unknown; onChange: (v: unknown) => void
  options?: { value: string; label: string }[]
}) {
  const type = spec.type as string | undefined
  // A parameter may name something that must already exist — an environment to
  // bind to, an identity to refresh. Those get a picker. A parameter that
  // CREATES the thing does not: `auth login` writes a session handle, and
  // offering a list there would show only handles it is about to overwrite.
  const enumValues = (spec.enum as string[] | undefined)
    ?? (options?.length ? options.map((o) => o.value) : undefined)
  const labels = new Map((options ?? []).map((o) => [o.value, o.label]))
  const description = spec.description as string | undefined
  // Masked in the panel, but NOT secret at rest: the value lives in the node's
  // extra_config, so it reaches the database and the nodes API like any other
  // field. Intended for disposable test identities. See the note beneath.
  const secret = spec.secret === true
  // A parameter may declare a default. It matters beyond convenience: a guard
  // like a dry-run flag has to be the value you get without deciding.
  const effective = value === undefined ? spec.default : value

  return (
    <div className="space-y-1">
      {type === "boolean" ? (
        <div className="flex items-center justify-between">
          <FieldLabel name={name} spec={spec} required={required} />
          <Switch checked={Boolean(effective)} onCheckedChange={onChange} />
        </div>
      ) : enumValues ? (
        <>
          <FieldLabel name={name} spec={spec} required={required} />
          <Select value={(effective as string) ?? ""} onValueChange={onChange}>
            <SelectTrigger className="text-xs h-7"><SelectValue placeholder="—" /></SelectTrigger>
            <SelectContent>
              {enumValues.map((v) => (
                <SelectItem key={v} value={v}>{labels.get(v) ?? v}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </>
      ) : (
        <>
          <FieldLabel name={name} spec={spec} required={required} />
          <Input
            className="text-xs h-7"
            type={secret ? "password" : undefined}
            autoComplete={secret ? "new-password" : undefined}
            value={
              effective === undefined || effective === null ? ""
                : Array.isArray(effective) ? effective.join(", ")
                : String(effective)
            }
            placeholder={(spec.placeholder as string | undefined) ?? (type && type !== "string" ? type : undefined)}
            onChange={(e) => onChange(e.target.value)}
          />
        </>
      )}
      {description && <p className="text-[10px] text-muted-foreground">{description}</p>}
    </div>
  )
}

export default function SchemaConfigForm({ schema, value, onChange }: SchemaConfigFormProps) {
  const operations = useMemo(
    () => (schema["x-operations"] ?? {}) as Record<string, OperationSpec>,
    [schema],
  )
  const binary = schema["x-binary"] as string | undefined
  // On an identity node the verbs ESTABLISH a session rather than consuming one,
  // so `session` and `env` arrive as ordinary parameters — offering the pickers
  // as well would show two fields for one value, one of them wrong.
  const isVerbNode = schema["x-verbs"] === true
  const ids = useMemo(() => Object.keys(operations).sort(), [operations])
  // Fetched for every binary node. Operation nodes use them for the session and
  // environment selectors below; identity nodes use them for whichever of their
  // own parameters names something that already exists.
  const sessions = usePluginSessions(binary)
  const environments = usePluginEnvironments(binary)

  const pickerOptions = useMemo(() => ({
    sessions: (sessions.data?.items ?? []).map((s) => ({
      value: s.id,
      label: `${s.id}${s.subject ? ` — ${s.subject}` : ""} (${s.env})`,
    })),
    environments: (environments.data?.items ?? []).map((e) => ({
      value: e.name, label: `${e.name} (${e.kind})`,
    })),
  }), [sessions.data, environments.data])

  const selected = (value.operation as string) ?? ""
  // The schema says whether an operation is required (it is, for every binary
  // node). An innocent-looking empty select would hide that; the marker, the
  // destructive border and the note below make the unset state say so.
  const operationRequired = ((schema.required as string[] | undefined) ?? []).includes("operation")
  const operationMissing = operationRequired && !selected
  const op = operations[selected]
  const params = (op?.params ?? {}) as Json
  const properties = (params.properties ?? {}) as Record<string, Json>
  const required = new Set((params.required as string[]) ?? [])

  const set = (key: string, v: unknown) => onChange({ ...value, [key]: v })

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <Label className="text-xs font-semibold">
          Operation
          {operationRequired && <span className="text-destructive ml-0.5">*</span>}
        </Label>
        <Select
          value={selected}
          onValueChange={(next) => {
            // Parameters belong to the operation that declared them. Carrying
            // them across a change would leave the node holding fields the new
            // operation never accepts, which fails at call time rather than here.
            //
            // `binary` and `domain` are not parameters — they identify which
            // catalog and which domain within it this node belongs to — so they
            // must survive an operation change alongside `session` and `env`.
            // Backend mirrors this exact set as RESERVED_CONFIG_KEYS
            // (schemas/binary_catalogs.py).
            const keep: Record<string, unknown> = { operation: next }
            for (const k of ["binary", "domain", "session", "env"]) if (value[k] !== undefined) keep[k] = value[k]
            onChange(keep)
          }}
        >
          <SelectTrigger className={`text-xs h-7${operationMissing ? " border-destructive" : ""}`}>
            <SelectValue placeholder={`Choose an operation${binary ? ` from ${binary}` : ""}`} />
          </SelectTrigger>
          <SelectContent>
            {ids.map((id) => <SelectItem key={id} value={id}>{id}</SelectItem>)}
          </SelectContent>
        </Select>
        {op?.summary && <p className="text-[10px] text-muted-foreground">{op.summary}</p>}
        {operationMissing && (
          <p className="text-[10px] text-destructive">
            Required. Until an operation is chosen this node does nothing, offers no
            output ports, and fails the workflow's validation.
          </p>
        )}
      </div>

      {selected && !isVerbNode && (
        <>
          <div className="space-y-1">
            <Label className="text-xs">
              Session
              {op?.session_required && <span className="text-destructive ml-0.5">*</span>}
            </Label>
            {sessions.data?.items?.length ? (
              <Select value={(value.session as string) ?? ""} onValueChange={(v) => set("session", v)}>
                <SelectTrigger className="text-xs h-7"><SelectValue placeholder="Choose an identity" /></SelectTrigger>
                <SelectContent>
                  {sessions.data.items.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.id}{s.subject ? ` — ${s.subject}` : ""} ({s.env})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              // The list comes from running the binary, which can fail — a stale
              // registration, a missing plugin. Falling back to free text keeps
              // the node editable rather than unconfigurable.
              <Input
                className="text-xs h-7"
                value={(value.session as string) ?? ""}
                placeholder={sessions.isError ? "could not reach the binary — type a handle" : "identity handle"}
                onChange={(e) => set("session", e.target.value)}
              />
            )}
            <p className="text-[10px] text-muted-foreground">
              Identities are held by the binary; this platform stores no credentials of its own.
              Create one with an identity node, or with `auth login`.
            </p>
          </div>

          {/* An environment is bound to an identity when that identity is
              established, so it is selectable only where there is no identity to
              carry the binding. Offering it beside a session would suggest
              "this identity, that environment" is expressible; it is not, and
              binaries refuse the combination. */}
          {!op?.session_required && (
            <div className="space-y-1">
              <Label className="text-xs">Environment</Label>
              {environments.data?.items?.length ? (
                <Select value={(value.env as string) ?? ""} onValueChange={(v) => set("env", v)}>
                  <SelectTrigger className="text-xs h-7"><SelectValue placeholder="Choose an environment" /></SelectTrigger>
                  <SelectContent>
                    {environments.data.items.map((e) => (
                      <SelectItem key={e.name} value={e.name}>{e.name} ({e.kind})</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  className="text-xs h-7"
                  value={(value.env as string) ?? ""}
                  onChange={(e) => set("env", e.target.value)}
                />
              )}
              <p className="text-[10px] text-muted-foreground">
                This operation needs no identity, so it names an environment directly.
              </p>
            </div>
          )}

        </>
      )}

      {selected && (
        <>
          {Object.entries(properties).map(([name, spec]) => (
            <ScalarField
              key={name}
              name={name}
              spec={spec}
              required={required.has(name)}
              value={value[name]}
              onChange={(v) => set(name, v)}
              options={pickerOptions[(spec.picker as "sessions" | "environments") ?? ""]}
            />
          ))}

          {Object.keys(properties).length === 0 && (
            <p className="text-[10px] text-muted-foreground">This operation takes no parameters.</p>
          )}

          {Object.values(properties).some((p) => (p as Json).secret === true) && (
            <p className="text-[10px] text-amber-600 dark:text-amber-500">
              Masked here, but stored in plain text on this node — it reaches the database
              and the nodes API like any other field. Intended for disposable test identities,
              not for an account that matters.
            </p>
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
