import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = relative => JSON.parse(readFileSync(new URL(relative, import.meta.url)));
const manifest = read("../../ml-service/evaluation/demo-manifest.json");
const fixture = read("../../infra/demo/accounts.json");
const realm = read("../../infra/keycloak/mediamesh-realm.json");

test("demo media have distinct pinned sources, credits and valid upload metadata", () => {
  const videos = manifest.items.filter(item => item.mediaType === "video");
  const photos = manifest.items.filter(item => !item.mediaType || item.mediaType === "image");
  assert.equal(photos.length, 500);
  assert.equal(videos.length, 2);
  assert.equal(manifest.items.length, photos.length + videos.length);
  for (const field of ["id", "filename", "source_page", "sha256"])
    assert.equal(new Set(manifest.items.map(item => item[field])).size, manifest.items.length, field);
  for (const item of manifest.items) {
    assert.match(item.sha256, /^[a-f0-9]{64}$/);
    assert.ok(item.creator && item.creator.length <= 255);
    assert.ok(item.title && item.title.length < 240);
    assert.ok((item.description || item.title).length <= 4000);
    assert.match(item.license, /^(CC BY|CC0|Public domain)/);
    assert.match(new URL(item.license_url || item.source_page).protocol, /^https?:$/);
    assert.equal(new URL(item.source_page).protocol, "https:");
    const download = new URL(item.download_url);
    assert.equal(download.protocol, "https:");
    assert.ok(["upload.wikimedia.org", "thumb.wikimedia.org", "www.nps.gov"].includes(download.hostname));
    assert.ok(!item.filename.includes("/") && !item.filename.includes(".."));
    assert.ok(item.filename.endsWith(item.mediaType === "video" ? ".mp4" : ".jpg"));
  }
});

test("realm imports only the provisioner; legacy accounts are retained for cleanup only", () => {
  assert.ok(realm.users.every(user => user.serviceAccountClientId));
  assert.equal(fixture.accounts.length, 7);
  assert.equal(realm.clients.find(client => client.clientId === "mediamesh-web").directAccessGrantsEnabled, false);
});
