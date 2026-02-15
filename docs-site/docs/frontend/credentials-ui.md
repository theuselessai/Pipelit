# Credentials

The **Credentials** page at `/credentials` manages API keys, bot tokens, and other secrets used by workflow nodes. Credentials are global -- any workflow can reference any credential.

## Credentials Table

The main view is a paginated table with the following columns:

| Column | Description |
|--------|-------------|
| **Checkbox** | Row selection for batch operations |
| **Name** | The credential's display name |
| **Type** | Badge showing the credential type |
| **Detail** | Provider type for LLM credentials (e.g., "openai_compatible") |
| **Created** | Creation date |
| **Actions** | Test button (LLM only) and delete button |

### Pagination

Credentials are paginated with **50 items per page**. Navigation controls appear at the bottom.

## Credential Types

The platform supports four credential types:

| Type | Purpose | Fields |
|------|---------|--------|
| **LLM** | LLM provider API access | Provider type, API key, base URL, organization ID |
| **Telegram** | Telegram bot authentication | Bot token |
| **Git** | Git repository access | (Configured via Extra Config) |
| **Tool** | Tool-specific credentials | (Configured via Extra Config) |

## Creating a Credential

Click **Add Credential** to open the creation dialog.

### Common Fields

- **Name** (required) -- A descriptive label for the credential

- **Type** (required) -- Select from LLM, Telegram, Git, or Tool

### LLM-Specific Fields

When the type is set to **LLM**, additional fields appear:

- **Provider Type** -- Choose from:
    - **OpenAI** -- For OpenAI's API
    - **Anthropic** -- For Anthropic's Claude API
    - **OpenAI Compatible** -- For any provider with an OpenAI-compatible API (e.g., local models, Venice.ai, Together AI)
- **API Key** -- Your provider's API key (masked as a password field)
- **Base URL** (optional) -- Override the default API endpoint. Useful for OpenAI-compatible providers that use a custom URL.
- **Organization ID** (optional) -- For OpenAI organization-scoped access

### Telegram-Specific Fields

When the type is set to **Telegram**:

- **Bot Token** -- Your Telegram bot token from @BotFather (masked as a password field)

## Testing Credentials

LLM credentials display a **Test** button in the actions column. Clicking it:

1. Sends a test request to the provider's API
2. Shows a loading spinner while the test runs
3. Displays the result:
    - **Green checkmark** -- The credential is valid
    - **Red X** -- The test failed (hover for details)

!!! tip "Test before using"
    Always test a new LLM credential before referencing it in a workflow. Invalid credentials cause execution failures that can be hard to diagnose.

## API Key Security

Sensitive fields (API keys, bot tokens) are encrypted at rest using Fernet encryption via the `FIELD_ENCRYPTION_KEY` environment variable. In the UI:

- API keys are entered as password fields (masked input)
- The API never returns raw key values -- only the encrypted reference is stored
- Credential detail shown in the table is limited to non-sensitive metadata (provider type, base URL)

## Deleting Credentials

### Single Delete

Click the trash icon on any row to open a confirmation dialog.

### Batch Delete

Select multiple credentials using checkboxes, then click **Delete Selected (N)**. A confirmation dialog shows the count.

!!! warning "Credential deletion"
    Deleting a credential that is referenced by workflow nodes will cause those nodes to fail during execution. Verify no active workflows depend on a credential before removing it.
