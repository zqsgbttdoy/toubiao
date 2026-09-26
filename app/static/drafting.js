import {api, query} from './api.js';
import {h, actions, badge, notice, button, linkButton, card, empty, loading, errorPanel, bind, checkbox, checks, editorForm, modal, confirmDialog, guard, toast, SECTIONS, RESPONSE, reviewBadge, materialWarnings, dateTime, definition, detail, versionRefresh, serverText, short} from './ui.js';
import {viewResource, resourceContent} from './library.js';
import {editRequirement, showSource} from './analysis.js';

export function quoteText(quote) {
  if (!quote) return '【待填：服务报价及明确税率】';
  const lines = quote.lines.map(x => `${x.name}：${x.quantity}${x.unit} × ${x.unit_price}元 = ${x.amount}元；依据：${x.basis}`);
  lines.push(`不含税合计：${quote.subtotal}元`, `税率：${quote.tax_rate}；税额：${quote.tax}元`, `含税总价：${quote.total}元`, '税率确认依据：' + quote.tax_note);
  if (!quote.tax_confirmed) lines.push('【待填：税率尚未人工确认】');
  return lines.join('\n');
}
export async function selectResources(ctx) {
  const [data, templates, materials, snippets] = await Promise.all([ctx.refresh(), api('/api/templates' + query({business_type: ctx.project.business_type})), api('/api/materials' + query({business_type: ctx.project.business_type})), api('/api/snippets' + query({business_type: ctx.project.business_type}))]);
  const dialog = modal('选择项目模板、企业资料与历史素材', {wide: true});
  const initial = {expected_version: data.item.version, template_ids: data.item.selected_template_ids, material_ids: data.item.selected_material_ids, snippet_ids: data.item.selected_snippet_ids};
  const form = editorForm({key: 'selection:' + ctx.id, initial, submitLabel: '保存项目选用资料',
    build: model => h('div', {}, notice('只显示当前业务可用资源。修改选用内容会使草稿输入过期、内部复核失效。需求正在引用的证明材料不能直接取消选择。', 'warn'),
      h('div', {class: 'form-section top-space'}, h('h3', {}, '编制模板'), checks(model, 'template_ids', templates.items, {info: item => h('div', {}, actions(reviewBadge(item), badge(item.sections.length + ' 章'), badge('v' + item.version)), h('p', {}, item.source))})),
      h('div', {class: 'form-section'}, h('h3', {}, '企业资料 / 原始证明'), checks(model, 'material_ids', materials.items, {info: item => h('div', {}, materialWarnings(item, ctx.project.deadline), h('p', {}, item.scope || '尚未填写适用范围')), emptyText: '暂无适用资料，请先到企业资料库维护原始证明。'})),
      h('div', {class: 'form-section'}, h('h3', {}, '历史素材'), checks(model, 'snippet_ids', snippets.items, {info: item => h('div', {}, reviewBadge(item), h('p', {}, short(item.content))), emptyText: '暂无历史素材。此项可为空，不会编造素材。'}))),
    save: model => ctx.write('/selection', 'PUT', {expected_version: model.expected_version, template_ids: model.template_ids, material_ids: model.material_ids, snippet_ids: model.snippet_ids}),
    refresh: async model => { const fresh = await ctx.refresh(); return versionRefresh(model, fresh, null, definition([['当前项目版本', 'v' + fresh.item.version], ['当前模板数量', fresh.item.selected_template_ids.length], ['当前企业资料数量', fresh.item.selected_material_ids.length], ['当前素材数量', fresh.item.selected_snippet_ids.length]])); },
    afterSave: async () => { await dialog.close(true); toast('选用资料已保存，请更新草稿并重新复核。'); await ctx.rerender(); }, readonly: data.item.archived
  });
  dialog.body.append(form.node);
}
export function snapshotView(draft) {
  const snapshot = draft.input_snapshot;
  return h('div', {}, definition([['草稿代次', '第 ' + draft.generation + ' 稿'], ['草稿版本', 'v' + draft.version], ['生成时间', dateTime(draft.created_at)], ['输入项目版本', 'v' + draft.input_project_version], ['生成方式', draft.generation_method], ['输入指纹', draft.input_hash]]),
    h('div', {class: 'snapshot-grid'}, ['templates', 'materials', 'snippets'].map(kind => h('div', {class: 'snapshot-item'}, h('strong', {}, {templates: '模板来源', materials: '企业资料', snippets: '历史素材'}[kind]), snapshot[kind].length ? snapshot[kind].map(item => h('p', {}, `${item.name || item.title} · v${item.version}`)) : '未选用'))),
    detail('生成时项目事实', h('div', {class: 'prewrap small'}, Object.entries(snapshot.project.facts || {}).map(([key, fact]) => `${key}：${fact.value}（${fact.confirmed ? '已确认' : '待确认'}）\n依据：${fact.source}`).join('\n\n') || '尚无事实')),
    detail('生成时权威报价', h('div', {class: 'prewrap small'}, quoteText(draft.quote_snapshot))),
    detail('原文与需求输入', h('div', {class: 'small prewrap'}, snapshot.documents.map(d => `${d.title} · 来源 v${d.source_version}`).join('\n')), h('p', {class: 'small top-space'}, `${snapshot.requirements.length} 条需求，其中 ${snapshot.requirements.filter(r => r.confirmed).length} 条已确认。`)),
    draft.reconciliations.length ? detail('人工核对记录', draft.reconciliations.map(record => h('div', {class: 'version-entry'}, h('h3', {}, record.reviewer), h('p', {}, dateTime(record.at)), h('p', {class: 'prewrap'}, record.note)))) : null);
}
async function reconcile(ctx, draft) {
  await ctx.refresh();
  if ((ctx.data.quote?.version || 0) !== (draft.quote_snapshot?.version || 0)) throw new Error('报价已变化，必须重新生成草稿，不能通过核对同步。旧稿会保留。');
  const dialog = modal('逐章核对后同步草稿输入');
  const form = editorForm({key: `reconcile:${ctx.id}:${draft.id}`, initial: {expected_version: ctx.project.version, reviewer: '', note: '', confirmed: false}, submitLabel: '记录核对并同步输入',
    build: model => h('div', {}, notice('只有在逐章核对所有变更、来源和引用版本后才能使用。此操作不自动改写正文，不代替技术、商务、资质三类复核。报价变更必须重新生成。', 'warn'),
      bind(model, 'reviewer', '核对人', {required: true, maxLength: 200, className: 'top-space'}), bind(model, 'note', '核对内容、变更及处理说明', {type: 'textarea', required: true, maxLength: 20000}), checkbox(model, 'confirmed', '我已逐章核对当前事实、需求、资料及引用版本', {required: true})),
    save: model => ctx.write('/drafts/' + draft.id + '/reconcile', 'POST', {expected_version: model.expected_version, reviewer: model.reviewer, note: model.note, confirmed: model.confirmed}),
    refresh: async model => { const fresh = await ctx.refresh(); return versionRefresh(model, fresh, null, fresh.draft ? snapshotView(fresh.draft) : notice('当前无草稿，请返回编制页。')); },
    afterSave: async () => { await dialog.close(true); toast('草稿输入已同步，仍须完成三类内部复核。'); await ctx.rerender(); }
  });
  dialog.body.append(form.node);
}
export async function draftingPage(ctx, preferredSection = '') {
  const [drafts, templates, materials, snippets] = await Promise.all([api(ctx.base + '/drafts'), api('/api/templates' + query({business_type: ctx.project.business_type})), api('/api/materials' + query({business_type: ctx.project.business_type})), api('/api/snippets' + query({business_type: ctx.project.business_type}))]);
  let draft = drafts.current;
  let sectionId = preferredSection || draft?.sections[0]?.id;
  let currentEditor = null;
  const editorSlot = h('section', {class: 'card'});
  const outline = h('div', {class: 'outline'});
  const right = h('aside', {class: 'card draft-sidebar'});
  const stateSlot = h('div', {class: 'bottom-space'});
  const historyState = {id: draft?.id || ''};
  const sourceLists = {template: templates.items, material: materials.items, snippet: snippets.items, document: ctx.data.documents};
  const resourceName = ref => {
    const items = draft && !draft.is_current ? draft.input_snapshot[ref.kind + 's'] : sourceLists[ref.kind];
    const item = items?.find(row => row.id === ref.id);
    return item?.name || item?.title || ref.id;
  };
  const editable = () => Boolean(draft?.is_current && !ctx.project.archived);
  const reload = async () => { await ctx.rerender({section: sectionId}); };
  async function generate() {
    if (!(await guard(editorSlot))) return;
    if (drafts.current && !(await confirmDialog('重新生成新草稿？', '按当前已确认事实、选用资料和报价重新组装。人工修改不会自动合并到新稿；旧稿及其正文永久保留，可从历史版本查看。未保存输入仅暂存，请先保存重要修改。', '确认重新生成'))) return;
    await ctx.write('/drafts/generate', 'POST', {expected_version: ctx.project.version, confirm_regenerate: Boolean(drafts.current)});
    toast('已按本地规则生成新草稿，请逐章补充与核对。'); await ctx.rerender();
  }
  function referenceEditor(model, editor, section) {
    const list = h('div');
    const choice = {resource: ''};
    const available = Object.entries(sourceLists).flatMap(([kind, items]) => items.filter(item => kind === 'document' || ctx.project['selected_' + kind + '_ids'].includes(item.id)).map(item => ({kind, item})));
    const options = {'': '选择项目已选用的来源', ...Object.fromEntries(available.map(({kind, item}) => [kind + ':' + item.id, `${{template: '模板', material: '资料', snippet: '素材', document: '招标来源'}[kind]} · ${item.name || item.title} · v${item.version}`]))};
    const renderRefs = () => list.replaceChildren(...model.references.map((ref, index) => {
      const current = sourceLists[ref.kind]?.find(item => item.id === ref.id);
      const stale = !current || current.version !== ref.version;
      const provenance = ref.kind === 'template' && ref.id === section.template_id && ref.version === section.template_version;
      return h('div', {class: 'reference-line'}, h('div', {}, h('span', {}, `${resourceName(ref)} · v${ref.version}`), stale ? h('div', {}, badge('来源版本已变化', 'warn')) : null, provenance ? h('div', {class: 'muted small'}, '生成模板出处 · 保留') : null), actions(
        button('查看当前来源', async () => {
          if (ref.kind !== 'document') return viewResource(ref.kind + 's', ref.id, {manage: false});
          const source = (await api(ctx.base + '/documents/' + ref.id)).item;
          const dialog = modal('章节引用的招标来源', {wide: true});
          dialog.body.append(definition([['来源', source.title], ['来源版本', 'v' + source.source_version], ['说明', source.source_note]]), serverText('完整来源内容', source.blocks.map(block => block.text).join('\n\n')));
        }, 'quiet small'),
        stale && current && !provenance ? button('核对版本', async () => {
          const latest = (await api(ref.kind === 'document' ? ctx.base + '/documents/' + ref.id : '/api/' + ref.kind + 's/' + ref.id)).item;
          const dialog = modal('引用版本核对', {wide: true});
          dialog.body.append(notice(`当前引用 v${ref.version}，服务器为 v${latest.version}。只更新引用版本不会自动替换已编辑正文。`, 'warn'), ref.kind === 'document' ? serverText('当前来源', latest.blocks.map(b => b.text).join('\n\n')) : resourceContent(ref.kind + 's', latest), actions(button('已核对正文，更新此引用版本', async () => { model.references[index] = {kind: ref.kind, id: ref.id, version: latest.version}; sourceLists[ref.kind] = sourceLists[ref.kind].map(x => x.id === latest.id ? latest : x); renderRefs(); editor.changed(); await dialog.close(true); }, 'primary')));
        }, 'small') : null,
        !provenance ? button('移除', () => { model.references.splice(index, 1); renderRefs(); editor.changed(); }, 'quiet small') : null));
    }));
    renderRefs();
    return h('div', {}, notice('生成模板出处始终保留。模板源版本变化时应重新生成；其他引用核对后可更新版本，再人工核对草稿输入。'), list,
      bind(choice, 'resource', '添加引用', {options, className: 'top-space'}), button('加入章节引用', async () => {
        if (!choice.resource) throw new Error('请选择来源。');
        const [kind, id] = choice.resource.split(':');
        const current = (await api(kind === 'document' ? ctx.base + '/documents/' + id : '/api/' + kind + 's/' + id)).item;
        if (model.references.some(ref => ref.kind === kind && ref.id === id && ref.version === current.version)) return;
        model.references.push({kind, id, version: current.version}); renderRefs(); editor.changed();
      }, 'small'));
  }
  function bodyEditor(model, section) {
    const block = quoteText(draft.quote_snapshot);
    if (!section.contains_quote || !model.body.includes(block)) return bind(model, 'body', '章节正文', {type: 'textarea', maxLength: 100000, class: 'body-editor', rows: 20});
    const start = model.body.indexOf(block);
    const parts = {before: model.body.slice(0, start), after: model.body.slice(start + block.length)};
    const combine = () => { model.body = parts.before + block + parts.after; };
    return h('div', {}, notice('中间为后端报价快照的权威块，保持原文只读。可编辑前后说明；修改金额请到商务报价页保存后重新生成。'),
      bind(parts, 'before', '报价块之前的正文', {type: 'textarea', rows: 5, maxLength: 100000, onChange: combine, className: 'top-space'}), h('div', {class: 'readonly-note prewrap'}, block), bind(parts, 'after', '报价块之后的正文', {type: 'textarea', rows: 5, maxLength: 100000, onChange: combine}));
  }
  function drawSection() {
    const section = draft?.sections.find(s => s.id === sectionId) || draft?.sections[0];
    sectionId = section?.id;
    drawOutline();
    if (!section) { editorSlot.replaceChildren(empty('没有可编辑章节', '请先选择适用模板，再生成草稿。')); return; }
    if (!editable()) {
      currentEditor = null;
      editorSlot.replaceChildren(h('div', {class: 'paper'}, actions(badge(draft.is_current ? '归档项目 · 只读' : '历史草稿 · 只读'), badge(SECTIONS[section.category])), h('h2', {class: 'top-space'}, section.title), h('div', {class: 'paper-meta'}, `第 ${draft.generation} 稿 · 章节 v${section.version} · ${dateTime(section.updated_at)}`), h('div', {class: 'readonly-body'}, section.body), detail('引用来源', section.references.map(ref => h('p', {class: 'small'}, `${resourceName(ref)} · v${ref.version}`)))));
      drawRight(); return;
    }
    const initial = {expected_version: ctx.project.version, entity_version: section.version, body: section.body, requirement_ids: section.requirement_ids, references: section.references};
    currentEditor = editorForm({key: `section:${ctx.id}:${draft.id}:${section.id}`, initial,
      build: (model, editor) => h('div', {}, bodyEditor(model, section), detail('关联条款（保存后同步响应章节映射）', checks(model, 'requirement_ids', ctx.data.requirements, {label: req => short(req.text, 180), info: req => actions(badge(RESPONSE[req.response_status]), badge(req.confirmed ? '已确认' : '待确认', req.confirmed ? 'good' : 'warn')), emptyText: '尚无条款，请先在招标分析阶段录入。'})), detail('章节引用与版本', referenceEditor(model, editor, section))),
      async save(model) {
        if (section.contains_quote && !model.body.includes(quoteText(draft.quote_snapshot))) throw new Error('必须保留完整权威报价块。请恢复报价块后保存，或修改报价并重新生成。');
        if (model.body.length > 100000) throw new Error('章节正文不能超过 100000 字。');
        return ctx.write('/drafts/' + draft.id + '/sections/' + section.id, 'PUT', {expected_version: model.expected_version, entity_version: model.entity_version, body: model.body, requirement_ids: model.requirement_ids, references: model.references.map(ref => ({kind: ref.kind, id: ref.id, version: ref.version}))});
      },
      async refresh(model) {
        const fresh = await ctx.refresh();
        if (fresh.draft?.id !== draft.id) throw new Error('已生成新的当前草稿，本稿成为只读。你的文本已保留，请进入新稿后人工合并，不能覆盖旧稿。');
        const latest = fresh.draft.sections.find(s => s.id === section.id);
        if (!latest) throw new Error('当前章节已不存在，请保留输入并刷新。');
        return versionRefresh(model, fresh, latest, h('div', {}, serverText('服务器最新章节正文', latest.body), definition([['当前章节版本', 'v' + latest.version], ['关联条款数量', latest.requirement_ids.length], ['引用数量', latest.references.length]])));
      },
      afterSave: async () => { toast('章节已保存。关联条款变化后请核对草稿输入。'); await reload(); }, submitLabel: '保存当前章节'
    });
    editorSlot.replaceChildren(h('div', {class: 'paper'}, actions(badge(SECTIONS[section.category]), badge(section.manually_edited ? '已人工编辑' : '规则组装'), badge('章节 v' + section.version)), h('h2', {class: 'top-space'}, section.title), h('div', {class: 'paper-meta'}, `第 ${draft.generation} 稿 · ${dateTime(section.updated_at)} · 明确保存，不自动覆盖`), currentEditor.node));
    drawRight();
  }
  function drawOutline() {
    outline.replaceChildren(...(draft?.sections || []).map((s, i) => button('', async () => { if (s.id === sectionId) return; if (!(await guard(editorSlot))) return; sectionId = s.id; drawSection(); }, 'outline-button' + (sectionId === s.id ? ' active' : ''), {'aria-current': sectionId === s.id ? 'true' : 'false'})));
    [...outline.children].forEach((node, i) => { const s = draft.sections[i]; node.className = 'outline-button' + (s.id === sectionId ? ' active' : ''); node.append(h('span', {}, `${String(i + 1).padStart(2, '0')}  ${s.title}`), h('small', {}, `${SECTIONS[s.category]} · ${s.manually_edited ? '人工编辑' : '规则组装'}`)); });
  }
  function drawState() {
    const quoteChanged = (ctx.data.quote?.version || 0) !== (draft?.quote_snapshot?.version || 0);
    stateSlot.replaceChildren(draft ? h('div', {}, actions(badge('第 ' + draft.generation + ' 稿'), badge(draft.is_current ? '当前草稿' : '历史只读'), draft.stale ? badge('输入已过期', 'bad') : badge('输入快照一致', 'good')),
      draft.stale && draft.is_current ? h('div', {class: 'top-space'}, notice(quoteChanged ? '报价与草稿快照已不同，必须重新生成。不能以“已核对”替代更新报价正文。' : '事实、条款或选用资料已变化。请重新生成，或逐章人工核对正文及来源版本后同步输入。', 'warn', actions(button('重新生成', generate, 'small', {disabled: ctx.project.archived}), button('逐章核对并同步', async () => { if (!(await guard(editorSlot))) return; await reconcile(ctx, draft); }, 'small', {disabled: ctx.project.archived || quoteChanged})))) : null) : notice('尚未生成草稿。先选用模板和企业资料，补充事实及报价，再生成可逐章编辑的初稿。'));
  }
  let sideTab = 'requirements';
  function drawRight() {
    const tabs = actions(...[['requirements', '需求'], ['selected', '所选资料'], ['snippets', '素材检索']].map(([id, label]) => button(label, () => { sideTab = id; drawRight(); }, 'small' + (sideTab === id ? ' active' : ''))));
    tabs.classList.add('side-tabs');
    const body = h('div');
    if (draft && !draft.is_current) body.append(notice('本栏展示当前项目资料，不是旧稿生成时的依据。历史依据请查看上方输入快照；旧稿正文只读。', 'warn'));
    if (sideTab === 'requirements') body.append(...ctx.data.requirements.map(req => h('div', {class: 'mini-resource'}, h('strong', {}, short(req.text, 160)), actions(badge(RESPONSE[req.response_status]), req.mandatory ? badge('强制', 'bad') : null), actions(button('确认 / 响应', () => editRequirement(ctx, req.id), 'quiet small'), req.document_id ? button('原文', () => showSource(ctx, req.document_id, req.block_id), 'quiet small') : null))));
    if (sideTab === 'selected') {
      for (const [kind, items] of Object.entries(sourceLists)) {
        if (kind === 'document') continue;
        body.append(...items.filter(item => ctx.project['selected_' + kind + '_ids'].includes(item.id)).map(item => h('div', {class: 'mini-resource'}, h('strong', {}, item.name || item.title), kind === 'material' ? materialWarnings(item, ctx.project.deadline) : reviewBadge(item), h('p', {}, 'v' + item.version), button('查看来源', () => viewResource(kind + 's', item.id, {manage: false}), 'quiet small'))));
      }
    }
    if (sideTab === 'snippets') {
      const searchState = {q: '', tag: ''};
      const results = h('div');
      let ticket = 0;
      const search = async () => {
        const current = ++ticket; results.replaceChildren(loading('检索素材…'));
        try {
          const rows = (await api('/api/snippets' + query({...searchState, business_type: ctx.project.business_type}))).items;
          if (current !== ticket) return;
          results.replaceChildren(...(rows.length ? rows.map(item => h('div', {class: 'mini-resource'}, h('strong', {}, item.title), reviewBadge(item), h('p', {class: 'top-space'}, short(item.content, 200)), actions(button('查看', () => viewResource('snippets', item.id, {manage: false}), 'small quiet'), button('插入此章', async () => {
            if (!currentEditor || currentEditor.dirty || currentEditor.busy) { toast('请先处理保留输入并保存当前章节，再插入素材，避免丢失正文。', 'error'); return; }
            if (!(await confirmDialog('插入历史素材？', '将原文追加到当前章节，并记录素材来源版本。尚未选用的素材会加入项目选用列表；插入后需核对适用性并同步草稿输入。', '确认插入'))) return;
            const section = draft.sections.find(s => s.id === sectionId);
            await ctx.write('/drafts/' + draft.id + '/sections/' + sectionId + '/insert-snippet', 'POST', {expected_version: ctx.project.version, entity_version: section.version, snippet_id: item.id, snippet_version: item.version});
            toast('素材已插入，来源版本已记录。'); await reload();
          }, 'primary small', {disabled: !editable()})))) : [notice('没有符合条件的素材。可在历史素材库上传并选择来源块。')]));
        } catch (error) { if (current === ticket) results.replaceChildren(errorPanel(error, search)); }
      };
      body.append(h('form', {onsubmit: event => { event.preventDefault(); search(); }}, bind(searchState, 'q', '素材关键词', {type: 'search', placeholder: '搜索已沉淀内容'}), bind(searchState, 'tag', '标签', {placeholder: '完整标签'}), h('button', {class: 'button small', type: 'submit'}, '检索')), h('div', {class: 'top-space'}, results)); search();
    }
    if (!body.childNodes.length) body.append(notice('暂无内容，请先维护并选用资料。'));
    right.replaceChildren(h('div', {class: 'side-panel'}, h('h3', {}, '编制依据'), tabs, body));
  }
  const versions = bind(historyState, 'id', '草稿版本', {options: {'': '请选择草稿', ...Object.fromEntries(drafts.items.map(item => [item.id, `第 ${item.generation} 稿 · ${item.id === drafts.current?.id ? '当前' : '历史只读'} · ${dateTime(item.created_at)}`]))}});
  versions.control.addEventListener('change', async () => {
    if (!historyState.id) { historyState.id = draft?.id || ''; versions.control.value = historyState.id; return; }
    const target = historyState.id;
    if (!(await guard(editorSlot))) { historyState.id = draft?.id || ''; versions.control.value = historyState.id; return; }
    versions.control.disabled = true;
    editorSlot.inert = true; outline.inert = true; right.inert = true;
    editorSlot.setAttribute('aria-busy', 'true');
    try { draft = (await api(ctx.base + '/drafts/' + target)).item; sectionId = draft.sections[0]?.id; drawState(); drawSection(); }
    catch (error) { historyState.id = draft?.id || ''; versions.control.value = historyState.id; editorSlot.prepend(errorPanel(error)); }
    finally {
      versions.control.disabled = false;
      editorSlot.inert = false; outline.inert = false; right.inert = false;
      editorSlot.removeAttribute('aria-busy');
    }
  });
  drawState(); drawSection();
  return h('div', {}, h('div', {class: 'stage-head'}, h('div', {}, h('h2', {}, '标书编制'), h('p', {}, '目录、正文与依据联动 · 本地规则组装，不接入云端 AI')), actions(button('选用模板与资料', () => selectResources(ctx), '', {disabled: ctx.project.archived}), button(drafts.current ? '重新生成草稿' : '生成初稿', generate, 'primary', {disabled: ctx.project.archived}))),
    h('div', {class: 'toolbar bottom-space'}, versions, button('查看输入快照', () => { const dialog = modal('草稿输入与来源快照', {wide: true}); dialog.body.append(snapshotView(draft)); }, 'small', {disabled: !draft})), stateSlot,
    draft ? h('div', {class: 'draft-layout'}, h('section', {class: 'card'}, h('header', {class: 'card-head'}, h('h3', {}, '章节目录'), h('span', {class: 'inline-count'}, draft.sections.length)), outline), editorSlot, right) : card(null, empty('从有依据的初稿开始', '请先选择适用模板和企业资料，并在商务报价阶段保存报价与税率。未确认事实将保留待填提示，不会自动编造。', button('选择模板与资料', () => selectResources(ctx), '', {disabled: ctx.project.archived}), button('生成初稿', generate, 'primary', {disabled: ctx.project.archived}))),
    h('p', {class: 'small muted top-space'}, '所有内容变更使内部复核失效。旧稿只读、原始附件及来源版本保留；最终 Word/WPS 打印排版仍需人工确认。'));
}
