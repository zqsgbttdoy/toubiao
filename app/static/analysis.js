import {api, query, checkFile} from './api.js';
import {h, actions, badge, notice, button, empty, loading, errorPanel, field, bind, checkbox, checks, editorForm, modal, confirmDialog, toast, CATEGORIES, RESPONSE, locator, dateTime, definition, versionRefresh, serverText, downloadButton, materialWarnings} from './ui.js';

export function documentStatus(doc) {
  return doc.parse_status === 'parsed' ? badge('文字已提取', 'good') : doc.parse_status === 'low_quality' ? badge('文字质量低 · 需人工核对', 'warn') : badge('需人工摘录', 'warn');
}
export async function showSource(ctx, documentId, blockId) {
  const doc = (await api(ctx.base + '/documents/' + documentId)).item;
  const block = doc.blocks.find(b => b.id === blockId);
  if (!block) throw new Error('此来源中找不到对应内容块，请核对来源版本。');
  const dialog = modal('完整原文与定位', {wide: true});
  dialog.body.append(definition([['来源', doc.title], ['来源版本', 'v' + doc.source_version], ['定位', locator(block.locator)], ['说明', doc.source_note]]), h('div', {class: 'source-block top-space'}, h('div', {class: 'prewrap'}, block.text)), notice('展示存储的完整内容块。Word 仅按段落或表格定位，不推断页码；仍需对照原件核对。'));
}
export async function importDocument(ctx, manual = false, replacement = '') {
  await ctx.refresh();
  const dialog = modal(manual ? '人工摘录招标要求' : '上传招标文件 / 补遗', {wide: manual});
  let selectedFile = null;
  const form = editorForm({
    key: `document:${ctx.id}:${manual ? 'excerpt' : 'upload'}`, initial: {expected_version: ctx.project.version, title: '', text: '', source_note: '', replaces_document_id: replacement}, submitLabel: manual ? '保存摘录并提取候选' : '上传并提取候选条款',
    build(model) {
      const replacementOptions = {'': '新独立来源（非替换补遗）', ...Object.fromEntries(ctx.data.documents.map(doc => [doc.id, `${doc.title} · 来源 v${doc.source_version}`]))};
      const fileInput = h('input', {type: 'file', accept: '.docx,.pdf', required: !manual, onchange: event => { selectedFile = event.target.files[0] || null; }});
      return h('div', {}, notice('单个文件不超过 20MB，仅支持 DOCX 与文字 PDF（最多 300 页）。扫描件无 OCR；DOC、宏、加密或损坏文件请改为人工摘录。补遗保留旧来源，原有条款不会自动删除。', 'warn'),
        h('div', {class: 'top-space'}, bind(model, 'replaces_document_id', '来源关系', {options: replacementOptions, hint: '选择被补充或替代的来源，会生成同一来源族的新版本。请人工处理旧条款。'})),
        manual ? h('div', {}, bind(model, 'title', '摘录标题', {required: true, maxLength: 200}), bind(model, 'source_note', '摘录依据 / 原件定位', {required: true, maxLength: 200, placeholder: '例如原件章节、条目或人工核对说明，不虚构页码'}), bind(model, 'text', '完整摘录内容', {type: 'textarea', required: true, maxLength: 20000, rows: 12}), notice('人工摘录不表示原件完整。如果原文提取不完整，请在项目事实中记录“原文完整性人工核对”的依据并确认。')) : h('div', {class: 'upload-box'}, field('选择本地文件', fileInput), h('p', {}, '上传期间请保持页面开启。解析失败将保留本表单；可更换文件后重试，或关闭后选择人工摘录。')));
    },
    async save(model) {
      if (manual) return ctx.write('/documents/excerpts', 'POST', {expected_version: model.expected_version, title: model.title, text: model.text, source_note: model.source_note, replaces_document_id: model.replaces_document_id || null});
      checkFile(selectedFile);
      const body = new FormData(); body.append('file', selectedFile); body.append('expected_version', String(model.expected_version));
      if (model.replaces_document_id) body.append('replaces_document_id', model.replaces_document_id);
      return ctx.write('/documents', 'POST', body);
    },
    async refresh(model) {
      const data = await ctx.refresh();
      return versionRefresh(model, data, null, serverText('当前来源记录（先检查是否已上传成功）', data.documents.map(d => `${d.title} · 来源 v${d.source_version} · ${dateTime(d.created_at)}`).join('\n')));
    },
    async afterSave(result) { toast(`来源已保存，新增 ${result.requirements.length} 条待人工确认候选。`); await dialog.close(true); await ctx.rerender(); }
  });
  dialog.body.append(form.node);
}
function requirementSummary(req) {
  return h('div', {}, definition([['分类', CATEGORIES[req.category]], ['确认', req.confirmed ? '已人工确认' : '待人工确认'], ['响应', RESPONSE[req.response_status]], ['章节', req.section_id || '未映射'], ['来源', req.source_note], ['版本', 'v' + req.version]]), serverText('服务器条款', req.text), serverText('服务器响应说明', req.response_note));
}
export async function editRequirement(ctx, requirementId = null, source = null) {
  const [data, materialData] = await Promise.all([ctx.refresh(), api('/api/materials' + query({business_type: ctx.project.business_type}))]);
  const original = requirementId ? data.requirements.find(r => r.id === requirementId) : null;
  if (requirementId && !original) throw new Error('条款已不存在，请刷新条款列表。');
  const initial = {
    expected_version: data.item.version, entity_version: original?.version,
    text: original?.text || source?.block?.text.slice(0, 20000) || '', category: original?.category || 'delivery', mandatory: original?.mandatory || false, confirmed: original?.confirmed || false,
    response_status: original?.response_status || 'pending', response_note: original?.response_note || '', section_id: original?.section_id || '', proof_material_ids: original?.proof_material_ids || [],
    document_id: original?.document_id || source?.document?.id || '', block_id: original?.block_id || source?.block?.id || '', source_note: original?.source_note || source?.document?.title || '人工录入'
  };
  const dialog = modal(original ? '编辑、确认与响应条款' : '新增人工条款', {wide: true});
  const form = editorForm({
    key: `requirement:${ctx.id}:${requirementId || source?.block?.id || 'new'}`, initial,
    build(model) {
      const sourceFields = h('div');
      const renderBlocks = () => {
        const doc = ctx.data.documents.find(d => d.id === model.document_id);
        if (!doc) { model.block_id = ''; sourceFields.replaceChildren(); return; }
        sourceFields.replaceChildren(bind(model, 'block_id', '原文内容块', {options: {'': '请选择原文定位块', ...Object.fromEntries(doc.blocks.map(b => [b.id, locator(b.locator) + ' · ' + b.text.slice(0, 65)]))}, required: true}), button('查看当前完整原文', () => {
          if (!model.block_id) throw new Error('请先选择内容块。');
          return showSource(ctx, model.document_id, model.block_id);
        }, 'small'));
      };
      renderBlocks();
      return h('div', {}, notice('候选提取不是结论。请逐条核对原文、分类与适用性，再明确确认；强制条款须填写响应说明、映射当前章节及相应证明。'),
        original?.source_text_truncated || source?.block?.text.length > 20000 ? h('div', {class: 'top-space'}, notice('来源文字超过条款摘录上限，当前只预填前 20000 字。请点击完整原文阅读整块内容，并人工拆分或摘编，不要仅据截断文字确认。', 'warn')) : null,
        bind(model, 'text', '条款内容', {type: 'textarea', required: true, maxLength: 20000, rows: 5, className: 'top-space'}),
        h('div', {class: 'form-grid'}, bind(model, 'category', '条款分类', {options: CATEGORIES}), bind(model, 'response_status', '响应状态', {options: RESPONSE})),
        actions(checkbox(model, 'mandatory', '属于强制 / 否决要求'), checkbox(model, 'confirmed', '我已对照来源人工确认')),
        h('div', {class: 'top-space'}, bind(model, 'response_note', '响应说明与差异', {type: 'textarea', maxLength: 10000, placeholder: '已如何响应、适用依据或尚待补齐的缺口'}), bind(model, 'section_id', '映射当前草稿章节', {options: {'': '暂未映射', ...Object.fromEntries((ctx.data.draft?.sections || []).map(s => [s.id, s.title]))}, hint: '尚未生成草稿时可先保存条款，生成后再映射。'})),
        h('section', {class: 'form-section'}, h('h3', {}, '证明资料 / 附件映射'), notice('关联企业资料即关联该资料的原始附件；选用状态由后台同步。未核验或过期材料仍会形成风险提示。'), checks(model, 'proof_material_ids', materialData.items, {info: item => materialWarnings(item, ctx.project.deadline), emptyText: '暂无适用企业资料，请先到企业资料库上传证明附件并维护资料。'})),
        h('section', {class: 'form-section'}, h('h3', {}, '来源与原文定位'), bind(model, 'document_id', '招标来源', {options: {'': '人工录入（无文档定位）', ...Object.fromEntries(ctx.data.documents.map(d => [d.id, d.title + ' · 来源 v' + d.source_version]))}, onChange: () => { model.block_id = ''; renderBlocks(); }}), sourceFields, bind(model, 'source_note', '来源 / 人工依据说明', {maxLength: 500, className: 'top-space'})));
    },
    async save(model) {
      const body = {expected_version: model.expected_version, text: model.text, category: model.category, mandatory: model.mandatory, confirmed: model.confirmed, response_status: model.response_status, response_note: model.response_note, section_id: model.section_id || null, proof_material_ids: model.proof_material_ids, document_id: model.document_id || null, block_id: model.block_id || null, source_note: model.source_note};
      if (original) body.entity_version = model.entity_version;
      return ctx.write('/requirements' + (original ? '/' + original.id : ''), original ? 'PUT' : 'POST', body);
    },
    async refresh(model) {
      const fresh = await ctx.refresh();
      const item = fresh.requirements.find(r => r.id === requirementId);
      if (original && !item) throw new Error('此条款已被删除，不能覆盖。请保留文本，返回列表新增条款。');
      return versionRefresh(model, fresh, item, item ? requirementSummary(item) : notice('项目现为 v' + fresh.item.version + '。请检查条款列表避免重复新增。', 'warn'));
    },
    async afterSave() { toast('条款与映射已保存，原复核已失效。'); await dialog.close(true); await ctx.rerender(); }, readonly: data.item.archived
  });
  dialog.body.append(form.node);
}
export function analysisPage(ctx) {
  const docs = ctx.data.documents;
  const state = {document_id: docs.at(-1)?.id || '', q: '', category: '', confirmed: '', response: ''};
  const left = h('section', {class: 'card'});
  const requirementsBox = h('div');
  const counts = h('span', {class: 'list-count'});
  let sourceRequest = 0;
  function sourceView(doc, activeBlock = '') {
    const blocks = h('div', {class: 'source-scroll', tabindex: '0', 'aria-label': '原文内容块'});
    const fileSlot = h('div');
    left.replaceChildren(h('header', {class: 'card-head'}, h('h2', {}, '招标来源'), h('span', {class: 'muted'}, `${docs.length} 份来源`)),
      h('div', {class: 'document-choice'}, bind(state, 'document_id', '选择来源与版本', {options: Object.fromEntries(docs.map(d => [d.id, `${d.title} · 来源 v${d.source_version}`])), onChange: () => loadSource(state.document_id)})),
      h('div', {class: 'source-info'}, actions(documentStatus(doc), badge('来源 v' + doc.source_version), doc.replaces_document_id ? badge('补遗版本') : null), h('p', {class: 'top-space'}, doc.source_note), fileSlot),
      doc.warnings.length ? h('div', {class: 'card-body'}, doc.warnings.map(w => notice(w, 'warn'))) : null,
      blocks,
      h('div', {class: 'card-body'}, actions(button('上传该来源的补遗', () => importDocument(ctx, false, doc.id), 'small', {disabled: ctx.project.archived}), button('人工补充摘录', () => importDocument(ctx, true, doc.id), 'small', {disabled: ctx.project.archived}))));
    if (!doc.blocks.length) blocks.append(empty('没有可阅读文字', '请对照原件人工摘录；不联网 OCR，也不推断扫描内容。', button('人工摘录', () => importDocument(ctx, true, doc.id), 'primary', {disabled: ctx.project.archived})));
    else blocks.append(...doc.blocks.map(b => h('article', {class: 'source-block' + (b.id === activeBlock ? ' active' : ''), id: 'block-' + b.id, tabindex: '-1'}, h('div', {class: 'source-locator'}, h('span', {}, locator(b.locator)), button('新增为条款', () => editRequirement(ctx, null, {document: doc, block: b}), 'quiet small', {disabled: ctx.project.archived})), h('div', {class: 'prewrap'}, b.text))));
    if (doc.file_id) {
      const loadFile = async () => { try { const file = (await api('/api/files/' + doc.file_id)).item; fileSlot.replaceChildren(actions(downloadButton(file), button('原件信息', () => { const dialog = modal('原件与完整性信息'); dialog.body.append(definition([['文件名', file.name], ['SHA-256', file.sha256], ['保存时间', dateTime(file.created_at)], ['来源族 ID', doc.source_family_id]])); }, 'quiet small'))); } catch (error) { fileSlot.replaceChildren(errorPanel(error, loadFile)); } };
      loadFile();
    }
    if (activeBlock) requestAnimationFrame(() => { const element = document.getElementById('block-' + activeBlock); element?.scrollIntoView({block: 'center', behavior: 'smooth'}); element?.focus({preventScroll: true}); });
  }
  async function loadSource(id, blockId = '') {
    const ticket = ++sourceRequest;
    left.replaceChildren(loading('正在读取完整原文…'));
    try { const doc = (await api(ctx.base + '/documents/' + id)).item; if (ticket !== sourceRequest) return; state.document_id = id; sourceView(doc, blockId); }
    catch (error) { if (ticket === sourceRequest) left.replaceChildren(errorPanel(error, () => loadSource(id, blockId))); }
  }
  function renderRequirements() {
    const list = ctx.data.requirements.filter(r => (!state.q || (r.text + r.response_note).includes(state.q)) && (!state.category || r.category === state.category) && (!state.confirmed || String(r.confirmed) === state.confirmed) && (!state.response || r.response_status === state.response));
    counts.textContent = `${list.length} / ${ctx.data.requirements.length} 条`;
    if (!list.length) { requirementsBox.replaceChildren(empty('暂无匹配条款', '上传文件提取候选，或人工新增。未发现条款不代表已满足投标要求。', button('＋ 人工新增', () => editRequirement(ctx), 'primary', {disabled: ctx.project.archived}))); return; }
    requirementsBox.replaceChildren(...list.map(r => h('article', {class: 'requirement'}, actions(badge(CATEGORIES[r.category]), r.mandatory ? badge('强制', 'bad') : null, badge(r.confirmed ? '已人工确认' : '待确认', r.confirmed ? 'good' : 'warn'), badge(RESPONSE[r.response_status], r.response_status === 'responded' ? 'good' : '')),
      h('p', {}, r.text), h('div', {class: 'requirement-meta'}, `${locator(r.locator)} · 来源 v${r.source_version} · 条款 v${r.version}`, r.source_text_truncated ? ' · 摘录已截断，请读完整原文' : ''),
      r.response_note ? h('div', {class: 'small muted prewrap bottom-space'}, '响应：' + r.response_note) : null,
      h('div', {class: 'requirement-meta'}, '章节：' + (ctx.data.draft?.sections.find(s => s.id === r.section_id)?.title || '未映射当前章节') + ` · ${r.proof_material_ids.length} 份证明资料`),
      actions(r.document_id ? button('定位完整原文', () => loadSource(r.document_id, r.block_id), 'quiet small') : h('span', {class: 'small muted'}, r.source_note), actions(button(ctx.project.archived ? '查看条款' : '编辑 / 确认', () => editRequirement(ctx, r.id), 'small'), button('删除', async () => {
        if (!(await confirmDialog('删除此条款？', '删除不会移除原始来源。请先确认不是遗漏或误删投标要求；删除会使复核失效。', '删除条款', true))) return;
        await ctx.write('/requirements/' + r.id, 'DELETE', {expected_version: ctx.project.version, entity_version: r.version}); await ctx.rerender();
      }, 'quiet small', {disabled: ctx.project.archived}))))));
  }
  if (docs.length) sourceView(docs.at(-1));
  else left.append(empty('首先，建立招标来源', '原件留存、来源版本和原文定位，将成为后续编制的依据。', button('上传 DOCX / PDF', () => importDocument(ctx), 'primary', {disabled: ctx.project.archived}), button('人工摘录', () => importDocument(ctx, true), '', {disabled: ctx.project.archived})));
  renderRequirements();
  return h('div', {}, h('div', {class: 'stage-head'}, h('div', {}, h('h2', {}, '招标文件与条款分析'), h('p', {}, '本地关键词提取候选 · 人工确认后使用 · 点击条款定位完整原文')), actions(button('人工摘录', () => importDocument(ctx, true), '', {disabled: ctx.project.archived}), button('上传文件 / 补遗', () => importDocument(ctx), 'primary', {disabled: ctx.project.archived}))),
    h('div', {class: 'analysis-grid'}, left, h('section', {class: 'card'}, h('header', {class: 'card-head'}, h('h2', {}, '条款确认与响应'), counts, button('＋ 新增', () => editRequirement(ctx), 'small', {disabled: ctx.project.archived})),
      h('div', {class: 'toolbar'}, bind(state, 'q', '搜索条款', {type: 'search', className: 'search', placeholder: '条款内容或响应说明', onChange: renderRequirements}), bind(state, 'category', '分类', {options: {'': '全部分类', ...CATEGORIES}, onChange: renderRequirements}), bind(state, 'confirmed', '确认状态', {options: {'': '全部', false: '待确认', true: '已确认'}, onChange: renderRequirements}), bind(state, 'response', '响应状态', {options: {'': '全部响应', ...RESPONSE}, onChange: renderRequirements})), requirementsBox)));
}
