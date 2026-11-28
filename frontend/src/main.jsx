import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { auth, api, post } from "./api";
import { uploadFile, metadata } from "./upload";
import "./styles.css";
import ErrorBoundary from "./ErrorBoundary";
import { ResultCard, MediaPreview } from "./Gallery";

const roles = ["UPLOADER", "RESEARCHER"];
function ErrorNotice({ error }) {
  return error ? (
    <div role="alert" className="notice error">
      {error}
    </div>
  ) : null;
}
function MediaGlyph({ video = false, upload = false }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {upload ? <><path d="M12 16V3m-4 4 4-4 4 4M4 15v5h16v-5" /></> : video ? <><rect x="3" y="5" width="13" height="14" rx="2" /><path d="m16 10 5-3v10l-5-3" /></> : <><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8" cy="8" r="1.5" /><path d="m3 17 5-5 4 4 4-6 5 7" /></>}
  </svg>;
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
        Additional notes (optional)
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
      <div className="section-title workspace-banner upload-banner">
        <span className="eyebrow">CONTRIBUTIONS</span>
        <h2>Contribute to the archive</h2>
        <p>Upload a photograph or a documentary clip up to 3 minutes.</p>
      </div>
      <ErrorNotice error={error} />
      <div className="columns contribution-layout">
        <section className="panel upload-panel">
          <div className="panel-heading"><span className="section-marker">01</span><div><h3>Add media</h3><p>A new perspective for the archive.</p></div></div>
          <form onSubmit={submit}>
            <label className="upload-picker">
              <span className="upload-glyph"><MediaGlyph upload /></span>
              <span className="picker-title">Choose a photograph or video</span>
              <span className="picker-hint">JPEG, PNG, MP4 or MOV · Up to 100 MB</span>
              <span className="sr-only">Media file</span>
              <input
                name="file"
                type="file"
                required
                accept="image/jpeg,image/png,video/mp4,video/quicktime"
              />
            </label>
            <div className="upload-description-note">A visual description is generated automatically after upload.</div>
            <div className="upload-metadata"><div className="form-section-heading">Media details</div><MetadataFields /></div>
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
        <section className="panel contributions-panel">
          <div className="panel-heading"><span className="section-marker">02</span><div><h3>Your contributions</h3><p>Manage media and track processing.</p></div><span className="page-count">{assets.length} on this page</span></div>
          {assets.length === 0 && <div className="contributions-empty"><MediaGlyph /><h4>Your archive starts here</h4><p>Uploaded media and its processing status will appear here.</p></div>}
          {assets.map((asset) => (
            <article className="asset-row contribution-row" key={asset.assetId}>
              <span className="asset-type-icon"><MediaGlyph video={asset.mediaType === "video"} /></span>
              <div className="contribution-copy">
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
          <div className="contribution-pagination">
            <span>Page {Math.floor(offset / 50) + 1}</span>
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
      const response = await api("/search", {
        method: "POST",
        body: JSON.stringify({ ...body, limit: 20 }),
        signal: AbortSignal.timeout(45000),
      });
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
      if (id === request.current) { setResults(response.results); setResultLabel(`Similar to ${asset.title}`); }
    } catch (e) { if (id === request.current) setError(e.message); }
    finally { if (id === request.current) setBusy(false); }
  }
  const topics = [["Wildlife", "wild animals in natural settings"],
    ["Botanical", "plants, flowers, or other vegetation"],
    ["Oceans", "ocean scenes, waves, or coastlines"],
    ["Marine life", "marine animals or underwater life"],
    ["Birds", "birds in natural settings"],
    ["Landscapes", "natural landscapes or scenic views"]];
  return (
    <section className="research-workspace">
      <div className="discovery-heading workspace-banner">
        <div><span className="eyebrow">EDITORIAL WORKSPACE</span>
          <h2>Search the archive</h2>
          <p>Find photographs and video by subject, scene, or setting.</p></div>
        <div className="banner-aside"><span className="banner-frame" aria-hidden="true" /><span>THE NATURAL WORLD<br /><strong>In focus.</strong></span></div>
      </div>
      <ErrorNotice error={error} />
      <form ref={form} className="panel search discovery-search" onSubmit={search}>
        <label htmlFor="archive-query">Describe what you need</label>
        <div className="query-row">
          <svg aria-hidden="true" className="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></svg>
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
        <div><h3>{resultLabel.startsWith("Similar to ") ? "Visually similar images" : `Results for “${resultLabel}”`}</h3>
          <p role="status">{results.length} matching assets · Sorted by relevance</p></div>
        <div className="density-toggle" role="group" aria-label="Gallery layout">
          <button className="secondary" aria-pressed={density === "comfortable"} onClick={() => setDensity("comfortable")}>Comfortable</button>
          <button className="secondary" aria-pressed={density === "compact"} onClick={() => setDensity("compact")}>Compact</button>
        </div>
      </div>}
      {busy && <div className="gallery-loading" role="status">Finding moments in the archive<span>…</span></div>}
      {results?.length === 0 && !busy && <div className="gallery-empty"><span aria-hidden="true">⌕</span>
        <h3>A new angle might help.</h3><p>Try a broader description or remove a filter to explore more of the archive.</p></div>}
      {!results && !busy && <div className="discovery-empty"><div><span className="eyebrow">A DIFFERENT PERSPECTIVE</span>
        <h3>Start with a subject.<br />Discover the scene.</h3><p>Describe an animal, a landscape, or a moment you need.</p></div>
        <div className="search-examples"><span>TRY A SEARCH</span>{[["01", "Wildlife", "elephants in the savanna"], ["02", "Underwater", "sea turtle underwater"], ["03", "Landscapes", "mountains and valleys"]].map(([number, label, prompt]) => <button type="button" key={number} onClick={() => search(null, prompt)}><span>{number}</span><div><strong>{label}</strong><small>{prompt}</small></div><span aria-hidden="true">↗</span></button>)}</div></div>}
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
function AccessRequest({ me, onChanged }) {
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const pending = me.requestStatus === "PENDING";
  async function submit(event) {
    event.preventDefault();
    const roles = new FormData(event.currentTarget).getAll("roles");
    if (!roles.length) { setError("Select at least one role."); return; }
    setBusy(true); setError("");
    try { await post("/me/access-request", { roles }); await onChanged(); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  if (pending) return <section className="panel access-request-panel access-pending-panel">
    <div className="pending-heading">
      <span className="pending-clock" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="8" /><path d="M12 7v5l3 2" /></svg></span>
      <span className="pending-label">AWAITING APPROVAL</span>
    </div>
    <h2>Your access request is pending</h2>
    <p className="pending-description" role="alert">Your sign-in request has not yet been approved. Once the administrator approves it, your workspace will open automatically.</p>
    <dl className="pending-details">
      <div><dt>Requested access</dt><dd>{me.requestedRoles.map(role => <span className="pending-role" key={role}>{role === "UPLOADER" ? "Uploader" : "Researcher"}</span>)}</dd></div>
    </dl>
    <div className="access-request-actions">
      <span className="access-action-note"><span className="pending-status-dot" aria-hidden="true" />Checking for updates automatically</span>
      <div className="access-action-buttons">
        <button type="button" className="secondary access-refresh" onClick={onChanged}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6.1 7a7 7 0 0 1 11.6-1L20 9M4 15l2.3 3A7 7 0 0 0 17.9 17" /></svg>
          Refresh access
        </button>
      </div>
    </div>
  </section>;
  return <section className="panel account-create access-request-panel">
    <span className="eyebrow">WORKSPACE ACCESS</span>
    <h2>Choose your workspace access</h2>
    <p>Select uploader, researcher, or both. An administrator must approve your request before you can use the selected tools.</p>
    {me.requestStatus === "REJECTED" && <p>Your last request was declined. You can submit a new request.</p>}
    {me.requestStatus === "APPROVED" && <p>Your last request was approved. Your current roles are shown in the navigation above.</p>}
    <ErrorNotice error={error} />
    <form id="access-request-form" onSubmit={submit}>
      <fieldset className="role-options"><legend>Select one or both roles</legend>
        {roles.map(role => {
          const approved = me.roles.includes(role);
          const label = role === "UPLOADER" ? "Uploader" : "Researcher";
          return <label className={`role-option${approved ? " role-option-approved" : ""}`} key={`${role}-${approved}`}>
            <input type="checkbox" name="roles" value={role} aria-label={label} defaultChecked={approved} disabled={approved} />
            <span className="role-option-copy"><strong>{label}</strong><span>{role === "UPLOADER" ? "Upload images and media for indexing. Manage your contributions and processing status." : "Search the archive, use the search API, and view indexed media."}</span>
              {approved ? <small className="role-approved-badge"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m3.5 8 3 3 6-6" /></svg>Approved</small> : <small className="role-available-note">Select to request access</small>}
            </span>
          </label>;
        })}
      </fieldset>
    </form>
    <div className="access-request-actions">
      <span className="access-action-note">You can select both roles.</span>
      <div className="access-action-buttons">
        <button type="button" className="secondary access-refresh" disabled={busy} onClick={onChanged}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6.1 7a7 7 0 0 1 11.6-1L20 9M4 15l2.3 3A7 7 0 0 0 17.9 17" /></svg>
          Refresh access
        </button>
        <button form="access-request-form" type="submit" className="access-submit" disabled={busy || roles.every(role => me.roles.includes(role))}>
          {busy ? "Submitting…" : "Request access"}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5" /></svg>
        </button>
      </div>
    </div>
  </section>;
}
function MemberIdentity({ user }) {
  const initials = user.displayName.split(" ").filter(Boolean).slice(0, 2).map(name => name[0]).join("");
  return <div className="member-identity">
    <span className="member-avatar" aria-hidden="true">{initials}</span>
    <div className="member-copy"><strong>{user.displayName}{user.primaryAdmin && <span className="admin-owner-badge">Admin</span>}</strong><p>{user.email}</p></div>
  </div>;
}
function Admin({ me, onChanged }) {
  const [users, setUsers] = useState([]),
    [requests, setRequests] = useState([]),
    [reviewing, setReviewing] = useState(null),
    [memberQuery, setMemberQuery] = useState(""),
    [error, setError] = useState(""),
    [status, setStatus] = useState("");
  const load = async () => {
    try {
      const [members, pending] = await Promise.all([api("/admin/users"), api("/admin/access-requests")]);
      setUsers(members); setRequests(pending);
    } catch (e) { setError(e.message); }
  };
  async function decide(request, approve) {
    setError(""); setStatus(""); setReviewing(request.id);
    try {
      await post(`/admin/access-requests/${request.id}/decision`, { approve });
      setStatus(`${approve ? "Approved" : "Declined"} access for ${request.user.displayName}.`);
      await load();
    } catch (e) { setError(e.message); }
    finally { setReviewing(null); }
  }
  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);
  async function save(event, user) {
    event.preventDefault();
    setError(""); setStatus("");
    const assigned = new FormData(event.currentTarget).getAll("roles");
    if (user.primaryAdmin) assigned.push("ADMIN");
    try {
      await api(`/admin/users/${user.id}/roles`, { method: "PUT", body: JSON.stringify({ roles: assigned }) });
      setStatus(`Saved roles for ${user.displayName}.`);
      await Promise.all([load(), onChanged()]);
    } catch (e) { setError(e.message); }
  }
  const canDelete = user => user.id !== me.id && !user.primaryAdmin && (me.primaryAdmin || !user.roles.includes("ADMIN"));
  async function remove(user) {
    setError(""); setStatus("");
    if (!window.confirm(`Delete ${user.displayName} (${user.email})?\n\nThey will no longer be able to sign in. Media they uploaded stays in the library. This cannot be undone.`)) return;
    try {
      await api(`/admin/users/${user.id}`, { method: "DELETE" });
      setStatus(`Deleted ${user.displayName}.`);
      await load();
    } catch (e) { setError(e.message); }
  }
  const managedUsers = users.filter(user => user.id !== me.id);
  const filteredUsers = managedUsers.filter(user => `${user.displayName} ${user.email}`.toLowerCase().includes(memberQuery.trim().toLowerCase()))
    .sort((a, b) => Number(Boolean(b.primaryAdmin)) - Number(Boolean(a.primaryAdmin)) || a.displayName.localeCompare(b.displayName));
  return (
    <div className="admin-workspace">
      <div className="admin-page-heading">
        <div><span className="eyebrow">ADMINISTRATION</span><h2>Manage library access</h2><p>Review access requests and manage your workspace members.</p></div>
        <div className="admin-summary" aria-label="Workspace overview">
          <div><strong>{requests.length}</strong><span>Pending requests</span></div>
          <div><strong>{users.length}</strong><span>Workspace members</span></div>
        </div>
      </div>
      <ErrorNotice error={error} />
      {status && <div role="status" className="notice admin-feedback">{status}</div>}
      <section className="panel admin-requests">
        <div className="admin-section-heading"><div><h3>Pending access requests <span className="admin-count">({requests.length})</span></h3><p>Approve the requested roles or decline access.</p></div><span className="admin-live-note"><span />Updates automatically</span></div>
        {!requests.length && <div className="admin-empty"><span className="admin-empty-check" aria-hidden="true">✓</span><div><strong>All caught up</strong><p>No requests awaiting approval.</p></div></div>}
        {requests.map(request => <article className="admin-request-row" key={request.id}>
          <MemberIdentity user={request.user} />
          <div className="admin-requested-roles"><span className="admin-column-label">Requested access</span><div>{request.roles.map(role => <span className="admin-role-badge" key={role}>{role === "UPLOADER" ? "Uploader" : "Researcher"}</span>)}</div></div>
          <div className="admin-row-actions">
            <button disabled={reviewing !== null} className="secondary admin-decline" onClick={() => decide(request, false)}>Decline request</button>
            <button disabled={reviewing !== null} className="admin-approve" onClick={() => decide(request, true)}>{reviewing === request.id ? "Saving…" : "Approve request"}</button>
          </div>
        </article>)}
      </section>
      <section className="panel admin-members">
        <div className="admin-section-heading admin-members-toolbar">
          <div><h3>Workspace members <span className="admin-count">({managedUsers.length})</span></h3><p>Select roles, then save changes for that member.</p></div>
          <div className="admin-member-tools">
            <label className="admin-member-search"><span className="sr-only">Search members</span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></svg><input type="search" placeholder="Search members…" value={memberQuery} onChange={event => setMemberQuery(event.target.value)} /></label>
            <button type="button" className="secondary admin-refresh" onClick={load} aria-label="Refresh users" title="Refresh users"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 7a7 7 0 0 1 11.6-1L20 9M4 15l2.3 3A7 7 0 0 0 17.9 17"/></svg></button>
          </div>
        </div>
        <div className="admin-table-heading" aria-hidden="true"><span>Member</span><span>Access roles</span><span>Actions</span></div>
        {!filteredUsers.length && <div className="admin-empty"><p>No members match your search.</p></div>}
        {filteredUsers.map(user => <form className="user-row admin-member-row" key={`${user.id}-${user.roles.join()}`} onSubmit={event => save(event, user)}>
          <MemberIdentity user={user} />
          <fieldset className="admin-role-options"><legend className="sr-only">Assigned roles for {user.displayName}</legend>
            {roles.map(role => <label className="admin-role-toggle" key={role}><input type="checkbox" name="roles" value={role} aria-label={role} defaultChecked={user.roles.includes(role)} /><span>{role === "UPLOADER" ? "Uploader" : "Researcher"}</span></label>)}
          </fieldset>
          <div className="admin-row-actions">
            <button className="secondary admin-save">Save roles</button>
            {canDelete(user) ? <button type="button" className="danger admin-delete" aria-label={`Delete user ${user.displayName}`} title="Delete user" onClick={() => remove(user)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5m4-5v5"/></svg></button> : <span className="admin-protected" title="The administrator account is protected">Owner</span>}
          </div>
        </form>)}
        <div className="admin-members-footer"><span>{filteredUsers.length} of {managedUsers.length} members</span><span>Administrator · {me.email}</span></div>
      </section>
      <section className="panel admin-self-roles" aria-labelledby="workspace-roles-heading">
        <div className="admin-section-heading"><div><h3 id="workspace-roles-heading">Your workspace roles</h3><p>Enable upload or search access for your account. Your administrator role stays active.</p></div></div>
        <form className="admin-member-row" key={me.roles.join()} onSubmit={event => save(event, me)}>
          <MemberIdentity user={me} />
          <fieldset className="admin-role-options"><legend className="sr-only">Your workspace roles</legend>
            {roles.map(role => <label className="admin-role-toggle" key={role}><input type="checkbox" name="roles" value={role} aria-label={role} defaultChecked={me.roles.includes(role)} /><span>{role === "UPLOADER" ? "Uploader" : "Researcher"}</span></label>)}
          </fieldset>
          <div className="admin-row-actions"><button className="secondary admin-save">Save workspace roles</button></div>
        </form>
      </section>
    </div>
  );
}

function Seed({ me }) {
  const [images, setImages] = useState(20),
    [seed, setSeed] = useState(null),
    [starting, setStarting] = useState(false),
    [error, setError] = useState("");
  const load = async (count = images) => {
    try { setSeed(await api(`/admin/seed?images=${count}`)); setError(""); }
    catch (e) { setError(e.message); }
  };
  useEffect(() => {
    load(images);
    const timer = setInterval(() => load(images), 5000);
    return () => clearInterval(timer);
  }, [images]);
  const run = seed?.run;
  const running = run?.state === "RUNNING";
  async function start() {
    if (!window.confirm(`Load ${images} demo images into the library?\n\nThey will be owned by your account (${me.email}). Images already in the library are skipped. Generating descriptions uses OpenRouter credit.`)) return;
    setStarting(true); setError("");
    try { setSeed(await post("/admin/seed", { images })); }
    catch (e) { setError(e.message); }
    finally { setStarting(false); }
  }
  const total = seed?.images || images;
  const stored = seed ? total - seed.missing - seed.uploading : 0;
  const percent = seed ? Math.round((seed.ready / total) * 100) : 0;
  return (
    <div className="admin-workspace">
      <div className="admin-page-heading">
        <div><span className="eyebrow">ADMINISTRATION</span><h2>Seed demo library</h2><p>Load curated, credited nature photographs into this library's storage and index them like normal uploads.</p></div>
        <div className="admin-summary" aria-label="Seed overview">
          <div><strong>{seed ? seed.ready : "–"}</strong><span>Ready</span></div>
          <div><strong>{seed ? seed.processing : "–"}</strong><span>Indexing</span></div>
          <div><strong>{seed ? seed.missing + seed.uploading : "–"}</strong><span>Not loaded</span></div>
        </div>
      </div>
      <ErrorNotice error={error} />
      {run?.state === "FAILED" && <div role="alert" className="notice error">{run.error}</div>}
      {run?.state === "COMPLETED" && run.images === images && <div role="status" className="notice admin-feedback">All {run.images} images are stored. Indexing continues in the background.</div>}
      <section className="panel seed-panel">
        <div className="admin-section-heading"><div><h3>Choose a collection size</h3><p>Larger sets include the smaller ones, so you can grow the library later without duplicates.</p></div><span className="admin-live-note"><span />Updates automatically</span></div>
        <div className="seed-body">
          <fieldset className="seed-options" disabled={running || starting}><legend className="sr-only">Number of images</legend>
            {(seed?.options || [20, 50, 100, 500]).map(count => <label key={count} className="admin-role-toggle">
              <input type="radio" name="images" value={count} checked={images === count} onChange={() => setImages(count)} /><span>{count} images</span>
            </label>)}
          </fieldset>
          <div className="seed-progress">
            <div className="seed-progress-label"><span>{seed ? `${seed.ready} of ${total} ready` : "Checking library…"}</span><span>{running ? `Storing ${run.processed}/${run.images}…` : `${stored} of ${total} stored`}</span></div>
            <div className="seed-bar" role="progressbar" aria-label="Images ready" aria-valuemin="0" aria-valuemax={total} aria-valuenow={seed?.ready || 0}><span style={{ width: `${percent}%` }} /></div>
            {seed?.failed > 0 && <p className="seed-note">{seed.failed} image{seed.failed === 1 ? "" : "s"} failed indexing. Check the ML worker logs.</p>}
            <p className="seed-note">Images are owned by you. To browse them in Search, enable the Researcher role for yourself on the Admin tab.</p>
          </div>
          <div className="admin-row-actions">
            <button className="admin-approve" disabled={running || starting || !seed || (seed.missing + seed.uploading === 0)} onClick={start}>
              {running ? "Seeding…" : starting ? "Starting…" : seed && seed.missing + seed.uploading === 0 ? "Already loaded" : `Load ${images} images`}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function App() {
  const [me, setMe] = useState(null),
    [error, setError] = useState(""),
    [tab, setTab] = useState("");
  const previousRoles = useRef(null);
  const refresh = () =>
    api("/me")
      .then((user) => {
        const justApproved = previousRoles.current?.length === 0 && user.roles.length > 0;
        previousRoles.current = user.roles;
        setMe(user);
        setError("");
        setTab(
          (current) =>
            (!justApproved && current) ||
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
    ["Seed", "ADMIN"],
  ].filter(([, role]) => me?.roles.includes(role));
  if (me && !me.roles.includes("ADMIN") && !roles.every(role => me.roles.includes(role))) tabs.push(["Access", ""]);
  const selected = tabs.some(([name]) => name === tab) ? tab : tabs[0]?.[0];
  return (
    <div className={tabs.length === 1 && selected === "Access" ? "access-only-shell" : undefined}>
      <header>
        <a className="brand" href="/">
          <span className="brand-box" />
          MediaMesh<span className="brand-sub">EDITORIAL ARCHIVE</span>
        </a>
        <div className="identity">
          <div className="identity-profile">
            <span className="identity-avatar" aria-hidden="true">{me?.displayName?.split(" ").filter(Boolean).slice(0,2).map(name=>name[0]).join("")}</span>
            <span className="identity-details"><span className="identity-name">{me?.displayName}</span><span className="identity-email" title={me?.email}>{me?.email}</span></span>
          </div>
          <button className="secondary" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>
      {tabs.length > 1 && <nav aria-label="Main navigation">
        {tabs.map(([name]) => (
          <button
            key={name}
            aria-current={selected === name ? "page" : undefined}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </nav>}
      <main>
        <ErrorNotice error={error} />
        {!me ? (
          error ? <section className="panel"><h2>Unable to complete sign-in</h2><p>Sign out and try Google sign-in again. Your access request, if submitted, is saved.</p><button onClick={refresh}>Try again</button></section> : <p>Loading your workspace…</p>
        ) : selected === "Access" ? (
          <AccessRequest me={me} onChanged={refresh} />
        ) : selected === "Search" ? (
          <Research />
        ) : selected === "Upload" ? (
          <Upload />
        ) : selected === "Seed" ? (
          <Seed me={me} />
        ) : (
          <Admin me={me} onChanged={refresh} />
        )}
      </main>
      <footer>
        MediaMesh · CMPE 272 · Hypothetical National Geographic editorial
        scenario
      </footer>
    </div>
  );
}
auth.onTokenExpired = () => auth.updateToken(30).catch(() => auth.login({ idpHint: "google" }));
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
