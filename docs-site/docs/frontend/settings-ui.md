# Settings

The **Settings** page at `/settings` provides configuration options for the platform, sandbox, appearance, and security. Access it from the user menu in the bottom-left corner of the sidebar.

The page is organized into four tabs:

| Tab | Description |
|-----|-------------|
| **Platform Config** | Global platform settings such as the instance name, base URL, and feature flags |
| **Sandbox Config** | Resource limits and runtime settings for the code execution sandbox |
| **Appearance** | Theme selection (light, dark, system) |
| **Security / MFA** | Two-factor authentication management |

---

## Platform Config

The **Platform Config** tab contains instance-wide settings that apply to all users and workflows.

| Setting | Description |
|---------|-------------|
| **Instance Name** | Display name shown in the browser title and emails |
| **Base URL** | Public-facing URL of this Pipelit instance, used for webhook and callback URL generation |
| **Feature Flags** | Enable or disable optional platform features |

Changes saved here are written to `conf.json` and take effect without a server restart.

---

## Sandbox Config

The **Sandbox Config** tab controls the code execution sandbox used by **Run Command** and other execution nodes.

| Setting | Description |
|---------|-------------|
| **Max CPU time (seconds)** | Maximum CPU time a sandboxed process may consume before being killed |
| **Max memory (MB)** | Memory limit for sandboxed processes |
| **Allowed commands** | Allowlist of shell commands that the sandbox permits |
| **Network access** | Whether sandboxed processes can make outbound network requests |

---

## Appearance

The **Appearance** tab provides a **theme selector** with three options:

| Option | Behavior |
|--------|----------|
| **System** | Follows your operating system's light/dark mode preference. Automatically switches when the OS preference changes. |
| **Light** | Forces light mode regardless of OS preference. |
| **Dark** | Forces dark mode regardless of OS preference. |

The selected theme is displayed as toggle buttons -- the active option is highlighted with the primary color.

### Persistence

The theme preference is saved to `localStorage` under the key `theme`. It persists across browser sessions and is applied immediately on page load (before React renders) to prevent a flash of the wrong theme.

### How It Works

The `useTheme` hook:

1. Reads the saved preference from `localStorage` on mount (defaults to `system`)
2. Resolves the effective theme (`system` queries `prefers-color-scheme` media query)
3. Toggles the `dark` class on `document.documentElement`
4. When set to `system`, listens for OS preference changes and updates automatically

The resolved theme is also passed to the React Flow canvas so the workflow editor matches the application theme.

---

## Security / MFA

### Two-Factor Authentication (MFA)

The MFA tab lets you enable or disable TOTP-based two-factor authentication.

### Current Status

A badge shows whether MFA is currently **Enabled** or **Disabled**. The status is fetched from the server on page load.

### Enabling MFA

1. Click **Enable MFA**
2. A dialog appears with a QR code generated from a provisioning URI
3. Scan the QR code with your authenticator app (Google Authenticator, Authy, 1Password, etc.)
4. If you cannot scan, a manual entry key is provided below the QR code
5. Enter the 6-digit verification code from your authenticator app
6. Click **Verify & Enable**

!!! tip "Save your recovery codes"
    Store the manual entry key in a secure location. If you lose access to your authenticator app, you will need this key to regain access.

### Disabling MFA

1. Click **Disable MFA**
2. A dialog asks you to confirm by entering your current TOTP code
3. Enter the 6-digit code and click **Disable MFA**

!!! warning "Security consideration"
    Disabling MFA removes the second authentication factor. Only disable it if you have a good reason and understand the security implications.
