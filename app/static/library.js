import {api, query, uploadShared} from './api.js';
import {h, actions, badge, notice, button, pageHead, empty, loading, errorPanel, field, bind, checkbox, checks, businessChecks, editorForm, modal, confirmDialog, toast, BUSINESS, KINDS, SECTIONS, reviewBadge, materialWarnings, dateTime, definition, detail, serverText, fileRow, short, locator} from './ui.js';

export const LIBRARIES = {
  templates: {title: '模板库', singular: '模板', eyebrow: 'TEMPLATES / 编制起点', description: '把成熟结构留在本地，以清晰的章节和来源组织每一份标书。内置模板先复制，再按企业需要修改。'},
  materials: {title: '企业资料', singular: '企业资料', eyebrow: 'CREDENTIALS / 企业依据', description: '统一维护资质、人员证照和项目业绩。附件原件、有效期、适用范围与人工核验缺一不可。'},
  snippets: {title: '历史素材', singular: '历史素材', eyebrow: 'KNOWLEDGE / 审慎复用', description: '从本地历史文档选取内容块，沉淀可追溯的编制素材。历史经验不是当前项目事实。'}
};
const notifyChanged = () => window.dispatchEvent(new Event('request-refresh'));
export async function libraryPage(type) {
  const config = LIBRARIES[type];
  const state = {q: '', business_type: '', tag: ''};
  const results = h('div');
  const count = h('span', {class: 'list-count'});
  let requestNumber = 0;
  async function search() {
    const ticket = ++requestNumber;
    results.replaceChildren(loading());
    try {
      const data = await api('/api/' + type + query(state));
      if (ticket !== requestNumber) return;
      count.textContent = `${data.items.length} 项 · 已人工核验优先`;
      if (!data.items.length) { results.replaceChildren(empty('从第一份可靠资料开始', '没有符合筛选条件的内容。可调整筛选，或创建并人工核验后再选用于项目。', button('＋ 新建' + config.singular, () => editResource(type, null, search), 'primary'))); return; }
      results.replaceChildren(h('div', {class: 'resource-grid'}, data.items.map(item => h('article', {class: 'resource-card'},
        h('div', {class: 'resource-card-main'}, h('div', {class: 'resource-heading'}, h('span', {class: 'resource-symbol'}, type === 'templates' ? 'TPL / ' + item.sections.length : type === 'materials' ? KINDS[item.kind] : 'EXCERPT'), reviewBadge(item)),
          h('h3', {}, item.name || item.title), h('p', {}, short(type === 'templates' ? item.source : type === 'materials' ? item.description || item.scope : item.content)),
          actions(item.builtin ? badge('内置参考') : null, item.is_demo ? badge('虚构演示', 'warn') : null), h('p', {class: 'top-space'}, item.business_types.map(b => BUSINESS[b]).join(' / ')),
          type === 'materials' ? h('div', {class: 'top-space'}, materialWarnings(item), h('p', {class: 'top-space'}, item.valid_until ? '有效至 ' + item.valid_until : item.validity_note || '尚未说明有效期')) : null,
          h('div', {}, item.tags.map(tag => h('span', {class: 'tag'}, tag)))),
        h('div', {class: 'resource-card-footer'}, h('span', {}, 'v' + item.version), actions(button('查看详情', () => viewResource(type, item.id, {onChanged: search}), 'small'), button(item.builtin ? '复制' : '编辑', () => item.builtin ? copyTemplate(item, search) : editResource(type, item.id, search), 'small quiet')))))));
    } catch (error) { if (ticket === requestNumber) results.replaceChildren(errorPanel(error, search)); }
  }
  const toolbar = h('form', {class: 'toolbar', onsubmit: event => { event.preventDefault(); search(); }}, bind(state, 'q', '关键词', {type: 'search', placeholder: '名称、内容或来源', className: 'search'}), bind(state, 'business_type', '适用业务', {options: {'': '全部业务', ...BUSINESS}}), bind(state, 'tag', '标签', {placeholder: '按完整标签筛选', maxLength: 200}), h('button', {class: 'button', type: 'submit'}, '检索'));
  await search();
  return h('div', {class: 'page'}, pageHead(config.title, config.description, config.eyebrow, button('＋ 新建' + config.singular, () => editResource(type, null, search), 'primary')),
    h('section', {class: 'card'}, h('header', {class: 'card-head'}, h('h2', {}, '本地' + config.singular), count), toolbar, results));
}
export function resourceContent(type, item) {
  const files = h('div');
  const content = h('div', {class: 'resource-detail stack'}, actions(reviewBadge(item), badge('v' + item.version), item.builtin ? badge('内置参考 · 先复制再编辑') : null, item.is_demo ? badge('虚构演示', 'warn') : null),
    definition([['名称', item.name || item.title], ['适用业务', item.business_types.map(b => BUSINESS[b]).join(' / ')], ['标签', item.tags.join('、') || '无标签'], ['更新时间', dateTime(item.updated_at)]]));
  if (type === 'templates') content.append(definition([['来源', item.source]]), ...item.sections.map(s => detail(s.title + ' · ' + SECTIONS[s.category], h('p', {class: 'small muted'}, '章节键：' + s.key), h('div', {class: 'prewrap small top-space'}, s.body))));
  if (type === 'materials') {
    content.append(materialWarnings(item), definition([['资料类型', KINDS[item.kind]], ['有效起始', item.valid_from], ['有效截止', item.valid_until], ['有效性说明', item.validity_note], ['适用范围', item.scope], ['资料说明', item.description]]), h('section', {}, h('h3', {}, '原始证明附件'), files));
    const readFiles = async () => {
      files.replaceChildren(loading('正在读取附件…'));
      try { const rows = await Promise.all(item.file_ids.map(id => api('/api/files/' + id))); files.replaceChildren(...(rows.length ? rows.map(row => fileRow(row.item)) : [notice('尚未关联证明附件。', 'warn')])); }
      catch (error) { files.replaceChildren(errorPanel(error, readFiles)); }
    };
    readFiles();
  }
  if (type === 'snippets') {
    content.append(h('div', {}, h('h3', {}, '素材正文'), h('div', {class: 'prewrap top-space'}, item.content)), definition([['来源版本', 'v' + item.source_version], ['来源 SHA-256', item.source_sha256]]), detail('选用的原始内容块', ...item.source_blocks.map(b => h('article', {class: 'source-block'}, h('div', {class: 'source-locator'}, locator(b.locator)), h('div', {class: 'prewrap'}, b.text)))), files);
    api('/api/files/' + item.source_file_id).then(row => files.replaceChildren(fileRow(row.item))).catch(error => files.replaceChildren(errorPanel(error)));
  }
  if (item.verification) content.append(detail('人工核验记录', definition([['核验人', item.verification.reviewer], ['意见', item.verification.opinion], ['核验依据', item.verification.evidence_note], ['核验时间', dateTime(item.verification.at)], ['内容版本', 'v' + item.verification.content_version]]), h('div', {class: 'top-space'}, notice(item.verification.disclaimer, 'warn'))));
  else content.append(notice('尚无人工核验记录。内容和附件均不自动等于真实、有效或适用。', 'warn'));
  return content;
}
export async function viewResource(type, id, {manage = true, onChanged = notifyChanged} = {}) {
  const item = (await api('/api/' + type + '/' + id)).item;
  const dialog = modal(LIBRARIES[type].singular + '详情', {wide: true});
  dialog.body.append(resourceContent(type, item));
  dialog.body.append(h('div', {class: 'top-space'}, actions(button('修订版本', () => resourceHistory(type, id)),
    manage ? button(item.builtin ? '复制为企业模板' : '编辑内容', async () => { await dialog.close(true); if (item.builtin) await copyTemplate(item, onChanged); else await editResource(type, id, onChanged); }) : null,
    manage ? button('记录人工核验', async () => { await dialog.close(true); await verifyResource(type, id, onChanged); }, 'primary') : null,
    manage && !item.builtin ? button('删除', async () => {
      if (!(await confirmDialog('删除' + LIBRARIES[type].singular + '？', '被项目选用的资料不能删除，请先解除关联。历史快照及修订证据仍会保留。', '删除', true))) return;
      await api('/api/' + type + '/' + id, {method: 'DELETE', body: {expected_version: item.version}});
      await dialog.close(true); toast('已删除资源入口，历史快照仍保留。'); await onChanged();
    }, 'danger') : null)));
}
async function resourceHistory(type, id) {
  const versions = (await api('/api/' + type + '/' + id + '/versions')).items;
  const dialog = modal('修订历史 · 只读');
  dialog.body.append(versions.length ? h('div', {}, versions.map(item => h('div', {class: 'version-entry'}, h('h3', {}, `版本 ${item.version} · ${item.name || item.title}`), h('p', {}, dateTime(item.updated_at)), actions(reviewBadge(item), button('查看此版本', () => { const versionDialog = modal('历史版本 v' + item.version + ' · 只读', {wide: true}); versionDialog.body.append(resourceContent(type, item)); }, 'small'))))) : empty('暂无版本', '保存后的版本会保留在本机。'));
}
export async function copyTemplate(template, onSaved = notifyChanged) {
  const latest = (await api('/api/templates/' + template.id)).item;
  const dialog = modal('复制为可编辑企业模板', {small: true});
  const form = editorForm({key: 'copy:' + latest.id, initial: {expected_version: latest.version, name: (latest.name + ' · 企业副本').slice(0, 200)},
    build: model => h('div', {}, notice('保留原始内置模板及来源，创建独立副本后才能编辑。'), bind(model, 'name', '新模板名称', {required: true, maxLength: 200, className: 'top-space'})),
    save: model => api('/api/templates/' + latest.id + '/copy', {method: 'POST', body: {expected_version: model.expected_version, name: model.name}}),
    refresh: async model => { const fresh = (await api('/api/templates/' + latest.id)).item; return {view: resourceContent('templates', fresh), apply: () => { model.expected_version = fresh.version; }}; },
    afterSave: async result => { await dialog.close(true); toast('已创建企业模板副本。'); await onSaved(); await editResource('templates', result.item.id, onSaved); }, submitLabel: '确认复制'
  });
  dialog.body.append(form.node);
}
async function verifyResource(type, id, onSaved) {
  const item = (await api('/api/' + type + '/' + id)).item;
  const dialog = modal('人工核验 · ' + (item.name || item.title));
  const form = editorForm({key: `verify:${type}:${id}`, initial: {expected_version: item.version, reviewer: '', opinion: '', status: 'approved', evidence_note: ''}, submitLabel: '保存人工核验记录',
    build: model => h('div', {}, notice('这是无身份认证的单机人工记录，不是软件判真。请自行核对原件、适用范围、有效期及来源。核验会递增资源和关联项目版本，使原复核失效。', 'warn'),
      h('div', {class: 'form-grid top-space'}, bind(model, 'reviewer', '核验人', {required: true, maxLength: 200}), bind(model, 'status', '核验结论', {options: {approved: '人工核验通过', rejected: '人工核验未通过'}})), bind(model, 'opinion', '核验意见', {type: 'textarea', required: true, maxLength: 20000}), bind(model, 'evidence_note', '核验依据', {required: true, maxLength: 200, placeholder: '原件、官方查询或内部核查记录'})),
    save: model => api('/api/' + type + '/' + id + '/verify', {method: 'POST', body: {expected_version: model.expected_version, reviewer: model.reviewer, opinion: model.opinion, status: model.status, evidence_note: model.evidence_note}}),
    refresh: async model => { const fresh = (await api('/api/' + type + '/' + id)).item; return {view: resourceContent(type, fresh), apply: () => { model.expected_version = fresh.version; }}; },
    afterSave: async () => { await dialog.close(true); toast('人工核验已记录，关联项目需重新核对与复核。'); await onSaved(); }
  });
  dialog.body.append(form.node);
}
function tags(value) {
  const values = [...new Set(value.split(/[,，、\n]/).map(x => x.trim()).filter(Boolean))];
  if (values.length > 30 || values.some(value => value.length > 200)) throw new Error('标签最多 30 项，每项不超过 200 字。');
  return values;
}
export async function editResource(type, id = null, onSaved = notifyChanged) {
  const [data, filesData] = await Promise.all([id ? api('/api/' + type + '/' + id) : Promise.resolve({item: null}), type === 'templates' ? Promise.resolve({items: []}) : api('/api/files')]);
  const item = data.item;
  if (item?.builtin) return copyTemplate(item, onSaved);
  const files = filesData.items.filter(file => file.purpose !== 'export');
  const initial = {expected_version: item?.version, business_types: item?.business_types || ['supervision', 'tis'], tags_text: item?.tags.join('，') || ''};
  if (type === 'templates') Object.assign(initial, {name: item?.name || '', source: item?.source || '', sections: item?.sections || [{key: 'section_1', title: '', category: 'technical', body: ''}]});
  if (type === 'materials') Object.assign(initial, {name: item?.name || '', kind: item?.kind || 'qualification', description: item?.description || '', valid_from: item?.valid_from || '', valid_until: item?.valid_until || '', validity_note: item?.validity_note || '', scope: item?.scope || '', file_ids: item?.file_ids || []});
  if (type === 'snippets') Object.assign(initial, {title: item?.title || '', content: item?.content || '', source_file_id: item?.source_file_id || '', source_block_ids: item?.source_block_ids || []});
  const dialog = modal((id ? '编辑' : '新建') + LIBRARIES[type].singular, {wide: true});
  const form = editorForm({key: `resource:${type}:${id || 'new'}`, initial,
    build(model, editor) {
      const common = h('div', {class: 'form-grid'}, businessChecks(model), bind(model, 'tags_text', '标签', {hint: '用中文或英文逗号分隔，最多 30 项。'}));
      const body = h('div', {}, notice('保存内容后人工核验将重置，关联项目也需要重新核对与复核。历史版本会保留。', 'warn'));
      if (type === 'templates') {
        const sections = h('div');
        const renderSections = () => sections.replaceChildren(...model.sections.map((part, index) => h('section', {class: 'fact-row'}, h('div', {class: 'split-label'}, h('h3', {}, '章节 ' + (index + 1)), actions(button('上移', () => { [model.sections[index - 1], model.sections[index]] = [model.sections[index], model.sections[index - 1]]; renderSections(); editor.changed(); }, 'quiet small', {disabled: index === 0}), button('移除', async () => {
          if (!(await confirmDialog('移除此模板章节？', '正文将从当前编辑模型中移除，保存后形成新模板版本。', '移除章节', true))) return;
          model.sections.splice(index, 1); renderSections(); editor.changed();
        }, 'quiet small', {disabled: model.sections.length <= 1}))), h('div', {class: 'form-grid'}, bind(part, 'key', '章节键（唯一）', {required: true, pattern: '[a-zA-Z0-9_-]{1,100}', maxLength: 100}), bind(part, 'title', '章节标题', {required: true, maxLength: 200}), bind(part, 'category', '章节分类', {options: SECTIONS})), bind(part, 'body', '模板正文', {type: 'textarea', required: true, maxLength: 20000, rows: 8}))));
        renderSections();
        body.append(h('div', {class: 'top-space'}, bind(model, 'name', '模板名称', {required: true, maxLength: 200}), bind(model, 'source', '模板来源', {required: true, maxLength: 200})), common,
          detail('本地模板字段说明', h('p', {class: 'small prewrap'}, '项目字段：{{project.name}}、{{project.region}}、{{project.client}}、{{project.scope}}\n已确认事实：{{fact.staffing}}、{{fact.regional_rules}} 等。\n集合：{{facts}}、{{materials}}、{{requirements}}。\n商务正文必须使用 {{quote}} 插入权威报价块。未知内容保留待填，不编造事实。')), sections,
          button('＋ 添加章节', () => { if (model.sections.length >= 30) throw new Error('每个模板最多 30 章。'); model.sections.push({key: 'section_' + Date.now(), title: '', category: 'technical', body: ''}); renderSections(); editor.changed(); }, 'small'));
      }
      if (type === 'materials') {
        const filesSlot = h('div');
        const renderFiles = () => filesSlot.replaceChildren(checks(model, 'file_ids', files, {label: file => file.name, info: file => h('p', {}, '原件 v' + file.version + ' · ' + dateTime(file.created_at)), emptyText: '暂无可选文件，请先上传附件。'}));
        renderFiles();
        body.append(h('div', {class: 'form-grid top-space'}, bind(model, 'name', '资料名称', {required: true, maxLength: 200}), bind(model, 'kind', '资料类型', {options: KINDS})), common,
          bind(model, 'description', '资料说明', {type: 'textarea', maxLength: 20000}), bind(model, 'scope', '适用范围', {type: 'textarea', maxLength: 2000, hint: '明确专业、地区、项目或人员的适用边界。'}),
          h('div', {class: 'form-grid'}, bind(model, 'valid_from', '有效起始日', {type: 'date'}), bind(model, 'valid_until', '有效截止日', {type: 'date'})), bind(model, 'validity_note', '长期有效 / 业绩性质说明', {maxLength: 500, hint: '无到期日时必须说明，不自动认定长期有效。'}),
          h('section', {class: 'form-section'}, h('h3', {}, '证明附件'), uploadBox(async file => { files.unshift(file); model.file_ids.push(file.id); renderFiles(); editor.changed(); }), filesSlot));
      }
      if (type === 'snippets') {
        const sourceSlot = h('div');
        let chooseField;
        const renderSource = () => {
          const source = files.find(file => file.id === model.source_file_id);
          if (!source) { sourceSlot.replaceChildren(notice('先上传或选择历史来源，再人工勾选内容块。')); return; }
          const selected = checks(model, 'source_block_ids', source.blocks || [], {label: block => locator(block.locator), info: block => h('div', {class: 'prewrap'}, block.text), emptyText: '此文件没有可选择文字，未启用 OCR。请另选文字型来源后建立素材。'});
          selected.classList.add('source-picker');
          sourceSlot.replaceChildren(...(source.warnings || []).map(w => notice(w, 'warn')), selected, button('用所选内容块填入素材正文', async () => {
            const chosen = (source.blocks || []).filter(block => model.source_block_ids.includes(block.id));
            if (!chosen.length) throw new Error('请至少选择一个来源内容块。');
            const combined = chosen.map(block => block.text).join('\n\n');
            if (combined.length > 20000) throw new Error('所选内容超过 20000 字，请减少选择，或自行摘编正文并保留来源关联。');
            if (model.content && !(await confirmDialog('替换素材正文？', '将用所选来源块替换当前编辑正文。请先确认原编辑内容不再需要。', '确认填入'))) return;
            model.content = combined; contentField.control.value = combined; editor.changed();
          }, 'small'));
        };
        const contentField = bind(model, 'content', '素材正文（可人工摘编）', {type: 'textarea', required: true, maxLength: 20000, rows: 10, hint: '保留来源关联不代表该内容适用于当前投标项目。'});
        const renderChoice = () => {
          const fresh = bind(model, 'source_file_id', '历史文档来源', {options: {'': '请选择已上传的历史来源', ...Object.fromEntries(files.filter(f => Array.isArray(f.blocks)).map(file => [file.id, file.name]))}, required: true, onChange: () => { model.source_block_ids = []; renderSource(); }});
          if (chooseField) chooseField.replaceWith(fresh); chooseField = fresh;
        };
        renderChoice(); renderSource();
        body.append(h('div', {class: 'top-space'}, bind(model, 'title', '素材标题', {required: true, maxLength: 200})), common, h('section', {class: 'form-section'}, h('h3', {}, '先建立来源，再选择内容'), uploadBox(async file => { files.unshift(file); model.source_file_id = file.id; model.source_block_ids = []; renderChoice(); renderSource(); editor.changed(); }), h('div', {class: 'top-space'}, chooseField), sourceSlot), h('div', {class: 'top-space'}, contentField));
      }
      return body;
    },
    async save(model) {
      if (!model.business_types.length) throw new Error('请至少选择一种适用业务。');
      let payload = {business_types: model.business_types, tags: tags(model.tags_text)};
      if (id) payload.expected_version = model.expected_version;
      if (type === 'templates') payload = {...payload, name: model.name, source: model.source, sections: model.sections.map(part => ({key: part.key, title: part.title, category: part.category, body: part.body}))};
      if (type === 'materials') payload = {...payload, name: model.name, kind: model.kind, description: model.description, scope: model.scope, valid_from: model.valid_from || null, valid_until: model.valid_until || null, validity_note: model.validity_note, file_ids: model.file_ids};
      if (type === 'snippets') {
        if (!model.source_block_ids.length) throw new Error('请人工选择至少一个来源块。');
        payload = {...payload, title: model.title, content: model.content, source_file_id: model.source_file_id, source_block_ids: model.source_block_ids};
      }
      return api('/api/' + type + (id ? '/' + id : ''), {method: id ? 'PUT' : 'POST', body: payload});
    },
    async refresh(model) {
      if (!id) return {view: notice('请先查看资源列表是否已有刚创建的记录，以免重复新增。输入已保留。', 'warn')};
      const fresh = (await api('/api/' + type + '/' + id)).item;
      return {view: resourceContent(type, fresh), apply: () => { model.expected_version = fresh.version; }};
    },
    afterSave: async () => { await dialog.close(true); toast('已保存，当前内容待人工核验。'); await onSaved(); }, submitLabel: '保存' + LIBRARIES[type].singular
  });
  dialog.body.append(form.node);
}
function uploadBox(onUploaded) {
  let file;
  const result = h('div');
  const control = h('input', {type: 'file', accept: '.docx,.pdf', onchange: event => {
    file = event.target.files[0];
    control.setCustomValidity(file ? '已选择原件，请先点击“上传原件”，或清空文件选择后再保存资料。' : '');
  }});
  const upload = button('上传原件', async () => {
    result.replaceChildren(loading('正在上传并本地解析…'));
    try {
      const uploaded = await uploadShared(file);
      await onUploaded(uploaded);
      result.replaceChildren(notice('原件已保存并关联到当前编辑选择。请继续保存资料表单；上传成功不代表人工核验通过。'), fileRow(uploaded));
      control.value = ''; file = null; control.setCustomValidity('');
      control.dispatchEvent(new Event('change', {bubbles: true}));
    }
    catch (error) { result.replaceChildren(errorPanel(error)); }
  }, 'small');
  return h('div', {class: 'upload-box'}, field('选择 DOCX / PDF 原件', control), h('p', {}, '不超过 20MB。文件单独保存在本机，取消表单不会删除已上传的原件，可从文件列表再次选择。'), upload, result);
}
