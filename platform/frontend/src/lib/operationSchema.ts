/**
 * Reading an operation schema.
 *
 * A node type may declare its operations in `config_schema` — a catalog-derived
 * type does, and a built-in may too. These helpers are what the config form, the
 * canvas and the variable picker read it with. They live apart from any
 * component because a module that exports both a component and a function
 * cannot fast-refresh.
 */
import type { NodeTypeSpec, PortDefinition } from "@/types/nodeIO"
import type { BinaryCatalog } from "@/api/plugins"

type Json = Record<string, unknown>

/**
 * The parts of `auth login` and `env add` a binary may declare for itself.
 *
 * The verb surface is protocol-fixed, but the protocol deliberately keeps two
 * of the objects it carries opaque: what establishes an identity (`credential`)
 * and what an environment record holds differ per binary, and its catalog may
 * describe them (`credential_schema`, `env_schema`). A host that hardcodes a
 * guess renders a form with no field for the thing the binary requires — so
 * the static verb entries are FALLBACKS, and these rules splice a binary's
 * declared fields in beside the protocol-fixed parameters. Mirrors
 * `compose_verbs` in the backend (schemas/binary_verbs.py); the `fixed` lists
 * and reserved keys are the backend's `_FIXED_PARAMS` and
 * `RESERVED_CONFIG_KEYS`.
 */
const VERB_DECLARED_SCHEMA: Record<
  string,
  { key: "credential_schema" | "env_schema"; fixed: string[] }
> = {
  "auth.login": { key: "credential_schema", fixed: ["env", "session"] },
  "env.add": { key: "env_schema", fixed: ["name"] },
}

const RESERVED_KEYS = ["binary", "domain", "operation", "session", "env"]

function composeVerbOperations(
  operations: Json,
  catalog: BinaryCatalog | undefined,
): Json {
  const out: Json = { ...operations }
  for (const [verbId, rule] of Object.entries(VERB_DECLARED_SCHEMA)) {
    const entry = out[verbId] as Json | undefined
    const declared = catalog?.[rule.key] as Json | null | undefined
    const declaredProps = declared?.properties as Record<string, Json> | undefined
    if (!entry || !declaredProps) continue
    const reserved = new Set([...RESERVED_KEYS, ...rule.fixed])
    // A declared property colliding with a platform key is skipped, as the
    // backend skips it; declaring ONLY collisions falls back entirely, since
    // an empty form would leave the operator nothing to fill in.
    const props = Object.fromEntries(
      Object.entries(declaredProps).filter(([name]) => !reserved.has(name)),
    )
    if (!Object.keys(props).length) continue
    const baseProps = ((entry.params as Json | undefined)?.properties ?? {}) as Record<string, Json>
    out[verbId] = {
      ...entry,
      params: {
        type: "object",
        required: [
          ...rule.fixed,
          ...((declared?.required as string[] | undefined) ?? []).filter((r) => r in props),
        ],
        // Declared property specs pass through untouched, so `secret: true`
        // still masks and still raises the plain-text storage notice.
        properties: {
          ...Object.fromEntries(rule.fixed.map((k) => [k, baseProps[k]])),
          ...props,
        },
      },
    }
  }
  return out
}

/**
 * The operation schema that actually governs one NODE — resolved per node, not
 * per type, because `binary_op` is a single static type whose operations live in
 * whichever binary's catalog the node names in `extra_config.binary`.
 *
 * - A spec whose `config_schema` carries `x-operations` (mailbox_action,
 *   binary_auth) governs every node of the type. For `binary_auth` the node's
 *   binary is spread in as `x-binary`, which is where SchemaConfigForm's
 *   session/environment pickers read it — the static spec cannot carry it
 *   because the binary is node data now — and the login/env.add entries are
 *   re-composed from whatever that binary's catalog declares for them.
 * - A `binary_op` node resolves to its binary's catalog schema. No binary, no
 *   registered catalog, or an unreadable catalog file (`schema: null`) all
 *   resolve to null: there is nothing truthful to render.
 * - Everything else resolves to null — not operation-driven.
 */
