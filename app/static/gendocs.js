import {api, download} from './api.js';
import {h, notice, button, card, empty, bind, checkbox, editorForm, confirmDialog, toast, downloadButton, dateTime, bytes, errorPanel, linkButton} from './ui.js';

const COLUMNS = {
  'personnel-gantt': [
    {key: 'name', label: '姓名', th: '姓名', cls: 'line-name', opts: {required: true, maxLength: 50}},
    {key: 'role', label: '岗位', th: '岗位', cls: 'line-name', opts: {required: true, maxLength: 100}},
    {key: 'entry_date', label: '进场日期', th: '进场日期', cls: 'line-number', opts: {type: 'date', required: true}},
    {key: 'exit_date', label: '退场日期（可空）', th: '退场日期', cls: 'line-number', opts: {type: 'date'}},
    {key: 'note', label: '备注', th: '备注', cls: 'line-basis', opts: {maxLength: 500}},
  ],
  'equipment-list': [
    {key: 'name', label: '设备名称', th: '设备名称', cls: 'line-name', opts: {required: true, maxLength: 100}},
    {key: 'model_spec', label: '型号规格', th: '型号规格', cls: 'line-name', opts: {maxLength: 100}},
    {key: 'quantity', label: '数量', th: '数量', cls: 'line-unit', opts: {type: 'number', min: '1', max: '9999', inputmode: 'numeric'}},
    {key: 'unit', label: '单位', th: '单位', cls: 'line-unit', opts: {maxLength: 20}},
    {key: 'purpose', label: '用途', th: '用途', cls: 'line-basis', opts: {maxLength: 200}},
    {key: 'calibration_expiry', label: '校准有效期', th: '校准有效期', cls: 'line-number', opts: {maxLength: 50}},
  ],
};

const emptyRow = key => key === 'equipment-list'
  ? {name: '', model_spec: '', quantity: '1', unit: '台', purpose: '', calibration_expiry: ''}
  : {name: '', role: '', entry_date: '', exit_date: '', note: ''};

const defaultTitle = key => key === 'equipment-list' ? '拟投入主要设备清单' : '人员进退场计划表';

// ── 通用列式引擎（1B/1C/1D）：后端下发 columns 元数据，前端据此自动渲染 ──
const metaToColumn = c => ({
  key: c.key, label: c.label, th: c.label, type: c.type,
  cls: c.type === 'text' ? 'line-basis' : 'line-unit',
  opts: c.type === 'select' ? {options: c.options, required: !!c.required}
    : c.type === 'number' ? {type: 'number', required: !!c.required, inputmode: 'decimal'}
    : c.type === 'date' ? {type: 'date', required: !!c.required}
    : {maxLength: c.max_length || 200, required: !!c.required, placeholder: c.placeholder || ''},
});
const genericEmptyRow = cols => Object.fromEntries(cols.map(c =>
  [c.key, c.type === 'bool' ? true : c.type === 'select' ? (Object.keys(c.options || {})[0] || '') : '']));
const blankRow = (tpl, key) => (tpl && tpl.columns) ? genericEmptyRow(tpl.columns) : emptyRow(tpl ? tpl.key : key);

function buildColumnPayload(model, tpl) {
  const cols = tpl.columns || [];
  const primary = cols[0] && cols[0].key;
  const rows = model.rows.filter(r => String((r && r[primary]) ?? '').trim());
  const payload = {rows: rows.map(r => {
    const o = {};
    cols.forEach(c => {
      const v = r[c.key];
      if (c.type === 'bool') { if (v === true) o[c.key] = true; else if (v === false) o[c.key] = false; }
      else { const s = String(v ?? '').trim(); if (s) o[c.key] = s; }
    });
    return o;
  })};
  const t = (model.title || '').trim();
  if (t) payload.title = t;
  return payload;
}

