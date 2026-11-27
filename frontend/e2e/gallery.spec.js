import { test, expect } from "@playwright/test";

const assets = [
  { assetId: "gallery-bird", title: "Birds | Puffin portrait", mediaType: "image", score: 0.32 },
  { assetId: "gallery-flower", title: "Plants | Sunflower head", mediaType: "image", score: 0.29 },
];

async function gallery(page) {
  await page.route("**/api/me", route => route.fulfill({ json: { id: "gallery-test", displayName: "Gallery tester", roles: ["RESEARCHER"] } }));
  await page.route("**/api/search", route => route.fulfill({ json: { results: assets } }));
  await page.route("**/api/assets/*", route => {
    const asset = assets.find(asset => route.request().url().endsWith(`/${asset.assetId}`));
    return route.fulfill({ json: { ...asset, description: "Source caption for the photograph.", contributor: "Test photographer", usageNote: "CC BY 4.0. Credit: Test photographer." } });
  });
  await page.route("**/api/assets/*/access-url", route => route.fulfill({ json: { url: "http://localhost:8080/gallery-test.jpg" } }));
  await page.route("**/gallery-test.jpg", route => route.fulfill({ path: "e2e/fixtures/red.png", contentType: "image/png" }));
  await page.goto("/");
  await page.locator("#username").fill("employee");
  await page.locator("#password").fill("local-demo-only");
  await page.locator("#kc-login").click();
  await page.getByRole("button", { name: "Sign out" }).waitFor();
}

test("search shows photographs immediately; modal supports navigation, credits and Escape", async ({ page }) => {
  await gallery(page);
  await page.getByRole("button", { name: "Birds", exact: true }).click();
  await expect(page.getByLabel("Describe what you need")).toHaveValue("birds in flight");
  const first = page.locator(".result").first();
  await expect.poll(() => first.locator("img").evaluate(img => img.naturalWidth)).toBeGreaterThan(0);
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Compact", exact: true }).click();
  await expect(page.locator(".results")).toHaveClass(/gallery-compact/);
  const trigger = page.getByRole("button", { name: "Preview Birds | Puffin portrait", exact: true });
  await trigger.click();
  const modal = page.getByRole("dialog", { name: "Media preview" });
  await expect(modal).toBeVisible();
  await expect(modal.getByRole("button", { name: "Previous asset" })).toBeDisabled();
  await expect(modal).toContainText("Test photographer");
  await page.keyboard.press("ArrowRight");
  await expect(modal.getByRole("heading")).toHaveText("Plants | Sunflower head");
  await expect(modal.getByRole("button", { name: "Next asset" })).toBeDisabled();
  await page.keyboard.press("ArrowLeft");
  await expect(modal.getByRole("heading")).toHaveText("Birds | Puffin portrait");
  await page.keyboard.press("Escape");
  await expect(modal).not.toBeVisible();
  await expect(trigger).toBeFocused();
});

test("expired thumbnail can renew access and load without losing results", async ({ page }) => {
  await gallery(page);
  let calls = 0;
  await page.route("**/api/assets/gallery-bird/access-url", route => {
    calls++;
    return route.fulfill({ json: { url: `http://localhost:8080/${calls === 1 ? "expired" : "gallery-test"}.jpg` } });
  });
  await page.route("**/expired.jpg", route => route.fulfill({ status: 403, body: "Expired" }));
  await page.getByRole("button", { name: "Birds", exact: true }).click();
  const first = page.locator(".result").first();
  await first.getByRole("button", { name: "Retry preview" }).click();
  await expect.poll(() => first.locator("img").evaluate(img => img.naturalWidth)).toBeGreaterThan(0);
  expect(calls).toBe(2);
  await expect(page.locator(".result")).toHaveCount(2);
});

test("mobile gallery fits the viewport and handles empty searches", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await gallery(page);
  await page.getByRole("button", { name: "Birds", exact: true }).click();
  await expect(page.locator(".result")).toHaveCount(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Preview Birds | Puffin portrait", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.route("**/api/search", route => route.fulfill({ json: { results: [] } }));
  await page.getByRole("button", { name: "Oceans", exact: true }).click();
  await expect(page.getByText("A new angle might help.")).toBeVisible();
  await expect(page.locator(".result")).toHaveCount(0);
});
