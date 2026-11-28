# Google sign-in and access approval

MediaMesh uses Google sign-in through Keycloak. Users select **Uploader**,
**Researcher**, or both after signing in. Submitting a request does not grant
access. The administrator reviews it in **Admin → Pending access requests**.

- **Uploader** can upload images/videos for indexing and manage their contributions.
- **Researcher** can search the archive, use the authenticated search API, and view
  ready library media.
- One account can hold both roles. Approving a request adds the requested roles
  without removing existing access.
- The Google email set in **`ADMIN_EMAIL`** is the sole administrator. Its first verified Google
  sign-in creates administrator access automatically. ADMIN cannot be requested,
  granted to another account, removed, or deleted through the portal.

## Configure Google OAuth

1. Create a Google OAuth **Web application** client in Google Cloud Console.
   Configure the consent screen and any required test users or Workspace access.
2. Register the exact authorized redirect URI:
   - Local: `http://localhost:8080/auth/realms/mediamesh/broker/google/endpoint`
   - Hosted: `https://YOUR_DOMAIN/auth/realms/mediamesh/broker/google/endpoint`
3. Set `ADMIN_EMAIL` to your administrator’s Google email, plus `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the private Compose env file
   (`.env` locally, `infra/deploy/runtime/deploy.env` when hosted).
4. For a **new realm**, start the stack normally. The imported realm reads these
   values from the Keycloak container environment. Deployment preparation creates
   no local application administrator or temporary password.
5. For an **existing realm**, Keycloak skips realm import on restart. Configure
   its Google provider and token mapper with the included updater. Export the
   Google credentials and `KEYCLOAK_ADMIN_PASSWORD` privately, then run on the
   deployment VM (use the Keycloak container's private IP; the public proxy blocks
   administration endpoints):

   ```sh
   python3 infra/deploy/configure-google.py \
     --url http://KEYCLOAK_PRIVATE_IP:8080/auth \
     --public-host YOUR_DOMAIN --username deployment-admin
   ```

   For the local stack use `--url http://localhost:8080/auth --username local-admin`
   and the local Keycloak operator password. The updater preserves users and is
   safe to rerun. Restarting Keycloak is unnecessary after the updater.
6. Rebuild backend and frontend together. Migration V407 removes previous ADMIN
   grants and adds persisted access requests. Sign out of older password sessions
   and sign in with Google as the Google email configured by `ADMIN_EMAIL`.

The Google provider trusts Google email assertions (`trustEmail=true`) and uses
`syncMode=FORCE` for profile updates. On older Keycloak versions, existing users
created before email trust was enabled may need an operator to correct their email
verification after checking the matching Google federated identity. Other providers and local password sessions are not
accepted by the API.

The API validates Keycloak issuer/audience/signature, the broker's
`identity_provider=google` session claim, and `email_verified=true`. Local password
sessions do not receive application access. Provider session claims use
[Keycloak's documented user session note mapper](https://github.com/keycloak/keycloak/blob/main/docs/documentation/server_admin/topics/identity-broker/session-data.adoc).

Existing local users with the same email may need to link their Google identity
through Keycloak's first broker login flow. Preserve the existing Keycloak subject
when linking to retain ownership of uploaded media. Existing uploader/researcher
grants are retained; prior administrators must use the designated Google account.

## Request and approve access

1. Select **Sign in with Google** and complete Google sign-in.
2. On the **Access** tab, select one or both roles and select **Request access**.
3. The user sees a pending status. Upload/search endpoints remain blocked until
   the corresponding role is approved. Only one request can be pending per user.
4. The administrator opens **Admin**, refreshes the request list, and selects
   **Approve request** or **Decline request**. Decisions are audited.
5. Access updates on the next API request; the user's page checks every 15 seconds
   or they can select **Refresh access**. A declined request can be resubmitted.

Approved users can request their other role from **Access**. Administrators can
also edit existing uploader/researcher grants; changes take effect on the next
API request. Deleting an account revokes its sessions and closes pending requests
while preserving uploaded media and audit history.

The search API uses the signed-in account's Keycloak bearer access token; this
change does not introduce API keys. Never distribute OAuth client secrets or
access tokens to other users.

## Local session storage

Local Compose uses in-memory Keycloak login sessions to avoid duplicate
persistent-session database writes in the development H2 setup. Restarting
Keycloak signs users out; Google links, users, platform roles, approval requests,
and media remain persisted. The hosted PostgreSQL configuration continues to use
persistent sessions.