// 段落类附件：字段初值（bool 默认勾选）与请求体构造（bool 显式提交 true/false，文本留空交后端渲染填空位）。
const letterDefaults = tpl => Object.fromEntries(((tpl && tpl.fields) || []).map(f => [f.key, f.type === 'bool' ? true : '']));

function buildLetterPayload(model, tpl) {
  const payload = {};
  ((tpl && tpl.fields) || []).forEach(f => {
    const v = (model.letter || {})[f.key];
    if (f.type === 'bool') payload[f.key] = Boolean(v);
    else { const s = String(v ?? '').trim(); if (s) payload[f.key] = s; }
  });
  return payload;
}

function buildPayload(model) {
  const rows = model.rows.filter(r => (r.name || '').trim());
  if (model.template_key === 'personnel-gantt') {
    const payload = {
      rows: rows.map(r => ({
        name: r.name.trim(),
        role: (r.role || '').trim(),
        entry_date: r.entry_date,
        exit_date: r.exit_date || null,
        note: (r.note || '').trim(),
      })),
    };
    if ((model.title || '').trim()) payload.title = model.title.trim();
    if (model.time_scale && model.time_scale !== 'auto') payload.time_scale = model.time_scale;
    return payload;
  }
  const payload = {
    rows: rows.map(r => {
      const row = {name: r.name.trim()};
      if ((r.model_spec || '').trim()) row.model_spec = r.model_spec.trim();
      const q = parseInt(r.quantity, 10);
      if (Number.isFinite(q) && q >= 1) row.quantity = q;
      if ((r.unit || '').trim()) row.unit = r.unit.trim();
      if ((r.purpose || '').trim()) row.purpose = r.purpose.trim();
      if ((r.calibration_expiry || '').trim()) row.calibration_expiry = r.calibration_expiry.trim();
      return row;
    }),
  };
  if ((model.title || '').trim()) payload.title = model.title.trim();
  return payload;
}

function historyView(items, templates) {
  if (!items.length) return empty('尚无生成的附件', '填写表格数据后点击「一键生成并下载」，生成的 Word 文档会在此保留，可随时重复下载。');
  const nameMap = Object.fromEntries(templates.map(t => [t.key, t.title]));
  return h('div', {}, [...items].reverse().map(item => h('div', {class: 'file-row'},
    h('span', {class: 'file-icon'}, (item.filename || 'DOCX').split('.').pop().toUpperCase().slice(0, 5)),
    h('div', {class: 'file-name'}, h('strong', {}, item.title || item.filename),
      h('p', {}, `${nameMap[item.template_key] || item.template_key} · ${dateTime(item.created_at)} · ${bytes(item.size)}`)),
    downloadButton({download_url: item.download_url, name: item.filename}, '下载 .docx'))));
}

