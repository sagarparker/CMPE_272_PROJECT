import { build } from "vite";

// Stub the OAuth boundary while exercising the production React flow.
let bundled;
async function bundle() {
  if (bundled) return bundled;
  const result = await build({
    configFile: false, logLevel: "silent",
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    plugins: [{
      name: "oauth-test-boundary", enforce: "pre",
      resolveId(id) { if (id === "keycloak-js") return "\0oauth-stub"; },
      load(id) {
        if (id === "\0oauth-stub") return `export default class {
          token = 'test-token';
          init(options) { window.__authInit = options; return window.__signedIn === false ? new Promise(() => {}) : Promise.resolve(true); }
          updateToken() { return Promise.resolve(false); }
          login(options) { window.__googleLogin = options; return Promise.resolve(); }
          logout() { window.__logoutCalled = true; return Promise.resolve(); }
        }`;
      },
    }],
    build: { write: false, lib: { entry: "src/main.jsx", name: "AccessFlow", formats: ["iife"] } },
  });
  const output = (Array.isArray(result) ? result : [result]).flatMap(result => result.output);
  bundled = { script: output.find(asset => asset.type === "chunk").code,
    css: output.filter(asset => asset.type === "asset" && asset.fileName.endsWith(".css")).map(asset => asset.source).join("\n") };
  return bundled;
}
export async function openOauthPage(page, user, signedIn = true, url = "http://access.test/") {
  const { script, css } = await bundle();
  await page.addInitScript(value => { window.__signedIn = value; }, signedIn);
  await page.route(url, route => route.fulfill({
    contentType: "text/html",
    body: `<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}</style></head><body><div id="root"></div><script>${script.replaceAll("</script", "<\\/script")}</script></body></html>`,
  }));
  await page.route("**/api/me", route => route.fulfill({ json: user }));
  await page.goto(url);
}
