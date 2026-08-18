/**
 * Reading an operation schema.
 *
 * A node type may declare its operations in `config_schema` — a catalog-derived
 * type does, and a built-in may too. These helpers are what the config form, the
 * canvas and the variable picker read it with. They live apart from any
 * component because a module that exports both a component and a function
 * cannot fast-refresh.
 */
import type { NodeTypeSpec } from "@/types/nodeIO"

type Json = Record<string, unknown>

/**
 * Which ports a node actually fills, given the operation it is configured for.
 *
 * A node type derived from a binary covers several operations and declares the
 * UNION of their outputs, because ports belong to the type and the type is what
 * edge validation resolves. Any one run fills only its own operation's ports and
 * returns the rest as null — deliberately, since a missing key becomes the
 * literal string `{{ node.port }}` travelling downstream as though it were data.
 *
 * That is right for the value and wrong for the display: four nulls beside one
 * result reads as "these are empty" when it means "these belong to a different
 * operation". This narrows what is SHOWN; the value keeps every port.
 *
 * Returns null for a node type that is not operation-driven, meaning "all of
 * them" — every built-in node type takes that path.
 */
export function emittedPortNames(
  spec: NodeTypeSpec | undefined,
  extraConfig: Record<string, unknown> | undefined,
): Set<string> | null {
  const operations = spec?.config_schema?.["x-operations"] as
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

