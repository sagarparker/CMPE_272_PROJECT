# React editorial portal

The portal uses React, Vite, and Keycloak's JavaScript adapter. Sign-in uses
Authorization Code + PKCE and keeps tokens only in memory. All application
requests go to `/api` on the same origin. Media bytes go directly to the
signed Azure Blob URL; internal Python endpoints are never called by the browser.

The portal provides an unassigned-user screen, role-aware navigation, admin
role assignment, uploads with progress/status polling, metadata editing,
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

Run the full stack through `../infra/start.sh`, then run browser acceptance:

```bash
npx playwright install chromium
npm run test:e2e
```

The test uses the four public local demo accounts and synthetic image/video
fixtures. It grants and removes roles, creates test catalog records, and
requires the real CLIP model to be ready. It targets localhost by default;
`APP_URL` can select another isolated demo instance.
