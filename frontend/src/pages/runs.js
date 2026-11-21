import {heading, panel} from '../components/common/heading.js';
import {records} from '../components/common/records.js';
import {badge} from '../components/common/status.js';
import {statusLabels} from '../constants/workflow.js';
import {topic} from '../constants/project.js';
import {date, esc} from '../utils/dom.js';

function shortDigest(value) {
  return value ? `${value.slice(0, 12)}…` : '—';
}

export function runsPage(state, identity) {
  const selected = state.runs.find(row=>row.id===identity) || state.runs[0];
  const cases = new Map(state.cases.map(row=>[row.id, row.title]));
  const rows = state.runs.map(row=>[
    `<a href="#runs/${row.id}">${esc(row.case_title || cases.get(row.case_id) || row.case_id)}</a>`,
    badge(row.status),
    esc(row.version ?? '—'),
    esc(row.attempts ?? 0),
    row.evidence_id ? `<a href="#evidence/${row.evidence_id}">证据 ${row.evidence_id}</a>` : '—',
    esc(row.owner),
    esc(date(row.created_at)),
  ]);
  const result = state.evidence.find(row=>row.run_id===selected?.id);
  const active = selected && ['queued','running'].includes(selected.status);
  const detail = selected ? `<h2>${esc(selected.case_title || cases.get(selected.case_id) || selected.case_id)}</h2>
    <p data-testid="run-status">${badge(selected.status)}</p>
    <dl><dt>执行版本</dt><dd>第 ${esc(selected.version ?? '—')} 次提交</dd>
    <dt>尝试次数</dt><dd>${esc(selected.attempts ?? 0)} 次</dd>
    <dt>快照摘要</dt><dd><code class="digest">${esc(shortDigest(selected.payload_digest))}</code></dd>
    <dt>启动时间</dt><dd>${esc(date(selected.started_at))}</dd>
    <dt>完成时间</dt><dd>${esc(date(selected.finished_at))}</dd></dl>
    ${selected.error ? `<p class="error">${esc(selected.error)}</p>` : ''}
    ${active?'<p class="note">后台处理中，记录会自动刷新。租约中断的执行会以新的尝试自动恢复。</p>':''}
    ${result?`<p class="note">本次执行已生成证据 ${result.id}，报告摘要 ${esc(shortDigest(result.digest))}，签署后开放下载。</p>
      <a class="button" href="#evidence/${result.id}">查看业务证据</a>`:''}
    ${!result && selected.status==='complete' ? '<p class="note">该执行没有生成证据。</p>' : ''}` : '<h2>执行记录</h2><p>从档案创建一条执行记录后，可在此查看进度。</p>';
  const audit = state.audit.filter(x=>selected && (
    x.run_id===selected.id || (x.run_id==null && x.reference===String(selected.id))
  ) && ['enqueue','retry','complete','failed','review','download'].includes(x.action));
  const labels = {...statusLabels, enqueue:'提交执行', retry:'自动重试', review:'签署复核', download:'导出证据'};
  return `${heading(topic.modules[2], `${state.spec.entity_labels[1]}与后台处理进度`, '<button class="secondary" type="button" id="refresh">刷新记录</button>')}
    <div class="spread"><section>${records(['档案','状态','版本','尝试','证据','经办','提交时间'], rows, '暂无执行记录。')}</section><aside class="brief">${detail}</aside></div>
    ${audit.length?panel('操作记录', records(['操作者','操作','证据','时间'], audit.map(x=>[esc(x.actor),esc(labels[x.action]||x.action),esc(x.evidence_id ?? '—'),esc(date(x.created_at))]))):''}`;
}
