"""drop llm_credentials.api_key — raw LLM keys live only in agentgateway

Revision ID: a41f9c2d7e10
Revises: 758cd1ca2aad
Create Date: 2026-07-03 00:00:00.000000

Phase 1(b) hard cutover (Pipelit#188): agentgateway is the sole holder of
LLM provider API keys. All code paths that read or wrote the encrypted
``llm_credentials.api_key`` column have been removed (direct-provider LLM
construction, credential CRUD/test/models endpoints, credential-field env
injection, DSL-compiler model fetch, and the one-shot ``migrate-credentials``
CLI, now deprecated), so the at-rest secret is dropped.

Column audit — what stays and why:

* ``provider_type`` — KEPT. Still read for backend-route resolution and
  provider inference (services/llm.py ``_resolve_backend_name``,
  ``resolve_credential_for_node`` → web-search provider detection).
* ``base_url`` — KEPT. Still resolvable via workspace credential-field env
  injection (components/_agent_shared.py ``_resolve_credential_field``) and
  used for legacy backend naming.
* ``organization_id`` — KEPT. Still resolvable via
  ``_resolve_credential_field`` for workspace env vars (non-secret metadata).
* ``custom_headers`` — KEPT (schema stability). No product-code reader
  remains after the LLM CRUD removal; retained as harmless non-secret
  metadata rather than widening this hard-cutover migration. Candidate for
  a future cleanup revision.
* ``api_key`` — DROPPED. This is the trust-boundary secret; no code reads
  or writes it anymore.

Hard cutover: no live user credentials exist, so there is no
data-preservation branch. ``downgrade()`` re-adds the column empty
(nullable — the original encrypted values are intentionally unrecoverable).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a41f9c2d7e10'
down_revision: Union[str, Sequence[str], None] = '758cd1ca2aad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table: portable across postgres and sqlite (test/dev DBs).
    with op.batch_alter_table('llm_credentials') as batch_op:
        batch_op.drop_column('api_key')


def downgrade() -> None:
    # Re-create the column shape only — the encrypted key data is gone for
    # good (hard cutover); nullable so existing rows remain valid.
    with op.batch_alter_table('llm_credentials') as batch_op:
        batch_op.add_column(sa.Column('api_key', sa.Text(), nullable=True))
