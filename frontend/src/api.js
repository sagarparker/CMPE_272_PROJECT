import Keycloak from "keycloak-js";
export const auth = new Keycloak({
  url: `${window.location.origin}/auth`,
  realm: "mediamesh",
  clientId: "mediamesh-web",
});
export async function api(path, options = {}) {
  await auth.updateToken(30);
  const response = await fetch(`/api${path}`, {
    ...options,
    signal: options.signal || AbortSignal.timeout(10000),
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${auth.token}`,
      ...options.headers,
    },
  });
  if (response.status === 401) {
    await auth.logout({ redirectUri: window.location.origin });
    throw new Error("Please sign in again.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      body?.error?.message ||
        (response.status === 403
          ? "You do not have access to this action."
          : `Request failed (${response.status})`),
    );
  return body;
}
export const post = (path, body = {}) =>
  api(path, { method: "POST", body: JSON.stringify(body) });