export function operationSchemaForNode(
  componentType: string,
  extraConfig: Record<string, unknown> | undefined,
  spec: NodeTypeSpec | undefined,
  catalogs: BinaryCatalog[] | undefined,
): Json | null {
  const specSchema = spec?.config_schema as Json | undefined
  if (specSchema && "x-operations" in specSchema) {
    if (componentType === "binary_auth") {
      // The static spec's login and env.add entries are fallbacks; whatever
      // this node's binary declares for them is composed in per node, exactly
      // as the component composes it at run time.
      const binary = extraConfig?.binary as string | undefined
      const catalog = binary ? catalogs?.find((c) => c.binary === binary) : undefined
      return {
        ...specSchema,
        "x-binary": binary,
        "x-operations": composeVerbOperations(
          (specSchema["x-operations"] ?? {}) as Json,
          catalog,
        ),
      }
    }
    return specSchema
  }
  if (componentType === "binary_op") {
    const binary = extraConfig?.binary as string | undefined
    if (!binary) return null
    return catalogs?.find((c) => c.binary === binary)?.schema ?? null
  }
  return null
}

/**
 * Restrict a catalog schema's operations to one domain — the palette creates a
 * `binary_op` node per (binary, domain), and the panel's dropdown honours that.
 *
 * When the node carries no `domain` (created raw through the API, or migrated),
 * it is derived from the configured operation's catalog entry; failing that,
 * every operation shows. A domain naming no operation at all (the catalog moved
 * on) also shows everything — an empty dropdown would leave the node
 * unconfigurable, which hides the mismatch instead of surfacing it.
 */
export function filterOperationsToDomain(
  schema: Json,
  domain: string | undefined,
  configuredOperation: string | undefined,
): Json {
  const operations = (schema["x-operations"] ?? {}) as Record<string, { domain?: string }>
  const effective =
    domain ?? (configuredOperation ? operations[configuredOperation]?.domain : undefined)
  if (!effective) return schema
  const kept = Object.entries(operations).filter(([, op]) => op.domain === effective)
  if (!kept.length) return schema
  const properties = { ...((schema.properties ?? {}) as Json) }
  if (properties.operation) {
    properties.operation = {
      ...(properties.operation as Json),
      enum: kept.map(([id]) => id).sort(),
    }
  }
  return { ...schema, properties, "x-operations": Object.fromEntries(kept) }
}

/**
 * The output ports one NODE truly offers — what the variable picker suggests.
 *
 * A `binary_op` type declares no outputs at all: its ports belong to the
 * configured operation. With no binary or no recognised operation it offers NO
 * ports — edges to it are still permitted (sketch-first), but there is nothing
 * truthful to suggest until an operation is chosen. The catalog sidecar carries
 * output names only, so those ports surface as `any`.
 *
 * A `binary_auth` type is the same discipline through a different table: its
 * static spec declares the UNION of every verb's outputs (the type is what edge
 * validation resolves), which is truthful for no single verb. With no verb
 * chosen — or one the `x-operations` sidecar does not recognise — it offers NO
 * ports; once a verb is chosen it offers exactly that verb's outputs, typed
 * from the spec.
 *
 * Every other type starts from the spec's declared ports, narrowed to the
 * configured operation where the schema is operation-driven (mailbox_action).
 */
export function effectiveOutputPorts(
  componentType: string,
  extraConfig: Record<string, unknown> | undefined,
  spec: NodeTypeSpec | undefined,
  catalogs: BinaryCatalog[] | undefined,
): PortDefinition[] {
  const schema = operationSchemaForNode(componentType, extraConfig, spec, catalogs)
  if (componentType === "binary_op") {
    const operations = (schema?.["x-operations"] ?? {}) as Record<string, { outputs?: string[] }>
    const operation = extraConfig?.operation as string | undefined
    const declared = operation ? operations[operation]?.outputs : undefined
    return (declared ?? []).map((name) => ({
      name,
      data_type: "any" as const,
      description: "",
      required: false,
      default: null,
    }))
  }
  const base = spec?.outputs ?? []
  const emitted = emittedPortNames(schema, extraConfig)
  if (componentType === "binary_auth" && !emitted) return []
  return emitted ? base.filter((p) => emitted.has(p.name)) : base
}

