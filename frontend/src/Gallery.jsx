import React, { useEffect, useRef, useState } from "react";
import { api, post } from "./api";

function mediaSource(url, asset) {
  return asset.mediaType === "video" ? `${url}#t=${asset.frameTimestampSeconds ?? 0.1}` : url;
}

export function ResultCard({ asset, onPreview, onDownload, onRelated }) {
  const container = useRef(null);
  const [visible, setVisible] = useState(false);
  const [url, setUrl] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { setVisible(true); observer.disconnect(); }
    }, { rootMargin: "200px" });
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!visible) return;
    let active = true;
    setError(""); setUrl(null);
    // Request short-lived URLs only near the viewport; never persist them.
    post(`/assets/${asset.assetId}/access-url`).then(access => {
      if (active) setUrl(access.url);
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [asset.assetId, visible, attempt]);
  return (
    <article className="result" ref={container}>
      <div className="thumbnail-wrap">
        <button className="thumbnail" onClick={onPreview} aria-label={`Preview ${asset.title}`}>
          {url && !error ? asset.mediaType === "video" ? (
            <video src={mediaSource(url, asset)} muted playsInline preload="metadata" aria-hidden="true"
              onError={() => setError("Video preview unavailable.")} />
          ) : (
            <img src={url} alt={asset.title} decoding="async"
              onError={() => setError("Image preview unavailable.")} />
          ) : <span className={error ? "thumbnail-message" : "thumbnail-skeleton"}>
            {error ? "Preview unavailable" : "Loading preview…"}
          </span>}
          <span className="media-pill">{asset.mediaType === "video" ? "▶ Video" : "Photograph"}</span>
          <span className="thumbnail-hint">{asset.mediaType === "video" ? "Play clip ↗" : "Open photograph ↗"}</span>
        </button>
        {error && <button className="thumbnail-retry" onClick={() => setAttempt(n => n + 1)}>Retry preview</button>}
      </div>
      <div className="result-info">
        <span className="eyebrow">{asset.title.includes(" | ") ? asset.title.split(" | ")[0] : "From the archive"}</span>
        <h3>{asset.title.includes(" | ") ? asset.title.split(" | ").slice(1).join(" | ") : asset.title}</h3>
        {(asset.species || asset.location) && <p>{[asset.species, asset.location].filter(Boolean).join(" · ")}</p>}
        {asset.frameTimestampSeconds != null && <p>Matching moment: {asset.frameTimestampSeconds.toFixed(1)}s</p>}
        <div className="result-bottom">
          <span className="similarity" title="Similarity indicates relative ranking, not confidence or accuracy.">
            {Math.round(asset.score * 100)} similarity
          </span>
          <div className="actions">
            <button className="secondary" onClick={onPreview}>Preview</button>
            <button className="secondary" onClick={onDownload}>Download</button>
            <button className="secondary" onClick={onRelated}>Related</button>
          </div>
        </div>
      </div>
    </article>
  );
}

export function MediaPreview({ asset, index, total, onClose, onPrevious, onNext, onDownload }) {
  const dialog = useRef(null);
  const previousFocus = useRef(document.activeElement);
  const [details, setDetails] = useState(null);
  const [url, setUrl] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => { element.close(); previousFocus.current?.focus(); };
  }, []);
  useEffect(() => {
    let active = true;
    setDetails(null); setUrl(null); setError("");
    Promise.all([api(`/assets/${asset.assetId}`), post(`/assets/${asset.assetId}/access-url`)])
      .then(([metadata, access]) => { if (active) { setDetails(metadata); setUrl(access.url); } })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [asset.assetId, attempt]);
  return (
    <dialog ref={dialog} className="lightbox" aria-label="Media preview" onCancel={onClose}
      onClick={event => { if (event.target === dialog.current) onClose(); }}
      onKeyDown={event => {
        if (["VIDEO", "INPUT", "TEXTAREA", "SUMMARY"].includes(event.target.tagName)) return;
        if (event.key === "ArrowLeft" && index > 0) { event.preventDefault(); onPrevious(); }
        if (event.key === "ArrowRight" && index < total - 1) { event.preventDefault(); onNext(); }
      }}>
      <div className="lightbox-top">
        <span className="eyebrow">The archive <span aria-live="polite">/ {index + 1} of {total}</span></span>
        <button className="secondary" onClick={onClose} autoFocus>Close</button>
      </div>
      <div className="lightbox-layout">
        <div className="lightbox-stage">
          {error ? <div className="preview-error" role="alert"><p>{error}</p>
            <button className="secondary" onClick={() => setAttempt(n => n + 1)}>Retry preview</button></div>
          : !url ? <p role="status">Loading preview…</p>
          : asset.mediaType === "image" ? <img src={url} alt={details?.title || asset.title}
              onError={() => setError("This preview could not load. Retry to renew access.")} />
            : <video key={url} controls autoPlay src={mediaSource(url, asset)}
                onError={() => setError("This clip could not load. Retry to renew access.")} />}
          <div className="lightbox-navigation">
            <button className="secondary" disabled={index === 0} onClick={onPrevious} aria-label="Previous asset">← Previous</button>
            <span>Use ← → to explore</span>
            <button className="secondary" disabled={index === total - 1} onClick={onNext} aria-label="Next asset">Next →</button>
          </div>
        </div>
        <aside className="lightbox-details">
          <span className="eyebrow">{asset.mediaType === "video" ? "Motion picture" : "Photograph"}</span>
          <h3>{asset.title}</h3>
          {details?.description && <p>{details.description}</p>}
          <dl>
            {[["Species", details?.species], ["Location", details?.location], ["Captured", details?.capturedAt],
              ["Contributor", details?.contributor]].filter(([, value]) => value).map(([label, value]) => (
                <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
              ))}
          </dl>
          <details className="rights" open key={asset.assetId}>
            <summary>Usage notes & credits</summary>
            <p>{details?.usageNote || "Not supplied. Verify licensing before publication."}</p>
          </details>
          <button onClick={onDownload}>Download original ↗</button>
          <p className="access-note">Private archive · access links last 60 seconds. Retry the preview to renew.</p>
        </aside>
      </div>
    </dialog>
  );
}
