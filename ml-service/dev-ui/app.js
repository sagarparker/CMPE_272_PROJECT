'use strict';
const $ = id => document.getElementById(id);
const assetsById = new Map();
let samples = [], refreshing = false, lastSearch = null;
const notice = (message, error = false) => {
  $('notice').textContent = message;
  $('notice').className = error ? 'error' : '';
};
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
async function api(path, options = {}) {
  const response = await fetch(path, {cache: 'no-store', ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || data.detail || `Request failed (${response.status})`);
  return data;
}
const post = (path, body) => api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)});
async function action(button, work) {
  button.disabled = true;
  try { await work(); await refresh(); }
  catch (error) { notice(error.message, true); }
  finally { button.disabled = false; }
}
function badge(value) { return el('span', value, `badge ${value}`); }
function cell(row, content, className) {
  const td = el('td', undefined, className);
  td.append(content instanceof Node ? content : document.createTextNode(String(content ?? '—')));
  row.append(td);
  return td;
}
function button(text, handler) {
  const b = el('button', text); b.type = 'button';
  b.addEventListener('click', () => action(b, handler));
  return b;
}
function emptyTable(id, count, message) {
  const row = el('tr'), td = el('td', message); td.colSpan = count; row.append(td); $(id).replaceChildren(row);
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const status = await api('/dev/status');
    $('health').textContent = `API: ${status.api ? 'online' : 'offline'} · Model & database: ${status.ready ? 'ready' : 'not ready'}`;
    if (!status.localFixtures) throw new Error('Local fixtures are unavailable. Follow LOCAL_WORKFLOW.md to initialize the database.');
    const [assetData, jobData] = await Promise.all([api('/dev/assets'), api('/dev/jobs')]);
    assetsById.clear(); $('assets').replaceChildren();
    for (const asset of assetData.assets) {
      assetsById.set(asset.assetId, asset);
      const row = el('tr');
      cell(row, asset.name); cell(row, asset.mediaType); cell(row, badge(asset.status || 'UNKNOWN')); cell(row, asset.vectorCount);
      const actions = cell(row, '');
      actions.append(button('Reindex', async () => {
        await post(`/dev/assets/${asset.assetId}/reindex`);
        notice(`Queued ${asset.name}. The worker will process it.`);
      }));
      actions.append(button('Remove index', async () => {
        await api(`/dev/assets/${asset.assetId}/index`, {method: 'DELETE'});
        notice(`Removed embeddings for ${asset.name}; original file kept.`);
        if (lastSearch) await search(lastSearch.query, lastSearch.limit);
      }));
      $('assets').append(row);
    }
    if (!assetData.assets.length) emptyTable('assets', 5, 'No assets yet. Upload a file or index a sample.');
    $('jobs').replaceChildren();
    for (const job of jobData.jobs) {
      const row = el('tr'); row.dataset.jobId = job.jobId;
      cell(row, job.name); cell(row, badge(job.status)); cell(row, `${job.attempts} / ${job.maxAttempts}`);
      cell(row, job.lastError); cell(row, job.jobId, 'id');
      const actions = cell(row, '');
      if (job.status === 'FAILED') actions.append(button('Retry', async () => {
        await post(`/dev/assets/${job.assetId}/reindex`); notice('Queued a new attempt.');
      }));
      $('jobs').append(row);
    }
    if (!jobData.jobs.length) emptyTable('jobs', 6, 'No jobs yet.');
  } catch (error) { notice(error.message, true); }
  finally { refreshing = false; }
}
function updateCredit() {
  const sample = samples.find(s => s.id === $('sample').value);
  $('credit').replaceChildren();
  if (sample) {
    const source = el('a', 'Source / license'); source.href = sample.source; source.target = '_blank'; source.rel = 'noopener noreferrer';
    $('credit').append(document.createTextNode(`${sample.credit} · ${sample.license} · `), source);
  }
}
async function loadSamples() {
  try {
    samples = (await api('/dev/samples')).samples;
    $('sample').replaceChildren();
    for (const sample of samples) {
      const option = el('option', `${sample.id} · ${sample.mediaType}`); option.value = sample.id; $('sample').append(option);
    }
    if (!samples.length) $('sample').append(el('option', 'No samples downloaded'));
    $('index-sample').disabled = !samples.length; $('index-all').disabled = !samples.length;
    updateCredit();
  } catch (error) { notice(error.message, true); }
}
async function search(query, limit) {
  const result = await post('/dev/search', {query, limit});
  lastSearch = {query, limit};
  notice('');
  $('raw').textContent = JSON.stringify(result, null, 2);
  $('results').replaceChildren();
  $('result-status').textContent = result.matches.length ? `${result.matches.length} result(s) for “${query}”` : 'No matches. Index some media first, or try another query.';
  for (const match of result.matches) {
    const asset = assetsById.get(match.assetId);
    const video = asset?.mediaType === 'video' || match.frameTimestampSeconds !== null;
    const card = el('article', undefined, 'result'); card.dataset.assetId = match.assetId;
    const media = el(video ? 'video' : 'img');
    media.src = `/dev/media/${match.assetId}`;
    if (video) {
      media.controls = true; media.preload = 'metadata';
      media.addEventListener('loadedmetadata', () => {
        if (match.frameTimestampSeconds !== null) media.currentTime = match.frameTimestampSeconds;
      }, {once: true});
    } else { media.alt = asset?.name || 'Matching image'; media.loading = 'lazy'; }
    const content = el('div', undefined, 'result-content');
    content.append(el('h3', asset?.name || match.assetId), el('p', `Score: ${match.score.toFixed(4)}`));
    if (match.frameTimestampSeconds !== null) content.append(el('p', `Best frame: ${match.frameTimestampSeconds.toFixed(2)} seconds`));
    card.append(media, content); $('results').append(card);
  }
}
$('file').addEventListener('change', () => {
  const file = $('file').files[0];
  if (file) $('kind').value = file.type.startsWith('video/') || /\.(mp4|mov|webm|mkv)$/i.test(file.name) ? 'video' : 'image';
});
$('upload-form').addEventListener('submit', event => {
  event.preventDefault(); const submit = event.submitter;
  action(submit, async () => {
    const file = $('file').files[0]; if (!file) throw new Error('Choose a file first.');
    const params = new URLSearchParams({filename: file.name, kind: $('kind').value});
    await api(`/dev/upload?${params}`, {method: 'POST', body: file});
    notice(`Uploaded ${file.name}; indexing queued.`); $('upload-form').reset();
  });
});
$('search-form').addEventListener('submit', event => {
  event.preventDefault();
  action(event.submitter, () => search($('query').value, Number($('limit').value)));
});
$('sample').addEventListener('change', updateCredit);
$('index-sample').addEventListener('click', event => action(event.currentTarget, async () => {
  const result = await post('/dev/samples/index', {sampleId: $('sample').value});
  notice(`Queued ${result.jobs.length} sample. Watch the jobs below.`);
}));
$('index-all').addEventListener('click', event => action(event.currentTarget, async () => {
  const result = await post('/dev/samples/index', {sampleId: null}); notice(`Queued ${result.jobs.length} samples.`);
}));
$('retry-demo').addEventListener('click', event => action(event.currentTarget, async () => {
  const result = await post('/dev/retry-demo'); notice(`Retry test queued: ${result.jobId}. It should succeed on attempt 2.`);
}));
$('refresh').addEventListener('click', refresh);
document.querySelectorAll('[data-query]').forEach(b => b.addEventListener('click', () => { $('query').value = b.dataset.query; $('query').focus(); }));
(async () => { await refresh(); await loadSamples(); })();
setInterval(refresh, 2000);