/**
 * Which ports a node actually fills, given the operation it is configured for.
 *
 * An operation-driven node type declares the UNION of its operations' outputs,
 * because ports belong to the type and the type is what edge validation
 * resolves. Any one run fills only its own operation's ports and returns the
 * rest as null — deliberately, since a missing key becomes the literal string
 * `{{ node.port }}` travelling downstream as though it were data.
 *
 * That is right for the value and wrong for the display: four nulls beside one
 * result reads as "these are empty" when it means "these belong to a different
 * operation". This narrows what is SHOWN; the value keeps every port.
 *
 * Takes the schema `operationSchemaForNode` resolved for the node. Returns null
 * for a schema that is not operation-driven, meaning "all of them" — every
 * plain built-in node type takes that path.
 */
export function emittedPortNames(
  schema: Json | null | undefined,
  extraConfig: Record<string, unknown> | undefined,
): Set<string> | null {
  const operations = schema?.["x-operations"] as
    | Record<string, { outputs?: string[] }>
    | undefined
  if (!operations) return null

  const operation = extraConfig?.operation as string | undefined
  const declared = operation ? operations[operation]?.outputs : undefined
  // An unrecognised or unset operation narrows nothing rather than hiding
  // everything: a node mid-configuration should not look like it produces no
  // output at all.
  return declared ? new Set(declared) : null
}

/** Keep only the ports the configured operation declares. */
export function narrowOutput(
  output: Record<string, unknown> | undefined,
  emitted: Set<string> | null,
): Record<string, unknown> | undefined {
  if (!output || !emitted) return output
  const kept = Object.entries(output).filter(([k]) => emitted.has(k))
  // If the operation's declared ports and the returned keys do not overlap at
  // all, show the raw output rather than an empty object — the catalog and the
  // binary disagreeing is something to see, not to hide.
  return kept.length ? Object.fromEntries(kept) : output
}

/** True when this schema is one this form can drive. */
export function isOperationSchema(schema: unknown): boolean {
  return Boolean(schema && typeof schema === "object" && "x-operations" in (schema as Json))
}

/**
 * Coerce a form's values to the types its parameters declare.
 *
 * Fields are edited as text and coerced once, here, rather than per keystroke —
 * coercing as you type makes "1." unrepresentable and "0.5" unreachable. An
 * empty value is dropped rather than sent as "", because a parameter that is
 * absent and one that is empty mean different things to a binary.
 *
 * A number carrying a {{ }} expression stays a string: it is resolved upstream
 * of the component and is not a number yet.
 */
export function coerceBySchema(
  schema: Json, operation: string | undefined, value: Record<string, unknown>,
): Record<string, unknown> {
  const operations = (schema["x-operations"] ?? {}) as Record<string, { params?: Json }>
  const properties = ((operations[operation ?? ""]?.params ?? {}) as Json).properties as
    | Record<string, Json>
    | undefined
  if (!properties) return value

  const out: Record<string, unknown> = { ...value }
  for (const [name, spec] of Object.entries(properties)) {
    const raw = out[name] === undefined ? spec.default : out[name]
    if (spec.type === "boolean") {
      out[name] = Boolean(raw)
      continue
    }
    if (raw === undefined || raw === null || String(raw).trim() === "") {
      delete out[name]
      continue
    }
    const text = String(raw)
    if (spec.type === "array") {
      out[name] = text.split(",").map((s) => s.trim()).filter(Boolean)
    } else if (spec.type === "number" && !text.includes("{{")) {
      const n = Number(text)
      out[name] = Number.isNaN(n) ? text : n
    } else {
      out[name] = text
    }
  }
  return out
}

