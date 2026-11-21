import {heading, panel} from '../components/common/heading.js';
import {entries, records} from '../components/common/records.js';
import {topic} from '../constants/project.js';
import {date, el, esc} from '../utils/dom.js';
import {submit} from '../hooks/submit.js';

function shortDigest(value) {
  return value ? `${value.slice(0, 12)}…` : '—';
}

export function evidencePage(state, identity) {
  const current = state.evidence.find(row=>row.id===identity) || state.evidence[0];
  if (!current) return heading(topic.modules[3]) + '<p class="empty">执行完成后，可查看、复核和导出证据。</p>';
  const {report} = current;
  const signed = Boolean(current.reviewed_at);
  const metrics = Object.entries(report.metrics).map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('');
  const sections = report.sections.map(x=>panel(x.title, entries(x.rows))).join('');
  const review = current.reviewer ? `<p data-testid="reviewed">${esc(current.reviewer)} · ${esc(date(current.reviewed_at))}</p><p>${esc(current.review_note)}</p>`
    : state.session.role==='reviewer'?`<form id="review-form" data-id="${current.id}"><label>复核意见<textarea name="note" maxlength="500" required></textarea></label><button>签署复核</button></form>`
    : '<p class="note">待复核员签署</p>';
  const tool = signed ? `<button id="download" data-id="${current.id}">导出证据</button>`
    : '<button type="button" disabled title="复核签署后开放下载">导出证据（待签署）</button>';
  const version = `<dl class="brief">
    <dt>档案</dt><dd>${esc(current.case_title || current.case_id)}</dd>
    <dt>执行</dt><dd><a href="#runs/${current.run_id}">执行 ${current.run_id}</a> · 第 ${esc(current.run_version ?? '—')} 次提交 · 第 ${esc(current.run_attempts ?? current.attempt ?? '—')} 次尝试</dd>
    <dt>证据版本</dt><dd>第 ${esc(current.version ?? '—')} 次提交 · 第 ${esc(current.attempt ?? '—')} 次尝试</dd>
    <dt>快照摘要</dt><dd><code class="digest">${esc(shortDigest(current.payload_digest))}</code></dd>
    <dt>报告摘要</dt><dd><code class="digest">${esc(shortDigest(current.digest))}</code></dd>
    </dl>`;
  const history = state.evidence.map(row=>[`<a href="#evidence/${row.id}">执行 ${row.run_id}</a>`, esc(row.report.summary), esc(row.reviewed_at ? row.reviewer : '待复核'), esc(row.version ?? '—')]);
  return `${heading(topic.modules[3], report.summary, tool)}
    <div class="spread evidence-top"><dl class="metrics">${metrics}</dl><aside class="brief"><h2>复核签署</h2>${review}${version}<details><summary>结果校验码</summary><code class="digest">${esc(current.digest)}</code></details></aside></div>
    ${sections}<details><summary>历史证据</summary>${records(['执行','结论','复核','版本'], history)}</details>`;
}

export function bindEvidence(api, update, fail) {
  const button = document.getElementById('download');
  const form = document.getElementById('review-form');
  const identity = button?.dataset.id || form?.dataset.id;
  if (!identity) return;
  button?.addEventListener('click', async()=>{
    try {
      const response = await api(`/evidence/${identity}/download`, {response:true});
      const url = URL.createObjectURL(await response.blob());
      const link = el('a');
      link.href = url;
      link.download = `evidence-${identity}.json`;
      link.click();
      setTimeout(()=>URL.revokeObjectURL(url), 1000);
    } catch (error) { fail(error); }
  });
  submit('review-form', async data=>{
    await api(`/evidence/${identity}/review`, {method:'POST', data:{note:data.get('note')}});
    await update();
  }, fail);
}
