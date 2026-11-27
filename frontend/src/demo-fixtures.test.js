import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = relative => JSON.parse(readFileSync(new URL(relative, import.meta.url)));
const manifest = read("../../ml-service/evaluation/demo-manifest.json");
const fixture = read("../../infra/demo/accounts.json");
const realm = read("../../infra/keycloak/mediamesh-realm.json");

test("demo media have distinct pinned sources, credits and valid upload metadata", () => {
  assert.equal(manifest.items.length, 50);
  for (const field of ["id", "filename", "source_page", "sha256"])
    assert.equal(new Set(manifest.items.map(item => item[field])).size, 50, field);
  assert.equal(manifest.items.filter(item => item.mediaType === "video").length, 2);
  for (const item of manifest.items) {
    assert.match(item.sha256, /^[a-f0-9]{64}$/);
    assert.ok(item.creator && item.creator.length <= 255);
    assert.ok(item.title && item.title.length < 240);
    assert.ok((item.description || item.title).length <= 4000);
    assert.match(item.license, /^(CC BY|CC0|Public domain)/);
    assert.equal(new URL(item.source_page).protocol, "https:");
    const download = new URL(item.download_url);
    assert.equal(download.protocol, "https:");
    assert.ok(["upload.wikimedia.org", "thumb.wikimedia.org", "www.nps.gov"].includes(download.hostname));
    assert.ok(!item.filename.includes("/") && !item.filename.includes(".."));
  }
});

test("each demo domain has its own uploader; researcher and browser login stay least privilege", () => {
  const uploaders = fixture.accounts.filter(account => account.domain);
  assert.equal(uploaders.length, 6);
  assert.equal(new Set(uploaders.map(account => account.domain)).size, 6);
  for (const account of fixture.accounts) {
    assert.deepEqual(account.roles, account.domain ? ["UPLOADER"] : ["RESEARCHER"]);
    const imported = realm.users.find(user => user.username === account.username);
    assert.equal(imported.email, account.email);
    assert.equal(imported.lastName, account.lastName);
    if (account.domain)
      assert.equal(manifest.items.filter(item => item.domain === account.domain).length,
        account.domain === "wildlife" ? 10 : 8);
  }
  assert.equal(realm.clients.find(client => client.clientId === "mediamesh-web").directAccessGrantsEnabled, false);
});
