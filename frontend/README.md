# React editorial portal

The portal uses React, Vite, and Keycloak's JavaScript adapter. Sign-in uses
Authorization Code + PKCE and keeps tokens only in memory. All application
requests go to `/api` on the same origin. Media bytes go directly to the
signed Azure Blob URL; internal Python endpoints are never called by the browser.

The portal provides Google sign-in, uploader/researcher role selection, pending
approval status, role-aware navigation, admin request approval and role assignment, uploads with progress/status polling, metadata editing,
filtered semantic search, video timestamps, related media, and signed
preview/download access. A 30-minute activity timer signs idle users out;
server/provider session limits remain authoritative.

Search uses a responsive photo gallery, topic suggestions, expandable filters,
and comfortable/compact layouts. `Gallery.jsx` requests authorized 60-second Blob SAS
URLs as cards approach the viewport. It never stores signed URLs persistently;
failed/expired previews can be retried. A native modal provides focus isolation,
Escape, previous/next buttons and arrow-key navigation, with captions and rights
beside the media. Original files are used for previews; add generated thumbnail
objects before serving large image collections. Video cards preload metadata,
while the full preview provides playback at the matching timestamp.

Node 24+ is used by CI and the Docker build:

```bash
npm ci
npm test
npm run build
```

Browser component tests stub the OAuth boundary and API calls while running the
production React bundle. They run without Google credentials or a running stack:

```bash
npx playwright install chromium
npm run test:e2e
```

The full-stack acceptance test requires live Google sessions. Against an isolated
stack, sign in once per test identity and save Playwright `storageState` JSON as
`admin.json`, `employee.json`, `uploader.json`, and `researcher.json` in a private
directory. The admin must use `sagar.parker@sjsu.edu`; employee starts unassigned.
Set `GOOGLE_AUTH_STATE_DIR` to that directory and `APP_URL` to the stack URL when
running the tests. These session files are credentials and must stay outside the
repository. Full-stack acceptance and the opt-in reliability demo skip without
these sessions; backend JWT, approval and authorization tests remain automated.

## Shared theme and sign-in illustration

`public/theme.css` defines the portal and login colors and typography. The build
copies bundled font files and their licenses into `public/fonts` and builds the
Three.js login scene separately as `dist/assets/login-jungle.js`. The main portal
does not load Three.js. The login scene uses flat layers, respects reduced motion,
and includes a pause control and an SVG fallback when WebGL is unavailable.

Both Compose files mount `infra/keycloak-themes/mediamesh` into Keycloak. Newly
imported local realms select the `mediamesh` login theme. For an existing realm,
select **Realm settings → Themes → Login theme → mediamesh**; importing a realm
again does not update an existing realm. The theme loads its shared assets from
the frontend at the same origin, so deploy the frontend build with the theme.
Keycloak continues to handle credentials, password updates, and MFA.


## Search behavior

The browser sends natural-language queries and optional metadata filters to
Spring Boot, never directly to the ML service or OpenRouter. Explore buttons
send short topic phrases. Comma-separated examples use “or” so a single result
does not need every listed subject. The gallery currently requests up to 20
results; this is not a category listing of every object in storage.

The displayed similarity comes from the integrated backend's
`80% query-to-image/frame cosine + 20% query-to-metadata-text cosine` score.
It is not accuracy or probability. OpenRouter can exclude candidates after
ranking, so the returned count may be smaller than the requested limit. Videos
show the best sampled frame timestamp. The [root README](../README.md#system-architecture)
contains the component and sequence Mermaid diagrams.

The OpenRouter credential stays in server-side environment configuration. Vite
never receives it. The browser's Keycloak access token is a separate credential.

The Google sign-in button uses the unmodified, pre-approved light rectangular
PNG from [Google's branding assets](https://developers.google.com/identity/branding-guidelines#download-brand-icons).
`public/google-signin-light.png` is the 4x Android/Web asset, displayed at its
standard size to preserve the official logo, typography, and spacing. Both the
portal and Keycloak theme use this asset.
