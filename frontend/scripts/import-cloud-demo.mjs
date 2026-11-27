// Explicit cloud import using private credentials; never uses local fixture passwords.
import { chromium } from "@playwright/test";
import { readFile, writeFile, rename } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const [credentialsPath, expectedOrigin] = process.argv.slice(2);
if (!credentialsPath || !expectedOrigin) throw new Error("Usage: node scripts/import-cloud-demo.mjs PRIVATE_CREDENTIALS_FILE EXPECTED_HTTPS_ORIGIN");
const credentials = JSON.parse(await readFile(credentialsPath, "utf8"));
const base = credentials.origin;
assert.equal(base, expectedOrigin);
assert.equal(new URL(base).origin, base);
assert.equal(new URL(base).protocol, "https:");
const root = fileURLToPath(new URL("../../", import.meta.url));
const manifest = JSON.parse(await readFile(path.join(root, "ml-service/evaluation/demo-manifest.json"), "utf8"));
const cache = path.join(root, "ml-service/data/demo");
assert.equal(manifest.items.length, 50);
assert.equal(credentials.accounts.length, 7);
for (const item of manifest.items) {
  assert.equal(path.basename(item.filename), item.filename);
  assert.equal(createHash("sha256").update(await readFile(path.join(cache, item.filename))).digest("hex"), item.sha256);
  assert.ok(item.creator && item.license && item.source_page);
}
const statePath = path.join(path.dirname(credentialsPath), "demo-upload-state.json");
let state;
try { state = JSON.parse(await readFile(statePath, "utf8")); }
catch (error) { if (error.code !== "ENOENT") throw error; state = { origin: base, assets: {} }; }
assert.equal(state.origin, base);
async function save() { await writeFile(statePath + ".tmp", JSON.stringify(state, null, 2) + "\n", { mode: 0o600 }); await rename(statePath + ".tmp", statePath); }
const browser = await chromium.launch();
const contexts = [];
const users = new Map();
async function api(user, method, route, data) {
  const response = await user.page.request.fetch(base + "/api" + route, { method, headers: { Authorization: user.token }, ...(data === undefined ? {} : { data }), timeout: 20000 });
  if (!response.ok()) throw new Error(`API ${method} ${route}: ${response.status()}`);
  return response.json();
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
    await page.goto(base);
    await page.locator("#username").fill(account.username);
    await page.locator("#password").fill(account.password);
    await page.locator("#kc-login").click();
    await page.getByRole("button", { name: "Sign out" }).waitFor();
    user.profile = await api(user, "GET", "/me");
    assert.equal(user.profile.id, account.appId);
    assert.deepEqual(user.profile.roles, account.roles);
    users.set(account.username, user);
    console.log(`SSO and roles verified: ${account.username}`);
  }
  for (const item of manifest.items) {
    const user = users.get("demo." + item.domain);
    const title = `${item.domain[0].toUpperCase() + item.domain.slice(1)} | ${item.title}`.slice(0, 255);
    const owned = await api(user, "GET", "/assets");
    let entry = state.assets[item.id];
    if (entry) { assert.equal(entry.sha256, item.sha256); assert.equal(entry.ownerId, user.profile.id); }
    if (!entry) {
      const existing = owned.find(a => a.title === title && a.usageNote?.includes(item.source_page));
      if (existing) entry = { assetId: existing.assetId, ownerId: user.profile.id, sha256: item.sha256 };
    }
    let current = entry ? await api(user, "GET", `/assets/${entry.assetId}`) : null;
    if (!entry) {
      const contentType = item.mediaType === "video" ? "video/mp4" : "image/jpeg";
      const initiated = await api(user, "POST", "/assets/initiate", {
        filename: item.filename, contentType, title, description: item.description || item.title,
        species: item.species || null, location: item.location || null, capturedAt: item.capturedAt || null,
        contributor: item.creator, usageNote: `${item.license}. Credit: ${item.creator}. Source: ${item.source_page}. License: ${item.license_url || item.source_page}. Educational demo; verify rights before publication.`,
      });
      entry = { assetId: initiated.assetId, ownerId: user.profile.id, sha256: item.sha256 };
      state.assets[item.id] = entry; await save();
      // Use a real browser fetch so successful imports also exercise Azure CORS.
      const status = await user.page.evaluate(async ({ url, headers, base64 }) => {
        const response = await fetch(url, { method: "PUT", headers, body: Uint8Array.from(atob(base64), x => x.charCodeAt(0)) });
        return response.status;
      }, { url: initiated.uploadUrl, headers: { ...initiated.uploadHeaders, "Content-Type": contentType, "If-None-Match": "*" }, base64: (await readFile(path.join(cache, item.filename))).toString("base64") });
      assert.equal(status, 201);
      await api(user, "POST", `/assets/${entry.assetId}/complete`);
    } else if (current.processingStatus === "UPLOADING") {
      await api(user, "POST", `/assets/${entry.assetId}/complete`);
    } else if (current.processingStatus === "FAILED") throw new Error(`Inspect failed indexing before retrying: ${item.id}`);
    state.assets[item.id] = entry; await save();
    console.log(`Imported ${item.id}`);
  }
  const deadline = Date.now() + 600000;
  while (true) {
    let ready = 0;
    for (const item of manifest.items) {
      const current = await api(users.get("demo." + item.domain), "GET", `/assets/${state.assets[item.id].assetId}`);
      assert.notEqual(current.processingStatus, "FAILED", `Indexing failed: ${item.id}`);
      if (current.processingStatus === "READY") ready++;
    }
    console.log(`READY ${ready}/50`);
    if (ready === 50) break;
    assert.ok(Date.now() < deadline, "Indexing deadline exceeded; state saved for resume");
    await new Promise(resolve => setTimeout(resolve, 3000));
  }
  console.log("Cloud transfer complete. IDs/checksums saved privately in demo-upload-state.json.");
} finally { await Promise.all(contexts.map(c => c.close())); await browser.close(); }
