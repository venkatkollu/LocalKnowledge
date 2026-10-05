const $ = selector => document.querySelector(selector);
const query = $('#query');
// Corpus filenames, errors and excerpts are untrusted. Always escape before
// producing HTML; the answer itself is rendered with textContent.
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
const token = sessionStorage.getItem('knowledgeos-token');
const headers = () => ({'Content-Type': 'application/json', ...(token ? {'Authorization': `Bearer ${token}`} : {})});
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {...headers(), ...options.headers}});
  const data = await response.json();
  if (!response.ok) throw Error(data.detail || 'Request failed');
  return data;
}
function setStats(stats) {
  const names = [['dense_candidates', 'Dense candidates'], ['bm25_candidates', 'BM25 candidates'], ['reranked', 'Reranked'], ['final_context', 'Final context'], ['retrieval_ms', 'Retrieval latency'], ['generation_ms', 'Generation latency']];
  $('#stats').innerHTML = names.map(([key, name]) => `<div><b>${name}</b><span>${escapeHTML(stats[key] ?? '—')}${key.endsWith('_ms') ? ' ms' : ''}</span></div>`).join('');
}
async function loadDocs() {
  try {
    const docs = await api('/documents');
    $('#docs').innerHTML = docs.length ? docs.map(doc => `<div class="doc"><i class="dot"></i><span>${escapeHTML(doc.filename)}<br><small>v${escapeHTML(doc.version)} · ${escapeHTML(doc.status)}${doc.error ? ' · ' + escapeHTML(doc.error) : ''}</small></span></div>`).join('') : 'No documents yet. Add files to data/knowledge.';
  } catch (error) { $('#docs').textContent = error.message; }
}
async function ask() {
  const question = query.value.trim();
  if (!question) return;
  $('#status').textContent = 'Retrieving and verifying evidence…';
  $('#answer').textContent = '';
  $('#citations').innerHTML = '';
  try {
    const data = await api('/chat', {method: 'POST', body: JSON.stringify({query: question, top_k: 6})});
    $('#answer').textContent = data.answer;
    $('#model').textContent = data.model;
    setStats(data.stats);
    $('#citations').innerHTML = data.citations.length ? '<strong>Verified sources</strong>' + data.citations.map(citation => `<div class="citation"><b>[${escapeHTML(citation.index)}] ${escapeHTML(citation.filename)}</b><small>${escapeHTML(citation.section || 'Document')} · v${escapeHTML(citation.version)} · chunk ${escapeHTML(citation.chunk_id)} · lines ${escapeHTML(citation.start_line ?? '—')}-${escapeHTML(citation.end_line ?? '—')}</small><br>${escapeHTML(citation.excerpt)}</div>`).join('') : '<small>No supporting citations.</small>';
    $('#status').textContent = `${data.abstained ? 'Abstained' : data.decision.decision} · trace ${data.trace_id.slice(0, 8)}`;
  } catch (error) { $('#answer').textContent = error.message; $('#status').textContent = 'Error'; }
}
$('#ask').onclick = ask;
query.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') ask(); });
$('#sync').onclick = async () => {
  $('#status').textContent = 'Queueing background sync…';
  try {
    const job = await api('/documents/sync', {method: 'POST'});
    const timer = setInterval(async () => {
      try {
        const status = await api(`/jobs/${job.job_id}`);
        $('#status').textContent = `${status.stage} · ${status.completed}/${status.total}`;
        if (['completed', 'failed'].includes(status.status)) { clearInterval(timer); loadDocs(); }
      } catch (error) { clearInterval(timer); $('#status').textContent = error.message; }
    }, 1000);
  } catch (error) { $('#status').textContent = error.message; }
};
loadDocs();
