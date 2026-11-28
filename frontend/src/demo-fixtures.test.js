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

test("each demo domain has its own uploader; researcher and browser login stay least privilege", () => {
  const uploaders = fixture.accounts.filter(account => account.domain);
  const collectionSizes = { wildlife: 122, plants: 75, oceans: 45, marine: 75, birds: 110, landscapes: 75 };
  assert.equal(uploaders.length, 6);
  assert.equal(new Set(uploaders.map(account => account.domain)).size, 6);
  for (const account of fixture.accounts) {
    assert.deepEqual(account.roles, account.domain ? ["UPLOADER"] : ["RESEARCHER"]);
    const imported = realm.users.find(user => user.username === account.username);
    assert.equal(imported.email, account.email);
    assert.equal(imported.lastName, account.lastName);
    if (account.domain)
      assert.equal(manifest.items.filter(item => item.domain === account.domain).length,
        collectionSizes[account.domain]);
  }
  assert.equal(realm.clients.find(client => client.clientId === "mediamesh-web").directAccessGrantsEnabled, false);
});
