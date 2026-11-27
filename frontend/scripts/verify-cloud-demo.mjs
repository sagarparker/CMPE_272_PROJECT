// Read-only acceptance of the imported collection. Credentials/tokens stay private.
import { chromium } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
const [credentialsPath, expectedOrigin] = process.argv.slice(2);
const credentials = JSON.parse(await readFile(credentialsPath, "utf8"));
const base = credentials.origin;
assert.equal(base, expectedOrigin); assert.equal(new URL(base).protocol, "https:");
const directory = path.dirname(credentialsPath);
const state = JSON.parse(await readFile(path.join(directory, "demo-upload-state.json"), "utf8"));
assert.equal(state.origin, base);
const root = fileURLToPath(new URL("../../", import.meta.url));
const manifest = JSON.parse(await readFile(path.join(root, "ml-service/evaluation/demo-manifest.json"), "utf8"));
const browser = await chromium.launch(); const contexts = []; const users = new Map();
const report = { checkedAt: new Date().toISOString(), origin: base, domains: {}, hashesVerified: 0, searches: [] };
async function api(user, method, route, data) {
  const response = await user.page.request.fetch(base + "/api" + route, { method, headers: { Authorization: user.token }, ...(data === undefined ? {} : { data }), timeout: 20000 });
  assert.ok(response.ok(), `API ${method} ${route}: ${response.status()}`); return response.json();
}
try {
  for (const account of credentials.accounts) {
    const context = await browser.newContext(); contexts.push(context);
    const page = await context.newPage(); const user = { page, account };
    page.on("request", request => { if (request.url() === base + "/api/me") user.token = request.headers().authorization; });
    page.on("response", async response => {
      if (new URL(response.url()).pathname.endsWith("/protocol/openid-connect/token") && response.ok()) {
        const body = await response.json().catch(() => null);
        if (body?.access_token) user.token = `Bearer ${body.access_token}`;
      }
    });
    await page.goto(base); await page.locator("#username").fill(account.username); await page.locator("#password").fill(account.password); await page.locator("#kc-login").click();
    await page.getByRole("button", { name: "Sign out" }).waitFor();
    const profile = await api(user, "GET", "/me"); assert.equal(profile.id, account.appId); assert.deepEqual(profile.roles, account.roles);
    users.set(account.username, user);
    if (account.domain) {
      const assets = await api(user, "GET", "/assets");
      const expected = manifest.items.filter(x => x.domain === account.domain);
      assert.equal(assets.length, expected.length); report.domains[account.domain] = assets.length;
      for (const item of expected) {
        const asset = assets.find(x => x.assetId === state.assets[item.id].assetId);
        assert.ok(asset); assert.equal(asset.ownerId, account.appId); assert.equal(asset.processingStatus, "READY");
        assert.equal(asset.contributor, item.creator);
        for (const credit of [item.license, item.source_page]) assert.ok(asset.usageNote.includes(credit));
      }
      await page.locator(".asset-row").last().waitFor(); assert.equal(await page.locator(".asset-row").count(), expected.length);
    }
  }
  console.log("PASS: all uploader catalogs, ownership, credits, roles and READY status");
  const researcher = users.get("demo.researcher");
  for (const item of manifest.items) {
    const assetId = state.assets[item.id].assetId;
    const access = await api(researcher, "POST", `/assets/${assetId}/access-url`);
    assert.equal(new URL(access.url).hostname, "mm272bf5064f9demo.blob.core.windows.net");
    const media = await researcher.page.request.get(access.url, { timeout: 20000 }); assert.ok(media.ok());
    assert.equal(createHash("sha256").update(await media.body()).digest("hex"), item.sha256); report.hashesVerified++;
  }
  console.log("PASS: all 50 cloud media downloads match source SHA-256");
  const queries = ["elephants drinking at a watering hole", "yellow sunflower", "ocean waves", "sea turtle underwater", "a puffin bird", "a waterfall surrounded by green rainforest"];
  for (const query of queries) {
    const started = performance.now();
    const result = await api(researcher, "POST", "/search", { query, limit: 10 });
    assert.ok(result.results.length);
    report.searches.push({ query, clientDurationMs: Math.round(performance.now() - started), topTitle: result.results[0].title, results: result.results.length });
  }
  console.log("PASS: six semantic-search queries returned results");
  const first = state.assets[manifest.items[0].id].assetId;
  const plants = users.get("demo.plants");
  assert.ok([403, 404].includes((await plants.page.request.get(base + `/api/assets/${first}`, { headers: { Authorization: plants.token } })).status()));
  assert.equal((await plants.page.request.post(base + "/api/search", { headers: { Authorization: plants.token }, data: { query: "birds" } })).status(), 403);
  const download = await api(researcher, "POST", `/assets/${first}/access-url?download=true`);
  const downloaded = await researcher.page.request.get(download.url); assert.ok(downloaded.ok()); assert.ok(downloaded.headers()["content-disposition"].includes("attachment"));
  await researcher.page.getByLabel("Describe what you need").fill("yellow sunflower");
  await researcher.page.getByRole("button", { name: "Search archive", exact: true }).click();
  const flower = researcher.page.locator(".result").filter({ hasText: "Sunflower head" });
  await flower.waitFor(); await flower.scrollIntoViewIfNeeded(); await flower.locator("img").waitFor();
  assert.ok(await flower.locator("img").evaluate(async img => { await img.decode(); return img.naturalWidth > 0; }));
  await flower.getByRole("button", { name: "Preview", exact: true }).click();
  const dialog = researcher.page.getByRole("dialog", { name: "Media preview" });
  assert.ok(await dialog.getByRole("img").evaluate(async img => { await img.decode(); return img.naturalWidth > 0; }));
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  console.log("PASS: access isolation, download headers, inline gallery and preview dialog");
  report.galleryPreview = true; report.accessIsolation = true;
  await writeFile(path.join(directory, "demo-transfer-report.json"), JSON.stringify(report, null, 2) + "\n", { mode: 0o600 });
  console.log(JSON.stringify(report, null, 2));
} finally { await Promise.all(contexts.map(c => c.close())); await browser.close(); }
