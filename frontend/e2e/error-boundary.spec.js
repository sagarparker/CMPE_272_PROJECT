import { test, expect } from "@playwright/test";
import { build } from "vite";

test("render failures show a recoverable boundary without backend calls", async ({
  page,
}) => {
  const result = await build({
    configFile: false,
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    logLevel: "silent",
    build: {
      write: false,
      lib: {
        entry: "e2e/boundary-harness.jsx",
        name: "BoundaryProbe",
        formats: ["iife"],
      },
    },
  });
  const outputs = Array.isArray(result) ? result : [result];
  const script = outputs
    .flatMap((output) => output.output)
    .find((asset) => asset.type === "chunk").code;
  const apiRequests = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/")) apiRequests.push(request.url());
  });
  await page.route("**/boundary-test", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<html><body><div id="root"></div><script>${script.replaceAll("</script", "<\\/script")}</script></body></html>`,
    }),
  );
  await page.goto("/boundary-test");
  await expect(page.getByRole("alert")).toContainText(
    "The workspace could not be displayed",
  );
  await page.evaluate(() => {
    window.boundaryShouldThrow = false;
  });
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(page.getByText("Workspace recovered")).toBeVisible();
  expect(apiRequests).toEqual([]);
});
