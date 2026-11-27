# Account setup: researchers, uploaders and administrators

MediaMesh has no self-registration and no shared demo logins. Every account is
created by an administrator in the app. Sign-in uses Keycloak single sign-on with
a password and an authenticator app (TOTP).

Site: https://mediamesh-demo-bf5064f9.swedencentral.cloudapp.azure.com

## Roles

| Role | Can do | Who can create it |
|---|---|---|
| RESEARCHER | Search and preview/download READY media | Any administrator |
| UPLOADER | Upload media and edit their own uploads | Any administrator |
| ADMIN | Create accounts, change roles | Primary administrator only |

The primary administrator is `archive-admin`. It always keeps ADMIN. ADMIN does
not include searching or uploading; those need RESEARCHER or UPLOADER.

## 1. Administrator creates the account

1. Sign in as an administrator and open **Admin**.
2. Under **Create an account**, enter:
   - **Username**: 3–40 lowercase letters, digits, `.`, `-` or `_` (e.g. `jane.doe`).
   - **Email**: must be unique across all accounts.
   - **First and last name**.
   - **Role**: Researcher or Uploader. Administrator appears only for the
     primary administrator.
3. Select **Create account**. The temporary password is shown **once**. Copy it
   and send it to the person privately (not in a shared channel). If it is
   lost, create a new account; there is no way to show it again.

## 2. The new user signs in for the first time

The person needs an authenticator app on their phone, such as Google
Authenticator, Microsoft Authenticator or Authy.

1. Open the site and sign in with the username and temporary password.
2. Set a new password (at least 14 characters, different from the username).
3. Scan the QR code with the authenticator app, enter the 6-digit code it
   shows, and optionally name the device.
4. MediaMesh opens with the tabs for their role.

## 3. Signing in afterwards

Enter username, password and the current authenticator code. While a Keycloak
session is active (up to 30 minutes idle, 8 hours total) the browser signs in
without asking again.

## Testing several roles yourself

- Create one account per role, each with its own email. With Gmail-style
  addresses you can use aliases such as `you+researcher@sjsu.edu`.
- To switch accounts, select **Sign out**, then sign in with the other username.
  Sign out ends both the MediaMesh and the Keycloak session. Closing the tab
  without signing out keeps the old session, which signs you back in as the same
  person. A private/incognito window lets you stay signed in to two accounts at once.

## Changing access later

In **Admin**, tick or untick roles for a user and select **Save roles**. The
change applies on their next request. Only the primary administrator can tick or
untick ADMIN.

## Retired demo accounts

The seven `demo.*` accounts used to import the 50 sample assets are disabled in
Keycloak and cannot sign in. They still appear in the Admin list because they own
those assets, which remain searchable by researchers.

## Troubleshooting

| Problem | Cause / fix |
|---|---|
| "That username or email is already in use" | Pick another username or email. |
| Signed in as the wrong person | Sign out, or use a private window. |
| Authenticator code rejected | Check the phone's clock is set automatically; codes change every 30 seconds. |
| Lost phone or forgotten password | Needs a Keycloak reset by the operator (see `infra/deploy/README.md`); the app cannot reset it. |
| "Account creation is not configured" | The backend lacks `KEYCLOAK_PROVISIONER_SECRET`; see `infra/deploy/README.md`. |
