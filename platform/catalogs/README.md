# Binary catalogs

Generated, not committed. Each `*.json` here is the document one binary printed
when asked `<bin> catalog`, and `platform/schemas/binary_catalogs.py` turns each
one into node types at import.

    python scripts/refresh_catalog.py -- <how you invoke the binary>

The files are gitignored because a catalog describes one organisation's
operations and this repository is public. Only the loader and this note are
committed, so a fresh clone registers no binary node types until someone
refreshes a catalog — which is correct, since it cannot run those binaries
either.

Refreshing is manual on purpose. Node types must not change underneath saved
workflows because someone upgraded a binary, so the file is the pin and updating
it is something a person does and reads the diff of. The script prints added and
removed operations whenever the catalog hash moves.
