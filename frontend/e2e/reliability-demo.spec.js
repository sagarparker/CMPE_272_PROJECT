import { test, expect } from "@playwright/test";

const enabled = process.env.RUN_RELIABILITY_DEMO === "1";
test("local delay: bulkhead rejects excess requests while identity remains responsive", async ({
  browser,
}) => {
  test.skip(
    !enabled,
    "Run explicitly with compose.reliability-demo.yaml after the normal acceptance test seeds READY media.",
  );
  const contexts = [];
  async function login(username) {
    const context = await browser.newContext();
    contexts.push(context);
    const page = await context.newPage();
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
    return { page, token, user: await response.json() };
  }
  let admin, researcher;
  try {
    researcher = await login("researcher");
    admin = await login("admin");
    const roles = await admin.page.request.put(
      `/api/admin/users/${researcher.user.id}/roles`,
      {
        headers: { Authorization: admin.token },
        data: { roles: ["RESEARCHER"] },
      },
    );
    expect(roles.ok()).toBeTruthy();
    const searches = Array.from({ length: 20 }, async () => {
      const started = Date.now();
      const response = await researcher.page.request.post("/api/search", {
        headers: { Authorization: researcher.token },
        data: { query: "red" },
      });
      return {
        status: response.status(),
        body: await response.json(),
        elapsed: Date.now() - started,
      };
    });
    const started = Date.now();
    const identity = await admin.page.request.get("/api/me", {
      headers: { Authorization: admin.token },
    });
    expect(identity.ok()).toBeTruthy();
    expect(Date.now() - started).toBeLessThan(1000);
    const results = await Promise.all(searches);
    const busy = results.filter((r) => r.body.error?.code === "ML_SEARCH_BUSY");
    expect(busy.length).toBeGreaterThanOrEqual(15);
    expect(
      busy.every((r) => r.status === 503 && r.elapsed < 1000),
    ).toBeTruthy();
    expect(results.every((r) => r.status === 503)).toBeTruthy();
  } finally {
    if (admin && researcher)
      await admin.page.request.put(
        `/api/admin/users/${researcher.user.id}/roles`,
        {
          headers: { Authorization: admin.token },
          data: { roles: researcher.user.roles },
        },
      );
    await Promise.all(contexts.map((context) => context.close()));
  }
});

test("local outage: breaker fails fast and recovers after ML restart", async ({
  browser,
}) => {
  test.skip(
    process.env.RUN_CIRCUIT_DEMO !== "1",
    "Explicit opt-in: this test stops and restarts the local ML API.",
  );
  const { execFileSync } = await import("node:child_process");
  const { resolve } = await import("node:path");
  const contexts = [];
  async function login(username) {
    const context = await browser.newContext();
    contexts.push(context);
    const page = await context.newPage();
    let token;
    page.on("request", (r) => {
      if (r.url().endsWith("/api/me")) token = r.headers().authorization;
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
    return { page, token, user: await response.json() };
  }
  const compose = (...args) =>
    execFileSync("docker", ["compose", ...args], {
      cwd: resolve(import.meta.dirname, "../.."),
      stdio: "pipe",
    });
  let admin,
    researcher,
    stopped = false;
  try {
    researcher = await login("researcher");
    admin = await login("admin");
    await admin.page.request.put(
      `/api/admin/users/${researcher.user.id}/roles`,
      {
        headers: { Authorization: admin.token },
        data: { roles: ["RESEARCHER"] },
      },
    );
    const search = () =>
      researcher.page.request.post("/api/search", {
        headers: { Authorization: researcher.token },
        data: { query: "red" },
      });
    expect((await search()).ok()).toBeTruthy();
    compose("stop", "ml-api");
    stopped = true;
    for (let i = 0; i < 10; i++) {
      const response = await search();
      expect(response.status()).toBe(503);
      expect((await response.json()).error.code).toBe("ML_SEARCH_UNAVAILABLE");
    }
    const started = Date.now();
    expect((await search()).status()).toBe(503);
    expect(Date.now() - started).toBeLessThan(500);
    compose("start", "ml-api");
    stopped = false;
    await expect
      .poll(async () => (await search()).status(), {
        timeout: 90000,
        intervals: [1000, 2000, 5000],
      })
      .toBe(200);
    expect((await search()).status()).toBe(200);
  } finally {
    if (stopped) compose("start", "ml-api");
    if (admin && researcher)
      await admin.page.request.put(
        `/api/admin/users/${researcher.user.id}/roles`,
        {
          headers: { Authorization: admin.token },
          data: { roles: researcher.user.roles },
        },
      );
    await Promise.all(contexts.map((context) => context.close()));
  }
});