export async function gendocPage(ctx) {
  const [templatesResp, historyResp] = await Promise.all([
    api('/api/gendocs/templates?business_type=' + encodeURIComponent(ctx.project.business_type)),
    api(ctx.base + '/gendocs'),
  ]);
  const templates = templatesResp.items;
  if (!templates.length) {
    return h('div', {},
      h('div', {class: 'stage-head'}, h('div', {}, h('h2', {}, '附件文档生成'), h('p', {}, '表格与横道图 · 一键导出 Word')), linkButton('返回商务报价', '#projects/' + ctx.id + '/quote', 'small')),
      card(null, empty('暂无可用模板', '当前项目业务类型没有可用的附件生成模板。')));
  }
  const templateOptions = Object.fromEntries(templates.map(t => [t.key, t.title]));
  const defaultKey = templates[0].key;
  const defaultTpl = templates[0];
  const historyBody = h('div', {}, historyView(historyResp.items, templates));

  const form = editorForm({
    key: 'gendoc:' + ctx.id,
    initial: {template_key: defaultKey, rows: [blankRow(defaultTpl, defaultKey)], title: '', time_scale: 'auto', letter: letterDefaults(defaultTpl)},
    submitLabel: '一键生成并下载 .docx',
    build(model, editor) {
      const tpl = templates.find(t => t.key === model.template_key);
      const isSection = !!(tpl && tpl.form_type === 'sections');
      const isFieldForm = !!(tpl && (tpl.form_type === 'letter' || isSection));
      const isGantt = !!(tpl && tpl.form_type === 'gantt');
      const isBar = !!(tpl && tpl.form_type === 'bar');
      const head = h('section', {class: 'form-section top-space'}, h('h3', {}, '① 选择附件模板'),
        h('div', {class: 'form-grid'},
          bind(model, 'template_key', '附件模板', {options: templateOptions, hint: '切换模板会清空下方已填内容', onChange: value => {
            const next = templates.find(t => t.key === value);
            model.rows = [blankRow(next, value)]; model.title = ''; model.letter = letterDefaults(next); editor.redraw(); editor.changed();
          }}),
          isGantt ? bind(model, 'time_scale', '时间刻度（横道图）', {options: {auto: '自动', day: '按天', week: '按周', month: '按月'}, hint: '通常保持「自动」即可'}) : null),
        h('p', {class: 'small muted top-space'}, tpl?.description || ''));
      if (isFieldForm) {
        const fieldNodes = (tpl.fields || []).map(f => f.type === 'bool'
          ? h('div', {class: 'field'}, checkbox(model.letter, f.key, f.label))
          : bind(model.letter, f.key, f.label, {required: f.required, maxLength: f.max_length, placeholder: f.key === 'sign_date' ? '如 2026年10月1日' : ''}));
        const topNotice = isSection
          ? notice('章节大纲按内置标准框架自动生成，正文要点与评分对应为编制指引；留空占位将标为需人工补充的提示，权威报价与选用资料须由人工补齐，本工具不代为臆造。')
          : notice('附件文档是辅助产物：生成并下载 Word 不会改变项目版本，也不影响复核状态。留空的字段将自动渲染为可手写补全的填空位，生成后请人工核对并线下签章。');
        return h('div', {},
          topNotice,
          head,
          h('section', {class: 'form-section top-space'}, h('h3', {}, isSection ? '② 生成选项' : '② 填写正文信息'),
            h('div', {class: 'form-grid'}, ...fieldNodes),
            h('p', {class: 'small muted top-space'}, isSection ? '标题留空则用标准标题；可关闭「目录页」或「编制指引」得到更精简的正文。'
              : '「招标人（委托方）」留空时自动取项目的委托方；落款日期建议填「2026年10月1日」这类中文日期，留空则显示为手写填空位。')));
      }
      const isGeneric = !!(tpl && tpl.columns);
      const columns = isGeneric ? tpl.columns.map(metaToColumn) : (COLUMNS[model.template_key] || COLUMNS[defaultKey] || []);
      const cellOf = (row, col) => col.type === 'bool'
        ? h('td', {class: 'line-unit'}, checkbox(row, col.key, col.label))
        : h('td', {class: col.cls}, bind(row, col.key, col.label, {...col.opts}));
      const rows = h('tbody');
      const renderRows = () => rows.replaceChildren(...model.rows.map((row, index) => h('tr', {},
        ...columns.map(col => cellOf(row, col)),
        h('td', {}, button('移除', async () => {
          const first = columns[0] ? String(row[columns[0].key] ?? '').trim() : '';
          if (first && !(await confirmDialog('移除此行？', '该行内容将从表格中删除，尚未生成的数据不会保存。', '移除行', true))) return;
          model.rows.splice(index, 1); renderRows(); editor.changed();
        }, 'quiet small', {disabled: model.rows.length <= 1})))));
      renderRows();
      const tableNotice = isGantt
        ? notice('结束日期留空表示「持续至期末」，横道图中将显示为灰色横道；至少填写一行名称与开始日期。')
        : isBar ? notice('按人填写姓名、岗位与进退场日期；系统按自然月自动统计每月在场人数（退场日期留空表示至项目工期结束）。')
        : isGeneric ? notice('按列填写，首列不能为空；「是否提供」等勾选列用复选框控制 ☑/□，计算列由系统自动生成。')
        : notice('至少填写一行设备名称；数量留空按 1 计，单位默认「台」。');
      return h('div', {},
        notice('附件文档是辅助产物：生成并下载 Word 不会改变项目版本，也不影响复核状态。请人工核对内容与日期后再生成。'),
        head,
        h('div', {class: 'top-space'}, bind(model, 'title', '文档标题（可选）', {maxLength: 200, placeholder: isGeneric ? tpl.title : defaultTitle(model.template_key), hint: '留空则使用默认标题'})),
        h('section', {class: 'form-section top-space'}, h('h3', {}, '② 填写表格数据'),
          tableNotice,
          h('div', {class: 'table-scroll top-space'}, h('table', {class: 'quote-table'},
            h('thead', {}, h('tr', {}, [...columns.map(c => h('th', {scope: 'col'}, c.th || c.label)), h('th', {scope: 'col'}, '操作')])),
            rows)),
          h('div', {class: 'top-space'}, button('＋ 添加行', () => {
            if (model.rows.length >= 200) { toast('最多 200 行数据。', 'error'); return; }
            model.rows.push(blankRow(tpl, model.template_key)); renderRows(); editor.changed();
          }, 'small'))));
    },
    save: async model => {
      const tpl = templates.find(t => t.key === model.template_key);
      const isFieldForm = !!(tpl && (tpl.form_type === 'letter' || tpl.form_type === 'sections'));
      let payload;
      if (isFieldForm) {
        payload = buildLetterPayload(model, tpl);
        if (tpl.form_type === 'letter' && !Object.keys(payload).length) throw Object.assign(new Error('请至少填写一项正文信息（如投标人名称）。'), {code: 'EMPTY_LETTER'});
      } else if (tpl && tpl.columns) {
        payload = buildColumnPayload(model, tpl);
        if (tpl.form_type === 'gantt' && model.time_scale && model.time_scale !== 'auto') payload.time_scale = model.time_scale;
        if (!payload.rows.length) throw Object.assign(new Error('请至少填写一行有效数据（首列不能为空）。'), {code: 'EMPTY_ROWS'});
      } else {
        payload = buildPayload(model);
        if (!payload.rows.length) throw Object.assign(new Error('请至少填写一行有效数据（姓名 / 设备名称不能为空）。'), {code: 'EMPTY_ROWS'});
      }
      const label = isFieldForm ? '正文信息' : '表格数据';
      const ok = await confirmDialog('生成并下载附件文档？', `将按当前${label}生成「${tpl?.title || model.template_key}」Word 文档并下载到本机。此操作不影响项目版本与复核状态。`, '确认生成并下载');
      if (!ok) throw Object.assign(new Error('已取消生成，输入已保留。'), {code: 'CANCELLED'});
      const result = await api(ctx.base + '/gendocs', {method: 'POST', body: {template_key: model.template_key, payload}});
      await download(result.file.download_url, result.file.name);
      toast('附件已生成并下载，不影响项目版本与复核状态');
      return result;
    },
    afterSave: async () => {
      try {
        const fresh = await api(ctx.base + '/gendocs');
        historyBody.replaceChildren(historyView(fresh.items, templates));
      } catch (error) { historyBody.replaceChildren(errorPanel(error)); }
    },
  });

  return h('div', {},
    h('div', {class: 'stage-head'}, h('div', {}, h('h2', {}, '附件文档生成'), h('p', {}, '表格与横道图 · 一键导出 Word')), linkButton('返回商务报价', '#projects/' + ctx.id + '/quote', 'small')),
    card(null, form.node),
    h('div', {class: 'top-space'}, card('历史生成记录', historyBody)));
}
