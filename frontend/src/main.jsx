import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { auth, api, post } from "./api";
import { uploadFile, metadata } from "./upload";
import "./styles.css";
import ErrorBoundary from "./ErrorBoundary";
import { ResultCard, MediaPreview } from "./Gallery";

const roles = ["ADMIN", "UPLOADER", "RESEARCHER"];
function ErrorNotice({ error }) {
  return error ? (
    <div role="alert" className="notice error">
      {error}
    </div>
  ) : null;
}
function MetadataFields({ asset = {} }) {
  return (
    <>
      <label>
        Title
        <input
          name="title"
          required
          maxLength="255"
          defaultValue={asset.title}
        />
      </label>
      <label>
        Shot notes
        <textarea
          name="description"
          maxLength="4000"
          defaultValue={asset.description}
        />
      </label>
      <div className="fields">
        <label>
          Species
          <input name="species" maxLength="255" defaultValue={asset.species} />
        </label>
        <label>
          Location
          <input
            name="location"
            maxLength="255"
            defaultValue={asset.location}
          />
        </label>
        <label>
          Capture date
          <input
            type="date"
            name="capturedAt"
            defaultValue={asset.capturedAt}
          />
        </label>
        <label>
          Contributor
          <input
            name="contributor"
            maxLength="255"
            defaultValue={asset.contributor}
          />
        </label>
      </div>
      <label>
        Usage and rights notes
        <textarea
          name="usageNote"
          maxLength="4000"
          defaultValue={asset.usageNote}
        />
      </label>
    </>
  );
}
function Upload() {
  const [assets, setAssets] = useState([]),
    [busy, setBusy] = useState(false),
    [progress, setProgress] = useState(0),
    [error, setError] = useState(""),
    [editing, setEditing] = useState(null),
    [offset, setOffset] = useState(0);
  const load = () =>
    api(`/assets?offset=${offset}`)
      .then(setAssets)
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [offset]);
  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    setProgress(0);
    const form = event.currentTarget,
      data = new FormData(form),
      file = data.get("file");
    try {
      if (!file?.size || file.size > 100000000)
        throw new Error("Choose a non-empty file up to 100 MB.");
      const created = await post("/assets/initiate", {
        ...metadata(data),
        filename: file.name,
        contentType: file.type,
      });
      await uploadFile(created.uploadUrl, file, setProgress, created.uploadHeaders);
      await post(`/assets/${created.assetId}/complete`);
      form.reset();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function save(event) {
    event.preventDefault();
    setError("");
    try {
      await api(`/assets/${editing.assetId}`, {
        method: "PUT",
        body: JSON.stringify(metadata(new FormData(event.currentTarget))),
      });
      setEditing(null);
      await load();
    } catch (e) {
      setError(e.message);
    }
  }
  return (
    <>
      <div className="section-title">
        <h2>Contribute to the archive</h2>
        <p>Upload a photograph or a documentary clip up to 3 minutes.</p>
      </div>
      <ErrorNotice error={error} />
      <div className="columns">
        <section className="panel">
          <form onSubmit={submit}>
            <label>
              Media file
              <input
                name="file"
                type="file"
                required
                accept="image/jpeg,image/png,video/mp4,video/quicktime"
              />
            </label>
            <MetadataFields />
            <button disabled={busy}>
              {busy ? `Uploading ${progress}%` : "Upload media"}
            </button>
            {busy && (
              <progress
                value={progress}
                max="100"
                aria-label="Upload progress"
              />
            )}
          </form>
        </section>
        <section className="panel">
          <h3>Your contributions</h3>
          {assets.length === 0 && <p>No contributions on this page.</p>}
          {assets.map((asset) => (
            <article className="asset-row" key={asset.assetId}>
              <div>
                <strong>{asset.title}</strong>
                <p>
                  {asset.species || asset.mediaType} ·{" "}
                  {asset.location || "Location unspecified"}
                </p>
                <span className={`badge ${asset.processingStatus}`}>
                  {asset.processingStatus}
                </span>
                {asset.processingStatus === "FAILED" && (
                  <p>
                    Indexing failed. Check the file format and duration, then
                    upload a corrected file.
                  </p>
                )}
              </div>
              <button className="secondary" onClick={() => setEditing(asset)}>
                Edit
              </button>
            </article>
          ))}
          <div className="actions">
            <button
              className="secondary"
              disabled={!offset}
              onClick={() => setOffset(offset - 50)}
            >
              Previous
            </button>
            <button
              className="secondary"
              disabled={assets.length < 50}
              onClick={() => setOffset(offset + 50)}
            >
              Next
            </button>
          </div>
        </section>
      </div>
      {editing && (
        <dialog open aria-label="Edit metadata">
          <form key={editing.assetId} onSubmit={save}>
            <h3>Edit metadata</h3>
            <MetadataFields asset={editing} />
            <div className="actions">
              <button>Save changes</button>
              <button
                type="button"
                className="secondary"
                onClick={() => setEditing(null)}
              >
                Cancel
              </button>
            </div>
          </form>
        </dialog>
      )}
    </>
  );
}
function Research() {
  const [results, setResults] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [previewIndex, setPreviewIndex] = useState(null),
    [query, setQuery] = useState(""),
    [resultLabel, setResultLabel] = useState(""),
    [density, setDensity] = useState("comfortable");
  const form = useRef(null);
  const request = useRef(0);
  async function search(event, suggestion) {
    event?.preventDefault();
    const id = ++request.current;
    setBusy(true); setError(""); setPreviewIndex(null);
    const data = new FormData(form.current);
    if (suggestion) { data.set("query", suggestion); setQuery(suggestion); }
    const body = Object.fromEntries([...data].map(([key, value]) => [key, value || null]));
    try {
      const response = await post("/search", { ...body, limit: 20 });
      if (id === request.current) { setResults(response.results); setResultLabel(body.query); }
    } catch (e) {
      if (id === request.current) setError(e.message);
    } finally {
      if (id === request.current) setBusy(false);
    }
  }
  async function download(asset) {
    setError("");
    try {
      const details = await api(`/assets/${asset.assetId}`);
      if (!window.confirm(`Usage notes: ${details.usageNote || "No rights information supplied."}\nVerify licensing before publication. Continue?`)) return;
      const access = await post(`/assets/${asset.assetId}/access-url?download=true`);
      const link = document.createElement("a");
      link.href = access.url; link.rel = "noreferrer"; link.click();
    } catch (e) { setError(e.message); }
  }
  async function similar(asset) {
    const id = ++request.current;
    setError(""); setBusy(true); setPreviewIndex(null);
    try {
      const response = await post(`/assets/${asset.assetId}/similar`);
      if (id === request.current) { setResults(response.results); setResultLabel(`Related to ${asset.title}`); }
    } catch (e) { if (id === request.current) setError(e.message); }
    finally { if (id === request.current) setBusy(false); }
  }
  const topics = [["Wildlife", "elephants in the savanna"], ["Botanical", "flowers and plants"],
    ["Oceans", "ocean waves"], ["Marine life", "sea turtle underwater"],
    ["Birds", "birds in flight"], ["Landscapes", "mountains and valleys"]];
  return (
    <section className="research-workspace">
      <div className="discovery-heading">
        <div><span className="eyebrow">A world worth exploring</span>
          <h2>Find your next story<span>.</span></h2>
          <p>From the wild to the underwater world. Describe a scene and see where it takes you.</p></div>
        <span className="archive-stamp">THE EDITORIAL<br />COLLECTION / 01</span>
      </div>
      <ErrorNotice error={error} />
      <form ref={form} className="panel search discovery-search" onSubmit={search}>
        <label htmlFor="archive-query">Describe what you need</label>
        <div className="query-row">
          <span aria-hidden="true" className="search-icon">⌕</span>
          <input id="archive-query" name="query" required maxLength="1000" value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder="Try ‘birds in flight over water’" />
          <button disabled={busy}>{busy ? "Searching…" : "Search archive"}<span aria-hidden="true"> ↗</span></button>
        </div>
        <div className="search-extras">
          <div className="topic-chips" aria-label="Suggested searches">
            <span>Explore</span>{topics.map(([label, prompt]) => <button key={label} type="button"
              className="topic-chip" disabled={busy} onClick={() => search(null, prompt)}>{label}</button>)}
          </div>
          <details className="search-filters"><summary>Refine search</summary>
            <div className="fields">
              <label>Media type<select name="mediaType"><option value="">All media</option><option value="image">Photographs</option><option value="video">Video</option></select></label>
              <label>Species<input name="species" maxLength="255" /></label>
              <label>Location<input name="location" maxLength="255" /></label>
              <label>Captured on or after<input type="date" name="capturedAfter" /></label>
            </div>
          </details>
        </div>
      </form>
      {results && <div className="gallery-toolbar">
        <div><h3>{resultLabel.startsWith("Related to ") ? "Keep exploring" : `Results for “${resultLabel}”`}</h3>
          <p role="status">{results.length} matching assets · Sorted by relevance</p></div>
        <div className="density-toggle" role="group" aria-label="Gallery layout">
          <button className="secondary" aria-pressed={density === "comfortable"} onClick={() => setDensity("comfortable")}>Comfortable</button>
          <button className="secondary" aria-pressed={density === "compact"} onClick={() => setDensity("compact")}>Compact</button>
        </div>
      </div>}
      {busy && <div className="gallery-loading" role="status">Finding moments in the archive<span>…</span></div>}
      {results?.length === 0 && !busy && <div className="gallery-empty"><span aria-hidden="true">⌕</span>
        <h3>A new angle might help.</h3><p>Try a broader description or remove a filter to explore more of the archive.</p></div>}
      {!results && !busy && <div className="discovery-empty"><span className="eyebrow">Start with curiosity</span>
        <h3>Every image has a story.<br />What will yours be?</h3><p>Choose a subject above, or search in your own words.</p>
        <div className="discovery-coordinates" aria-hidden="true">WILDLIFE / BOTANY / OCEANS / THE NATURAL WORLD</div></div>}
      <div className={`results gallery-${density}`} aria-busy={busy}>
        {results?.map((asset, index) => <ResultCard key={asset.assetId} asset={asset}
          onPreview={() => setPreviewIndex(index)} onDownload={() => download(asset)} onRelated={() => similar(asset)} />)}
      </div>
      {!!results?.length && <p className="gallery-footnote">A different perspective, one frame at a time. Similarity scores express ranking, not certainty.</p>}
      {previewIndex != null && results?.[previewIndex] && <MediaPreview asset={results[previewIndex]}
        index={previewIndex} total={results.length} onClose={() => setPreviewIndex(null)}
        onPrevious={() => setPreviewIndex(index => Math.max(0, index - 1))}
        onNext={() => setPreviewIndex(index => Math.min(results.length - 1, index + 1))}
        onDownload={() => download(results[previewIndex])} />}
    </section>
  );
}
function CreateAccount({ me, onCreated }) {
  const [created, setCreated] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    setError("");
    setCreated(null);
    setBusy(true);
    try {
      const account = await api("/admin/users", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(form))),
      });
      setCreated(account);
      form.reset();
      onCreated();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <h3>Create an account</h3>
      <p>
        Share the temporary password privately. At first sign-in the person
        sets their own password and enrolls an authenticator app; later
        sign-ins use both.
      </p>
      <ErrorNotice error={error} />
      <form onSubmit={submit}>
        <div className="fields">
          <label>
            Username
            <input name="username" required pattern="[a-z0-9][a-z0-9._\-]{2,39}"
              title="3–40 lowercase letters, digits, dots, hyphens or underscores" />
          </label>
          <label>
            Email
            <input name="email" type="email" required maxLength="254" />
          </label>
          <label>
            First name
            <input name="firstName" required maxLength="80" />
          </label>
          <label>
            Last name
            <input name="lastName" required maxLength="80" />
          </label>
          <label>
            Role
            <select name="role" defaultValue="RESEARCHER">
              <option value="RESEARCHER">Researcher</option>
              <option value="UPLOADER">Uploader</option>
              {me.primaryAdmin && <option value="ADMIN">Administrator</option>}
            </select>
          </label>
        </div>
        <button disabled={busy}>Create account</button>
      </form>
      {created && (
        <div role="status" className="notice">
          <p>
            Created <strong>{created.username}</strong>. Temporary password
            (shown once): <code>{created.temporaryPassword}</code>
          </p>
          <button className="secondary" type="button"
            onClick={() => navigator.clipboard?.writeText(created.temporaryPassword)}>
            Copy password
          </button>
        </div>
      )}
    </section>
  );
}
function Admin({ me, onChanged }) {
  const [users, setUsers] = useState([]),
    [error, setError] = useState(""),
    [status, setStatus] = useState("");
  const load = () =>
    api("/admin/users")
      .then(setUsers)
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);
  async function save(event, user) {
    event.preventDefault();
    setError("");
    setStatus("");
    const assigned = new FormData(event.currentTarget).getAll("roles");
    // A locked (disabled) ADMIN checkbox is not submitted; keep the role unchanged.
    const adminLocked = !me.primaryAdmin || user.primaryAdmin;
    if (adminLocked && user.roles.includes("ADMIN") && !assigned.includes("ADMIN"))
      assigned.push("ADMIN");
    try {
      await api(`/admin/users/${user.id}/roles`, {
        method: "PUT",
        body: JSON.stringify({ roles: assigned }),
      });
      setStatus(`Saved roles for ${user.displayName}.`);
      // Reload the list and your own access, so tab changes appear immediately.
      await Promise.all([load(), onChanged()]);
    } catch (e) {
      setError(e.message);
    }
  }
  const canDelete = (user) =>
    user.id !== me.id &&
    !user.primaryAdmin &&
    (me.primaryAdmin || !user.roles.includes("ADMIN"));
  async function remove(user) {
    setError("");
    setStatus("");
    if (
      !window.confirm(
        `Delete ${user.displayName} (${user.email})?\n\nThey will no longer be able to sign in. ` +
          "Media they uploaded stays in the library. This cannot be undone.",
      )
    )
      return;
    try {
      await api(`/admin/users/${user.id}`, { method: "DELETE" });
      setStatus(`Deleted ${user.displayName}.`);
      await load();
    } catch (e) {
      setError(e.message);
    }
  }
  return (
    <>
      <div className="section-title">
        <h2>Manage library access</h2>
        <p>
          Create accounts for researchers and uploaders. Role changes apply on
          their next API request.
          {!me.primaryAdmin &&
            " Only the primary administrator can create or change administrators."}
        </p>
      </div>
      <CreateAccount me={me} onCreated={load} />
      <ErrorNotice error={error} />
      {status && (
        <div role="status" className="notice">
          {status}
        </div>
      )}
      <button className="secondary" onClick={load}>
        Refresh users
      </button>
      <section className="panel user-list">
        {users.map((user) => (
          <form
            className="user-row"
            key={`${user.id}-${user.roles.join()}`}
            onSubmit={(event) => save(event, user)}
          >
            <div>
              <strong>{user.displayName}</strong>
              <p>{user.email}</p>
            </div>
            <fieldset>
              <legend>Assigned roles</legend>
              {roles.map((role) => (
                <label key={role}>
                  <input
                    type="checkbox"
                    name="roles"
                    value={role}
                    defaultChecked={user.roles.includes(role)}
                    disabled={role === "ADMIN" && (!me.primaryAdmin || user.primaryAdmin)}
                  />
                  {role}
                </label>
              ))}
            </fieldset>
            <div className="user-actions">
              <button>Save roles</button>
              {canDelete(user) && (
                <button type="button" className="danger" onClick={() => remove(user)}>
                  Delete user
                </button>
              )}
            </div>
          </form>
        ))}
      </section>
    </>
  );
}
function App() {
  const [me, setMe] = useState(null),
    [error, setError] = useState(""),
    [tab, setTab] = useState("");
  const refresh = () =>
    api("/me")
      .then((user) => {
        setMe(user);
        setTab(
          (current) =>
            current ||
            (user.roles.includes("RESEARCHER")
              ? "Search"
              : user.roles.includes("UPLOADER")
                ? "Upload"
                : user.roles.includes("ADMIN")
                  ? "Admin"
                  : ""),
        );
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    let timer;
    const activity = () => {
      clearTimeout(timer);
      timer = setTimeout(() => logout(), 30 * 60 * 1000);
    };
    const events = ["pointerdown", "keydown"];
    events.forEach((event) => window.addEventListener(event, activity));
    activity();
    return () => {
      clearTimeout(timer);
      events.forEach((event) => window.removeEventListener(event, activity));
    };
  }, []);
  async function logout() {
    try {
      await post("/logout");
    } finally {
      await auth.logout({ redirectUri: window.location.origin });
    }
  }
  const tabs = [
    ["Search", "RESEARCHER"],
    ["Upload", "UPLOADER"],
    ["Admin", "ADMIN"],
  ].filter(([, role]) => me?.roles.includes(role));
  const selected = tabs.some(([name]) => name === tab) ? tab : tabs[0]?.[0];
  return (
    <>
      <header>
        <a className="brand" href="/">
          <span className="brand-box" />
          MediaMesh<span className="brand-sub">EDITORIAL ARCHIVE</span>
        </a>
        <div className="identity">
          <span>{me?.displayName}</span>
          <button className="secondary" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>
      <nav aria-label="Main navigation">
        {tabs.map(([name]) => (
          <button
            key={name}
            aria-current={selected === name ? "page" : undefined}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </nav>
      <main>
        <ErrorNotice error={error} />
        {!me ? (
          <p>Loading your workspace…</p>
        ) : !tabs.length ? (
          <section className="panel">
            <h2>Welcome, {me.displayName}</h2>
            <p>
              Your account is ready. Ask your administrator to grant uploader or
              researcher access.
            </p>
            <button onClick={refresh}>Refresh access</button>
          </section>
        ) : selected === "Search" ? (
          <Research />
        ) : selected === "Upload" ? (
          <Upload />
        ) : (
          <Admin me={me} onChanged={refresh} />
        )}
      </main>
      <footer>
        MediaMesh · CMPE 272 · Hypothetical National Geographic editorial
        scenario
      </footer>
    </>
  );
}
auth.onTokenExpired = () => auth.updateToken(30).catch(() => auth.login());
auth
  .init({
    onLoad: "login-required",
    pkceMethod: "S256",
    checkLoginIframe: false,
  })
  .then(() => {
    createRoot(document.getElementById("root")).render(
      <ErrorBoundary>
        <App />
      </ErrorBoundary>,
    );
  })
  .catch(() => {
    document.getElementById("root").textContent =
      "Sign-in is unavailable. Check the identity service and reload.";
  });
