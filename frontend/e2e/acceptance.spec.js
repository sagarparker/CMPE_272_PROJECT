import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

async function login(browser, username) {
  const context = await browser.newContext(),
    page = await context.newPage();
  let token;
  page.on("request", (request) => {
    if (request.url().endsWith("/api/me"))
      token = request.headers().authorization;
  });
  await page.goto("/");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill("local-demo-only");
  await page.locator("#kc-login").click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await expect.poll(() => token).toBeTruthy();
  const response = await page.request.get("/api/me", {
    headers: { Authorization: token },
  });
  expect(response.ok()).toBeTruthy();
  return { context, page, token, user: await response.json() };
}
async function grant(admin, target, roles) {
  const response = await admin.page.request.put(
    `/api/admin/users/${target.user.id}/roles`,
    { headers: { Authorization: admin.token }, data: { roles } },
  );
  expect(response.ok()).toBeTruthy();
}

test("SSO, role grants, image/video indexing, search, preview, download and revocation", async ({
  browser,
}) => {
  const employee = await login(browser, "employee");
  await expect(
    employee.page.getByText("Your account is ready.", { exact: false }),
  ).toBeVisible();
  const denied = await employee.page.request.post("/api/search", {
    headers: { Authorization: employee.token },
    data: { query: "red" },
  });
  expect(denied.status()).toBe(403);
  const uploader = await login(browser, "uploader"),
    researcher = await login(browser, "researcher"),
    admin = await login(browser, "admin");
  try {
    for (const [target, role] of [
      [uploader, "UPLOADER"],
      [researcher, "RESEARCHER"],
    ]) {
      const row = admin.page
        .locator(".user-row")
        .filter({ has: admin.page.getByText(target.user.email, { exact: true }) });
      await row.getByRole("checkbox", { name: role, exact: true }).check();
      await row.getByRole("button", { name: "Save roles" }).click();
      await expect(
        row.getByRole("checkbox", { name: role, exact: true }),
      ).toBeChecked();
    }
    await admin.page.getByRole("button", { name: "Refresh users" }).click();
    await expect(
      admin.page.getByText("uploader@mediamesh.local"),
    ).toBeVisible();
    await uploader.page.reload();
    await researcher.page.reload();
    await expect(
      uploader.page.getByRole("heading", { name: "Contribute to the archive" }),
    ).toBeVisible();
    const title = `Acceptance photo ${Date.now()}`;
    const subject = `Acceptance subject ${Date.now()}`;
    await uploader.page
      .getByLabel("Media file")
      .setInputFiles("e2e/fixtures/red.png");
    await uploader.page.getByLabel("Title", { exact: true }).fill(title);
    await uploader.page
      .getByLabel("Species", { exact: true })
      .fill(subject);
    await uploader.page
      .getByLabel("Location", { exact: true })
      .fill("Demo studio");
    await uploader.page
      .getByLabel("Usage and rights notes")
      .fill("Synthetic test fixture; internal review.");
    await uploader.page
      .getByRole("button", { name: "Upload media", exact: true })
      .click();
    await expect(
      uploader.page.locator(".asset-row").filter({ hasText: title }),
    ).toContainText("READY", { timeout: 180000 });
    await uploader.page
      .locator(".asset-row")
      .filter({ hasText: title })
      .getByRole("button", { name: "Edit", exact: true })
      .click();
    const editor = uploader.page.getByRole("dialog", { name: "Edit metadata" });
    await editor
      .getByLabel("Shot notes")
      .fill("Updated from the editorial portal");
    await editor.getByRole("button", { name: "Save changes" }).click();
    await expect(editor).not.toBeVisible();
    const listing = await uploader.page.request.get("/api/assets", {
      headers: { Authorization: uploader.token },
    });
    const photo = (await listing.json()).find((asset) => asset.title === title);
    expect(photo).toBeTruthy();
    expect(photo.description).toBe("Updated from the editorial portal");
    expect(
      (
        await uploader.page.request.post(
          `/api/assets/${photo.assetId}/complete`,
          { headers: { Authorization: uploader.token } },
        )
      ).status(),
    ).toBe(202);
    await researcher.page
      .getByLabel("Describe what you need")
      .fill("a solid red screen");
    await researcher.page.locator(".search-filters summary").click();
    await researcher.page
      .getByLabel("Species", { exact: true })
      .fill(subject);
    const searchReply = researcher.page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/search"),
    );
    await researcher.page
      .getByRole("button", { name: "Search archive" })
      .click();
    const searchResponse = await searchReply;
    expect(searchResponse.status()).toBe(200);
    const requestId = await searchResponse.headerValue("x-request-id");
    expect(requestId).toMatch(/^[a-fA-F0-9-]{16,64}$/);
    console.log("Search correlation requestId:", requestId);
    const card = researcher.page.locator(".result").filter({ hasText: title });
    await expect(card).toBeVisible({ timeout: 90000 });
    await card.getByRole("button", { name: "Preview", exact: true }).click();
    const preview = researcher.page.getByRole("dialog", {
      name: "Media preview",
    });
    await expect(preview.getByRole("img")).toBeVisible();
    await expect
      .poll(() => preview.getByRole("img").evaluate((img) => img.naturalWidth))
      .toBeGreaterThan(0);
    await preview.getByRole("button", { name: "Close", exact: true }).click();
    const access = await researcher.page.request.post(
      `/api/assets/${photo.assetId}/access-url?download=true`,
      { headers: { Authorization: researcher.token } },
    );
    const url = (await access.json()).url,
      download = await researcher.page.request.get(url);
    expect(download.ok()).toBeTruthy();
    expect(download.headers()["content-disposition"]).toContain("attachment");
    const videoData = await readFile("e2e/fixtures/red.mp4");
    const initiated = await uploader.page.request.post("/api/assets/initiate", {
      headers: { Authorization: uploader.token },
      data: {
        filename: "red.mp4",
        contentType: "video/mp4",
        title: `Acceptance video ${Date.now()}`,
        species: subject,
        location: "Demo studio",
      },
    });
    expect(initiated.ok()).toBeTruthy();
    const video = await initiated.json();
    expect(
      (
        await uploader.page.request.put(video.uploadUrl, {
          headers: { ...video.uploadHeaders, "Content-Type": "video/mp4", "If-None-Match": "*" },
          data: videoData,
        })
      ).ok(),
    ).toBeTruthy();
    expect(
      (
        await uploader.page.request.put(video.uploadUrl, {
          headers: { ...video.uploadHeaders, "Content-Type": "video/mp4", "If-None-Match": "*" },
          data: videoData,
        })
      ).status(),
    ).toBe(403);
    const overwrite = await uploader.page.request.put(video.uploadUrl, {
      headers: { ...video.uploadHeaders, "Content-Type": "video/mp4" },
      data: videoData,
    });
    expect([403, 409, 412]).toContain(overwrite.status());
    expect(
      (
        await uploader.page.request.post(
          `/api/assets/${video.assetId}/complete`,
          { headers: { Authorization: uploader.token } },
        )
      ).status(),
    ).toBe(202);
    await expect
      .poll(
        async () => {
          const response = await uploader.page.request.get(
            `/api/assets/${video.assetId}`,
            { headers: { Authorization: uploader.token } },
          );
          return (await response.json()).processingStatus;
        },
        { timeout: 180000 },
      )
      .toBe("READY");
    const search = await researcher.page.request.post("/api/search", {
      headers: { Authorization: researcher.token },
      data: {
        query: "a solid red screen",
        mediaType: "video",
        species: subject,
        limit: 10,
      },
    });
    expect(search.ok()).toBeTruthy();
    const results = (await search.json()).results;
    expect(
      results.some(
        (result) =>
          result.assetId === video.assetId && result.frameTimestampSeconds >= 0,
      ),
    ).toBeTruthy();
    const similar = await researcher.page.request.post(
      `/api/assets/${photo.assetId}/similar`,
      { headers: { Authorization: researcher.token } },
    );
    expect(similar.ok()).toBeTruthy();
    const related = (await similar.json()).results;
    expect(related.length).toBeGreaterThan(0);
    expect(related.every(result => result.assetId !== photo.assetId)).toBeTruthy();
    // Repeated runs create identical red fixtures; tied neighbors need not include this run's video.
    expect(related.some(result => result.score > 0.9)).toBeTruthy();
    const empty = await researcher.page.request.post("/api/search", {
      headers: { Authorization: researcher.token },
      data: { query: "red", species: "No such species 817" },
    });
    expect((await empty.json()).results).toEqual([]);
    await grant(admin, researcher, []);
    expect(
      (
        await researcher.page.request.post("/api/search", {
          headers: { Authorization: researcher.token },
          data: { query: "red" },
        })
      ).status(),
    ).toBe(403);
    const anonymous = await browser.newContext();
    expect(
      (await anonymous.request.get("http://localhost:8080/api/me")).status(),
    ).toBe(401);
    await anonymous.close();
  } finally {
    await grant(admin, researcher, []);
    await grant(admin, uploader, []);
    await Promise.all([
      employee.context.close(),
      uploader.context.close(),
      researcher.context.close(),
      admin.context.close(),
    ]);
  }
});
