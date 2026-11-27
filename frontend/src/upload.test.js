import test from "node:test";
import assert from "node:assert/strict";
import { metadata, uploadFile } from "./upload.js";
test("metadata preserves notes and sends empty optional fields as null", () => {
  const form = new FormData();
  form.set("title", "Elephants");
  form.set("usageNote", "Editorial review only");
  const result = metadata(form);
  assert.equal(result.title, "Elephants");
  assert.equal(result.usageNote, "Editorial review only");
  assert.equal(result.capturedAt, null);
});

test("uploads send Azure's required header while preserving create-only PUT", async () => {
  const previous = globalThis.XMLHttpRequest;
  const headers = {};
  globalThis.XMLHttpRequest = class {
    upload = {};
    status = 201;
    open(method) { assert.equal(method, "PUT"); }
    setRequestHeader(name, value) { headers[name] = value; }
    send() { this.onload(); }
  };
  try {
    await uploadFile("https://storage.example/blob", {type:"image/jpeg"}, () => {}, {"x-ms-blob-type":"BlockBlob"});
    assert.equal(headers["x-ms-blob-type"], "BlockBlob");
    assert.equal(headers["If-None-Match"], "*");
    assert.equal(headers["Content-Type"], "image/jpeg");
  } finally { globalThis.XMLHttpRequest = previous; }
});
