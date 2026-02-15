# Settings

The **Settings** page at `/settings` provides user-level configuration options. Access it from the user menu in the bottom-left corner of the sidebar.

## Appearance

The appearance card provides a **theme selector** with three options:

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

## Two-Factor Authentication (MFA)

The MFA card lets you enable or disable TOTP-based two-factor authentication.

### Current Status

A badge in the card header shows whether MFA is currently **Enabled** or **Disabled**. The status is fetched from the server on page load.

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
