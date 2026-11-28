import { test, expect } from "@playwright/test";
import { openOauthPage as open } from "./oauth-harness";

const member = { id: "member", email: "member@example.org", displayName: "New Member", roles: [], requestedRoles: [], requestStatus: "NONE", primaryAdmin: false };

test("signed-out visitors use the designed Keycloak login instead of a plain welcome page", async ({ page }) => {
  await open(page, member, false);
  expect(await page.evaluate(() => window.__authInit.onLoad)).toBe("login-required");
  await expect(page.getByRole("heading", { name: "Welcome to MediaMesh" })).toHaveCount(0);
});

test("new user requests both roles and waits for approval", async ({ page }) => {
  let current = { ...member };
  await open(page, current);
  await page.route("**/api/me", route => route.fulfill({ json: current }));
  await page.route("**/api/me/access-request", async route => {
    expect(route.request().postDataJSON()).toEqual({ roles: ["UPLOADER", "RESEARCHER"] });
    current = { ...current, requestedRoles: ["UPLOADER", "RESEARCHER"], requestStatus: "PENDING" };
    await route.fulfill({ status: 201, json: current });
  });
  await page.getByRole("checkbox", { name: /Uploader/ }).check();
  await page.getByRole("checkbox", { name: /Researcher/ }).check();
  await page.getByRole("button", { name: "Request access", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Your access request is pending" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("Your sign-in request has not yet been approved");
  await expect(page.getByRole("button", { name: "Upload", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Search", exact: true })).toHaveCount(0);
  current = { ...current, roles: ["UPLOADER", "RESEARCHER"], requestStatus: "APPROVED" };
  await page.getByRole("button", { name: "Refresh access" }).click();
  await expect(page.getByRole("button", { name: "Upload", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Search", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Search the archive" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Access", exact: true })).toHaveCount(0);
});

test("administrator approves requests without extra-admin controls", async ({ page }) => {
  let requests = [{ id: "request-1", user: member, roles: ["UPLOADER", "RESEARCHER"], status: "PENDING" }];
  const admin = { ...member, id: "admin", displayName: "Sagar Parker", email: "sagar.parker@sjsu.edu", roles: ["ADMIN"], primaryAdmin: true };
  await page.route("**/api/admin/users", route => route.fulfill({ json: [admin, member] }));
  await page.route("**/api/admin/access-requests", route => route.fulfill({ json: requests }));
  await page.route("**/api/admin/access-requests/request-1/decision", async route => {
    expect(route.request().postDataJSON()).toEqual({ approve: true });
    requests = [];
    await route.fulfill({ status: 204 });
  });
  await open(page, admin);
  await expect(page.getByRole("heading", { name: "Pending access requests (1)" })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "ADMIN", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Create account" })).toHaveCount(0);
  await page.getByRole("button", { name: "Approve request" }).click();
  await expect(page.getByRole("status")).toContainText("Approved access for New Member");
  await expect(page.getByText("No requests awaiting approval.")).toBeVisible();
});


test("returning pending users see approval error and cannot open workspace", async ({ page }) => {
  await open(page, { ...member, requestedRoles: ["RESEARCHER"], requestStatus: "PENDING" });
  await expect(page.getByRole("alert")).toContainText("Your sign-in request has not yet been approved");
  await expect(page.getByRole("button", { name: "Search", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Upload", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
});

test("API rejection shows an error without sending the user back to login", async ({ page }) => {
  await page.route("**/api/logout", route => route.fulfill({ status: 200, json: {} }));
  await open(page, member);
  await expect(page.getByRole("heading", { name: "Choose your workspace access" })).toBeVisible();
  await page.route("**/api/me", route => route.fulfill({ status: 401, json: { error: { code: "UNAUTHORIZED" } } }));
  await page.getByRole("button", { name: "Refresh access" }).click();
  await expect(page.getByRole("alert")).toContainText("Your sign-in could not be verified");
  expect(await page.evaluate(() => window.__logoutCalled)).not.toBe(true);
});


test("administrator can find a member and save both access roles", async ({ page }) => {
  const admin = { ...member, id: "admin", displayName: "Workspace Owner", email: "sagar.parker@sjsu.edu", roles: ["ADMIN"], primaryAdmin: true };
  let target = { ...member };
  await page.route("**/api/admin/users", route => route.fulfill({ json: [target, admin] }));
  await page.route("**/api/admin/access-requests", route => route.fulfill({ json: [] }));
  let saved = false;
  await page.route("**/api/admin/users/member/roles", route => {
    expect(route.request().postDataJSON()).toEqual({ roles: ["UPLOADER", "RESEARCHER"] });
    target = { ...target, roles: ["UPLOADER", "RESEARCHER"] }; saved = true;
    return route.fulfill({ json: target });
  });
  await open(page, admin);
  const rows = page.locator(".admin-members .admin-member-row");
  await expect(rows).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "Your workspace roles" })).toBeVisible();
  await page.getByRole("searchbox", { name: "Search members" }).fill("member@example.org");
  await expect(rows).toHaveCount(1);
  await rows.getByRole("checkbox", { name: "UPLOADER", exact: true }).check();
  await rows.getByRole("checkbox", { name: "RESEARCHER", exact: true }).check();
  await rows.getByRole("button", { name: "Save roles" }).click();
  await expect(page.getByRole("status")).toContainText("Saved roles for New Member");
  expect(saved).toBe(true);
});


test("admin manages personal workspace roles inside Admin without an Access tab", async ({ page }) => {
  let admin = { ...member, id: "admin", displayName: "Workspace Owner", email: "sagar.parker@sjsu.edu", roles: ["ADMIN"], primaryAdmin: true };
  await page.route("**/api/admin/users", route => route.fulfill({ json: [admin] }));
  await page.route("**/api/admin/access-requests", route => route.fulfill({ json: [] }));
  await open(page, admin);
  await page.route("**/api/me", route => route.fulfill({ json: admin }));
  const personal = page.getByRole("region", { name: "Your workspace roles" });
  await expect(personal).toBeVisible();
  await expect(page.getByRole("button", { name: "Access", exact: true })).toHaveCount(0);
  await page.route("**/api/admin/users/admin/roles", route => {
    expect(route.request().postDataJSON()).toEqual({ roles: ["RESEARCHER", "ADMIN"] });
    admin = { ...admin, roles: ["ADMIN", "RESEARCHER"] };
    return route.fulfill({ json: admin });
  });
  await personal.getByRole("checkbox", { name: "RESEARCHER", exact: true }).check();
  await personal.getByRole("button", { name: "Save workspace roles" }).click();
  await expect(page.getByRole("button", { name: "Search", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Admin", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Access", exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Manage library access" })).toBeVisible();
});


test("a user with one role sees approved access and can request only the remaining role", async ({ page }) => {
  await open(page, { ...member, roles: ["UPLOADER"], requestStatus: "APPROVED" });
  await page.getByRole("button", { name: "Access", exact: true }).click();
  const uploader = page.getByRole("checkbox", { name: "Uploader", exact: true });
  await expect(uploader).toBeChecked();
  await expect(uploader).toBeDisabled();
  await expect(page.locator(".role-option-approved")).toContainText("Approved");
  await expect(page.getByRole("checkbox", { name: "Researcher", exact: true })).toBeEnabled();
  await page.route("**/api/me/access-request", route => {
    expect(route.request().postDataJSON()).toEqual({ roles: ["RESEARCHER"] });
    return route.fulfill({ status: 201, json: member });
  });
  await page.getByRole("checkbox", { name: "Researcher", exact: true }).check();
  await page.getByRole("button", { name: "Request access", exact: true }).click();
});
