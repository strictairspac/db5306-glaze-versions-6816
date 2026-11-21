import {heading} from '../components/common/heading.js';
import {fields, readFields} from '../components/fields.js';
import {topic} from '../constants/project.js';
import {esc} from '../utils/dom.js';
import {submit} from '../hooks/submit.js';
import {go} from '../router/hash.js';

export function editorPage(state, identity) {
  if (state.session.role!=='operator') return heading(topic.modules[1], '经办员可以建立并提交业务档案。');
  const original = state.cases.find(row=>row.id===identity);
  const payload = original?.payload || state.spec.sample;
  state.draft = payload;
  state.editing = original?.id || null;
  return `${heading(topic.modules[1], state.spec.guidance)}
    <form id="case-form"><label class="field title-field"><span>档案名称</span><input name="title" required maxlength="120" value="${esc((original?.title || state.spec.name) + ' · 复核')}" /></label>
    <div class="field-grid">${fields(payload, state.spec.field_labels)}</div>
    <p class="note">保存后档案内容会被冻结为执行快照，之后再改档案也不影响这次执行口径；同一快照重复提交会沿用已有执行，不重复生成证据。</p>
    <div class="actions form-actions"><button name="save-run" value="new">保存为新档案并执行</button>${original ? `<button name="save-run" value="update" class="secondary">覆盖当前档案并执行</button><a class="secondary" href="#cases/${esc(original.id)}">返回档案</a>` : '<a class="secondary" href="#cases">返回档案</a>'}</div></form>`;
}

export function bindEditor(state, api, fail) {
  submit('case-form', async (data, event)=>{
    const payload = readFields(state.draft, state.spec.field_labels);
    const replace = state.editing && event?.submitter?.value==='update';
    let draft;
    try {
      draft = replace
        ? await api(`/cases/${state.editing}`, {method:'PUT', data:{title:data.get('title'), payload}})
        : await api('/cases', {method:'POST', data:{title:data.get('title'), payload}});
    } catch (error) {
      fail(error);
      return;
    }
    try {
      const run = await api(`/cases/${draft.id}/runs`, {method:'POST'});
      go(`runs/${run.id}`);
    } catch (error) {
      go(`cases/${draft.id}`);
      fail(new Error(`档案已保存。提交执行失败：${error.message}`));
    }
  }, fail);
}
