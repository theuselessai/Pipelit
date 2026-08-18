import type { NodeTypeSpec } from "@/types/nodeIO"

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
