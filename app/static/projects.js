import {api, query, ProjectContext} from './api.js';
import {h, actions, badge, notice, button, linkButton, pageHead, card, empty, loading, errorPanel, bind, checkbox, editorForm, modal, confirmDialog, toast, BUSINESS, projectBadge, dateTime, inputDateTime, definition, versionRefresh, serverText} from './ui.js';
import {loadDemo} from './settings.js';

export const FACTS = {
  staffing: '人员配置', control_points: '履职与控制要点', deliverables: '交付成果', regional_rules: '地区适用规则',
  payment_terms: '付款条件', commercial_terms: '商务条款', commission_relationship: 'TIS 委托关系', independence: 'TIS 独立性与角色边界',
  inspection_nodes: 'TIS 检查节点', risk_process: 'TIS 风险分级与整改复核', source_completeness: '原文完整性人工核对'
};
const allFacts = facts => [...new Set([...Object.keys(FACTS), ...Object.keys(facts || {})])].map(key => ({key, value: facts?.[key]?.value || '', confirmed: Boolean(facts?.[key]?.confirmed), source: facts?.[key]?.source || ''}));
export function projectSummary(project) {
  return h('div', {class: 'stack'}, definition([['项目名称', project.name], ['业务类型', BUSINESS[project.business_type]], ['地区', project.region], ['委托方', project.client], ['截止时间', dateTime(project.deadline)], ['服务范围', project.scope], ['项目版本', 'v' + project.version]]),
    serverText('当前服务器事实', Object.entries(project.facts || {}).map(([key, f]) => `${FACTS[key] || key}：${f.value}\n${f.confirmed ? '已确认' : '待确认'}；依据：${f.source}`).join('\n\n')));
}
export async function editProject(projectId, onSaved) {
  const original = projectId ? (await api('/api/projects/' + projectId)).item : null;
  const initial = {
    name: original?.name || '', business_type: original?.business_type || 'supervision', region: original?.region || '', client: original?.client || '', scope: original?.scope || '',
    deadline_local: inputDateTime(original?.deadline), fact_rows: allFacts(original?.facts), expected_version: original?.version
  };
  const dialog = modal(original ? '项目资料与已确认事实' : '新建投标项目', {wide: true});
  if (original?.archived) {
    dialog.body.append(notice('已归档项目只读保留，需先取消归档才能修改。', 'warn'), h('div', {class: 'top-space'}, projectSummary(original)));
    return;
  }
  const form = editorForm({
    key: 'project:' + (projectId || 'new'), initial,
    build(model, editor) {
      const factsBox = h('div');
      function renderFacts() {
        factsBox.replaceChildren(...model.fact_rows.map((fact, index) => h('div', {class: 'fact-row'},
          h('h4', {}, FACTS[fact.key] || '自定义事实'),
          h('div', {class: 'form-grid'}, bind(fact, 'key', '事实键', {required: true, maxLength: 100, readOnly: Boolean(FACTS[fact.key]), hint: '模板根据此键引用事实。'}), bind(fact, 'value', '事实内容（200 字以内）', {maxLength: 200, placeholder: '未知请留空，绝不自动编造'})),
          bind(fact, 'source', '依据或来源', {maxLength: 500, placeholder: '原文位置、已核验资料或人工确认依据'}),
          actions(checkbox(fact, 'confirmed', '我已人工确认此项事实'), button('移除此项', () => { model.fact_rows.splice(index, 1); renderFacts(); editor.changed(); }, 'quiet small')))));
      }
      renderFacts();
      return h('div', {}, notice('内容修改会使内部复核失效。仅已确认的事实用于本地模板组装；留空事实不会提交。TIS 地区规则与独立性须逐项目核对。'),
        h('div', {class: 'form-grid top-space'}, bind(model, 'name', '项目名称', {required: true, maxLength: 200}), bind(model, 'business_type', '业务类型', {options: BUSINESS, disabled: Boolean(original?.current_draft_id), hint: original?.current_draft_id ? '已有草稿，业务类型不可更改。' : ''}),
          bind(model, 'region', '项目地区', {maxLength: 200}), bind(model, 'client', '委托方', {maxLength: 200}), bind(model, 'deadline_local', '投标截止时间', {type: 'datetime-local', hint: '使用当前电脑时区，提交时转换为带时区时间。'}),
          bind(model, 'scope', '服务范围', {type: 'textarea', maxLength: 20000, className: 'span-two'})),
        h('section', {class: 'form-section'}, h('h3', {}, '项目事实与依据'), factsBox, button('＋ 添加自定义事实', () => { model.fact_rows.push({key: '', value: '', confirmed: false, source: ''}); renderFacts(); editor.changed(); }, 'small')));
    },
    async save(model) {
      const facts = {};
      for (const row of model.fact_rows) {
        if (!row.value.trim()) { if (row.confirmed) throw new Error('已确认事实必须填写内容：' + (FACTS[row.key] || row.key)); continue; }
        const key = row.key.trim();
        if (!key) throw new Error('请填写事实键。');
        if (Object.hasOwn(facts, key)) throw new Error('事实键不可重复：' + key);
        if (row.confirmed && !row.source.trim()) throw new Error('已确认事实请填写依据：' + (FACTS[key] || key));
        Object.defineProperty(facts, key, {value: {value: row.value, confirmed: row.confirmed, source: row.source || '人工录入'}, enumerable: true});
      }
      const payload = {name: model.name, business_type: model.business_type, region: model.region, client: model.client, scope: model.scope, deadline: model.deadline_local ? new Date(model.deadline_local).toISOString() : null, facts};
      if (original) payload.expected_version = model.expected_version;
      return api('/api/projects' + (projectId ? '/' + projectId : ''), {method: original ? 'PUT' : 'POST', body: payload});
    },
    async refresh(model) {
      if (!projectId) return {view: notice('新建操作结果不确定，请先返回工作台检查是否已经创建，避免重复提交。', 'warn')};
      const data = await api('/api/projects/' + projectId);
      return versionRefresh(model, data, null, projectSummary(data.item));
    },
    async afterSave(result) { toast(original ? '项目与事实已保存，需重新核对与复核。' : '项目已创建。'); await dialog.close(true); await onSaved?.(result.item); },
    submitLabel: original ? '保存项目与事实' : '创建项目'
  });
  dialog.body.append(form.node);
}
export async function archiveProject(project, onSaved) {
  const latest = (await api('/api/projects/' + project.id)).item;
  const label = latest.archived ? '取消归档' : '归档项目';
  if (!(await confirmDialog(label, latest.archived ? '恢复后可继续编辑。归档状态变化会使原内部复核失效。' : '归档后项目只读，历史草稿与导出仍保留。可随时取消归档；当前内部复核将失效。', label))) return;
  await api('/api/projects/' + latest.id + '/archive', {method: 'POST', body: {expected_version: latest.version, archived: !latest.archived}});
  toast(label + '完成。'); await onSaved?.();
}
export async function deleteProject(project, onSaved) {
  if (!(await confirmDialog('删除已归档项目入口？', '仅移除项目入口；历史修订与证据仍保留在本机审计及备份中。此操作不能从工作台撤销。', '删除项目入口', true))) return;
  await api('/api/projects/' + project.id, {method: 'DELETE', body: {expected_version: project.version}});
  toast('项目入口已删除，历史证据仍保留。'); await onSaved?.();
}
export async function dashboard() {
  const [stats, projects] = await Promise.all([api('/api/dashboard'), api('/api/projects')]);
  let all = projects.items;
  const filter = {q: '', business_type: '', archived: 'false', status: ''};
  const results = h('div');
  const count = h('span', {class: 'list-count'});
  let requestNumber = 0;
  const refresh = () => window.dispatchEvent(new Event('request-refresh'));
  const create = () => editProject(null, project => { location.hash = '#projects/' + project.id + '/analysis'; });
  function showList() {
    const filtered = all.filter(p => (!filter.business_type || p.business_type === filter.business_type) && (!filter.status || p.review_status === filter.status) && (!filter.archived || String(p.archived) === filter.archived) && (!filter.q || p.name.toLocaleLowerCase().includes(filter.q.toLocaleLowerCase())));
    count.textContent = `共 ${filtered.length} 个项目`;
    if (!filtered.length) {
      results.replaceChildren(empty(all.length ? '没有符合条件的项目' : '把下一次投标，安排得更有序', all.length ? '调整关键词、业务类型或归档筛选后再试。' : '从一份招标文件开始，逐步完成条款确认、标书编制、报价与内部复核。所有数据留在本机。', button('＋ 新建项目', create, 'primary'), button('手动载入虚构演示', () => loadDemo(refresh))));
      return;
    }
    results.replaceChildren(h('div', {class: 'table-scroll'}, h('table', {}, h('thead', {}, h('tr', {}, ['项目 / 委托方', '业务类型', '地区', '截止时间', '状态', '操作'].map(label => h('th', {scope: 'col'}, label)))), h('tbody', {}, filtered.map(p => h('tr', {},
      h('td', {class: 'title-cell'}, h('strong', {}, h('a', {href: '#projects/' + p.id + '/analysis'}, p.name)), h('span', {class: 'muted small'}, p.client || '待补充委托方'), p.is_demo ? h('div', {class: 'top-space'}, badge('明确虚构 · 不可提交', 'warn')) : null),
      h('td', {}, badge(BUSINESS[p.business_type])), h('td', {}, p.region || '未设置'), h('td', {class: 'small'}, dateTime(p.deadline)), h('td', {}, projectBadge(p), h('div', {class: 'small muted'}, 'v' + p.version)),
      h('td', {}, actions(linkButton('进入项目', '#projects/' + p.id + '/analysis', 'small'), button(p.archived ? '取消归档' : '归档', () => archiveProject(p, refresh), 'quiet small')))))))));
  }
  async function search() {
    const ticket = ++requestNumber;
    results.replaceChildren(loading('正在检索项目…'));
    try { const data = await api('/api/projects' + query({q: filter.q, archived: filter.archived})); if (ticket !== requestNumber) return; all = data.items; showList(); }
    catch (error) { if (ticket === requestNumber) results.replaceChildren(errorPanel(error, search)); }
  }
  const searchForm = h('form', {class: 'toolbar', onsubmit: event => { event.preventDefault(); search(); }}, bind(filter, 'q', '项目搜索', {type: 'search', placeholder: '搜索项目名称', className: 'search'}),
    bind(filter, 'business_type', '业务类型', {options: {'': '全部业务', ...BUSINESS}, onChange: showList}), bind(filter, 'archived', '归档状态', {options: {'false': '进行中的项目', 'true': '已归档', '': '全部项目'}, onChange: search}),
    bind(filter, 'status', '复核状态', {options: {'': '全部状态', pending: '待内部复核', reviewed: '已内部复核'}, onChange: showList}), h('button', {type: 'submit', class: 'button'}, '搜索'));
  showList();
  const stat = (name, value, note, accent = false) => h('div', {class: 'stat' + (accent ? ' accent' : '')}, h('div', {class: 'label'}, name), h('div', {class: 'value'}, value), h('div', {class: 'note'}, note));
  return h('div', {class: 'page'}, pageHead('项目工作台', '从招标要求到成稿，让每一份依据、每一次修改都有迹可循。', 'WORKSPACE / 项目总览', button('刷新数据', refresh), button('＋ 新建项目', create, 'primary')),
    h('div', {class: 'stats'}, stat('进行中的项目', stats.active, '当前数据库 · 不含已归档', true), stat('已内部复核', stats.reviewed, '仅表示人工内部复核记录'), stat('企业资料', stats.materials, '资质 / 人员 / 项目业绩'), stat('模板与历史素材', stats.templates + stats.snippets, `${stats.templates} 份模板 · ${stats.snippets} 条素材`)),
    h('section', {class: 'card'}, h('header', {class: 'card-head'}, h('h2', {}, '我的投标项目'), count), searchForm, results),
    h('div', {class: 'welcome-strip'}, h('div', {}, h('h3', {}, '本地运行，审慎复用'), h('p', {}, `数据库共 ${stats.projects} 个项目，其中 ${stats.archived} 个已归档、${stats.demo} 个明确虚构演示。外部 AI 未接入，候选条款均需人工确认。`)), actions(button('手动载入虚构演示', () => loadDemo(refresh), 'small'), linkButton('查看使用指南', '#help', 'small'))));
}
export function projectFrame(ctx, stage) {
  const p = ctx.project;
  const content = h('div', {class: 'project-content'});
  const stages = [['analysis', '招标分析', '来源与条款'], ['drafting', '标书编制', '章节与依据'], ['quote', '商务报价', '计费与税率'], ['gendocs', '附件生成', '表格与横道图'], ['review', '复核导出', '意见与成果']];
  const node = h('div', {class: 'page'}, h('div', {class: 'project-banner'}, h('div', {}, h('div', {class: 'eyebrow'}, 'PROJECT / ' + BUSINESS[p.business_type]), h('h1', {}, p.name), h('div', {class: 'project-meta'}, h('span', {}, p.region || '地区待填写'), h('span', {}, p.client || '委托方待填写'), h('span', {}, '截止：' + dateTime(p.deadline)), h('span', {}, '项目 v' + p.version))),
    actions(projectBadge(p), button(p.archived ? '查看项目与事实' : '项目与事实', () => editProject(p.id, ctx.rerender)), button('操作记录', () => events(ctx), 'quiet'), button(p.archived ? '取消归档' : '归档', () => archiveProject(p, ctx.rerender), 'quiet'))),
    p.is_demo ? notice('本项目及演示资料均为虚构，仅用于软件流程试用，不可用于真实投标。', 'warn') : null,
    p.archived ? notice('项目已归档，只读保留。需先取消归档才能修改内容。', 'warn', actions(button('删除项目入口', () => deleteProject(p, () => { location.hash = '#dashboard'; }), 'danger small'))) : null,
    p.review_invalidated_reason && p.current_draft_id ? h('div', {class: 'small muted top-space'}, '复核状态说明：' + p.review_invalidated_reason) : null,
    h('nav', {class: 'stage-nav', 'aria-label': '项目五阶段'}, stages.map(([id, label, sub], index) => h('a', {href: '#projects/' + p.id + '/' + id, class: 'stage-link' + (id === stage ? ' active' : ''), ...(id === stage ? {'aria-current': 'step'} : {})}, h('span', {class: 'stage-number'}, String(index + 1).padStart(2, '0')), label, h('small', {}, sub)))), content);
  return {node, content};
}
async function events(ctx) {
  const records = (await api(ctx.base + '/events')).items;
  const dialog = modal('项目操作记录');
  const entity = {project: '项目', requirement: '需求', document: '招标来源', draft: '草稿', section: '章节', quote: '报价', review_decision: '人工意见', review_snapshot: '冻结快照', export: '导出'};
  const action = {save: '保存', content_changed: '内容变化', internally_reviewed: '完成内部复核', verify: '人工核验', delete: '删除', requirement_link_changed: '需求映射变化', section_edited: '编辑章节', snippet_inserted: '插入素材', manual_reconcile: '人工核对输入', bind_frozen_version: '绑定冻结版本', remap_regenerated_section: '重生章节映射', section_editor_link: '编辑器关联需求'};
  dialog.body.append(notice('最多显示最近 500 条记录。此单机版本无身份认证，日志不等同于具备身份认证的审批。'), h('div', {class: 'top-space'}, records.length ? records.map(record => {
    const [kind, verb] = record.action.split('.');
    return h('div', {class: 'version-entry'}, h('h3', {}, `${entity[kind] || kind} · ${action[verb] || verb}`), h('p', {}, dateTime(record.at)), h('p', {class: 'mono'}, record.entity_id));
  }) : empty('暂无记录', '后续项目变更会记录在本地数据库。')));
}
