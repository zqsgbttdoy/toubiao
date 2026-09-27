import {api} from './api.js';
import {h, actions, badge, notice, button, linkButton, card, empty, bind, checkbox, editorForm, modal, confirmDialog, toast, SECTIONS, dateTime, definition, detail, versionRefresh, serverText, downloadButton, loading, errorPanel} from './ui.js';
import {quoteText, snapshotView} from './drafting.js';
import {editRequirement} from './analysis.js';
import {viewResource} from './library.js';

export function quoteSummary(quote) {
  if (!quote) return notice('尚未保存报价；当前没有权威合计。', 'warn');
  return h('div', {}, actions(badge('已保存报价 v' + quote.version), badge(quote.tax_confirmed ? '税率已人工确认' : '税率待确认', quote.tax_confirmed ? 'good' : 'warn')), h('div', {class: 'quote-totals top-space'},
    h('div', {}, h('span', {}, '不含税合计 / 元'), h('strong', {}, quote.subtotal)), h('div', {}, h('span', {}, '税额 / 元'), h('strong', {}, quote.tax)), h('div', {class: 'grand'}, h('span', {}, '含税总价 / 元'), h('strong', {}, quote.total))), h('p', {class: 'small muted top-space'}, quote.rounding));
}
export async function quotePage(ctx) {
  const response = await api(ctx.base + '/quote');
  const quote = response.item;
  const initial = {expected_version: response.project_version, entity_version: quote?.version || 0, fee_type: quote?.fee_type || (ctx.project.business_type === 'tis' ? 'tis_service' : 'supervision_service'),
    lines: quote?.lines.map(line => ({name: line.name, quantity: line.quantity, unit_price: line.unit_price, unit: line.unit, basis: line.basis, saved_amount: line.amount})) || [{name: '', quantity: '', unit_price: '', unit: '人月', basis: '', saved_amount: ''}], tax_rate: quote?.tax_rate || '', tax_confirmed: quote?.tax_confirmed || false, tax_note: quote?.tax_note || ''};
  const form = editorForm({key: 'quote:' + ctx.id, initial, submitLabel: '保存并由后端计算', readonly: ctx.project.archived,
    build(model, editor) {
      const rows = h('tbody');
      const renderRows = () => rows.replaceChildren(...model.lines.map((line, index) => {
        const amount = h('span', {class: 'small number'}, line.saved_amount || '保存后计算');
        const changed = () => { line.saved_amount = ''; amount.textContent = '保存后重算'; };
        return h('tr', {}, h('td', {class: 'line-name'}, bind(line, 'name', `第 ${index + 1} 项名称`, {required: true, maxLength: 200, onChange: changed})),
          h('td', {class: 'line-number'}, bind(line, 'quantity', '数量', {required: true, inputmode: 'decimal', pattern: '[0-9]{1,16}(\\.[0-9]{1,3})?', maxLength: 30, placeholder: '最多 3 位小数', onChange: changed})),
          h('td', {class: 'line-unit'}, bind(line, 'unit', '单位', {options: {'人月': '人月', '次': '次', '项': '项'}, onChange: changed})),
          h('td', {class: 'line-number'}, bind(line, 'unit_price', '单价 / 元', {required: true, inputmode: 'decimal', pattern: '[0-9]{1,16}(\\.[0-9]{1,2})?', maxLength: 30, placeholder: '最多 2 位小数', onChange: changed})),
          h('td', {class: 'line-basis'}, bind(line, 'basis', '数量与单价依据', {required: true, maxLength: 200, onChange: changed})), h('td', {}, amount),
          h('td', {}, button('移除', async () => {
            if ((line.name || line.basis) && !(await confirmDialog('移除此报价行？', '保存后会形成新的报价版本，并使草稿报价快照过期。', '移除行', true))) return;
            model.lines.splice(index, 1); renderRows(); editor.changed();
          }, 'quiet small', {disabled: model.lines.length <= 1})));
      }));
      renderRows();
      const taxCheck = checkbox(model, 'tax_confirmed', '我已核对并确认本项目适用税率');
      return h('div', {}, notice('数量与金额使用十进制字符串，由后端逐行四舍五入至分后计算。此处不计算权威总价；修改后下方仍显示上次保存值，直到保存成功。'),
        h('div', {class: 'form-grid top-space'}, bind(model, 'fee_type', '费用类型', {options: ctx.project.business_type === 'tis' ? {tis_service: 'TIS 技术服务费'} : {supervision_service: '监理服务费'}, hint: '不测算保险保费，监理费、TIS 服务费与保费不得混写。'})),
        h('div', {class: 'table-scroll'}, h('table', {class: 'quote-table'}, h('thead', {}, h('tr', {}, ['服务项目', '工作量', '计费单位', '单价', '计费依据', '已保存金额 / 元', '操作'].map(label => h('th', {scope: 'col'}, label)))), rows)),
        h('div', {class: 'top-space'}, button('＋ 添加报价行', () => { if (model.lines.length >= 200) throw new Error('最多 200 条报价行。'); model.lines.push({name: '', quantity: '', unit_price: '', unit: '项', basis: '', saved_amount: ''}); renderRows(); editor.changed(); }, 'small')),
        h('section', {class: 'form-section top-space'}, h('h3', {}, '税率与确认依据'), h('div', {class: 'form-grid'}, bind(model, 'tax_rate', '税率（0 至 1 的小数）', {required: true, inputmode: 'decimal', pattern: '[0-9]{1,16}(\\.[0-9]{1,6})?', maxLength: 20, placeholder: '例如 0.06，而不是 6', hint: '不预设统一行业税率，需由企业确认。', onChange: () => { model.tax_confirmed = false; taxCheck.querySelector('input').checked = false; }}), bind(model, 'tax_note', '税率确认依据', {required: true, maxLength: 200})), taxCheck),
        h('section', {class: 'form-section top-space'}, h('h3', {}, '后端权威合计 · 上次保存结果'), quoteSummary(quote)));
    },
    save: model => ctx.write('/quote', 'PUT', {expected_version: model.expected_version, entity_version: model.entity_version, fee_type: model.fee_type, lines: model.lines.map(line => ({name: line.name, quantity: line.quantity, unit_price: line.unit_price, unit: line.unit, basis: line.basis})), tax_rate: model.tax_rate, tax_confirmed: model.tax_confirmed, tax_note: model.tax_note}),
    refresh: async model => { const fresh = await ctx.refresh(); return versionRefresh(model, fresh, fresh.quote, h('div', {}, quoteSummary(fresh.quote), serverText('服务器完整报价', quoteText(fresh.quote)))); },
    afterSave: async () => { toast('报价已保存。请重新生成草稿，保证正文与报价使用同一快照。'); await ctx.rerender(); }
  });
  return h('div', {}, h('div', {class: 'stage-head'}, h('div', {}, h('h2', {}, '商务报价'), h('p', {}, '透明列项，明确依据 · 金额单位：人民币元')), linkButton('返回标书编制', '#projects/' + ctx.id + '/drafting', 'small')),
    card(null, form.node), h('div', {class: 'top-space'}, notice('每次保存报价都会产生新版本。已生成的草稿须重新生成，不能仅通过人工核对同步输入来更新报价。', 'warn')));
}
const LEVELS = {blocking: '阻断风险', scoring: '评分缺口', information: '资料待核验 / 信息提示'};
export function riskView(report, onLocate) {
  return h('div', {}, h('div', {class: 'risk-overview'}, Object.entries(LEVELS).map(([key, label]) => h('div', {class: 'risk-count ' + key}, h('span', {}, label), h('strong', {}, report[key + '_count'])))),
    h('p', {class: 'small muted top-space'}, `项目 v${report.project_version} · 检查时间 ${dateTime(report.checked_at)}`),
    ...Object.entries(LEVELS).map(([key, label]) => {
      const issues = report.issues.filter(issue => issue.severity === key);
      const panel = detail(`${label} · ${issues.length}`, issues.length ? issues.map(issue => h('div', {class: 'risk-item'}, h('div', {}, issue.message, h('small', {}, issue.code)), onLocate ? button('查看 / 处理', () => onLocate(issue), 'quiet small') : null)) : notice('本次规则未发现此类问题，仍须人工判断。'));
      panel.open = key === 'blocking' && issues.length > 0;
      return panel;
    }), notice(report.disclaimer, 'warn'));
}
export function frozenView(snapshot) {
  return h('div', {class: 'stack'}, definition([['项目', snapshot.project.name], ['冻结项目版本', 'v' + snapshot.project.version], ['冻结时间', dateTime(snapshot.frozen_at)]]),
    snapshot.draft ? detail('冻结的草稿与正文', snapshotView(snapshot.draft), snapshot.draft.sections.map(section => detail(section.title, h('div', {class: 'prewrap small'}, section.body)))) : notice('此送审快照尚无草稿。', 'warn'),
    detail('冻结的人工意见', snapshot.review_records.map(record => h('div', {class: 'version-entry'}, h('h3', {}, SECTIONS[record.category] + ' · ' + record.reviewer), h('p', {}, `${record.decision === 'approved' ? '通过' : '不通过'} · 项目 v${record.project_version}`), h('p', {class: 'prewrap'}, record.opinion)))),
    detail('冻结时风险', riskView(snapshot.risk_report)), notice(snapshot.disclaimer));
}
async function editDecision(ctx, category) {
  const [data, review] = await Promise.all([ctx.refresh(), api(ctx.base + '/review')]);
  const record = review.records.find(item => item.category === category);
  const dialog = modal(SECTIONS[category] + '人工复核意见');
  const form = editorForm({key: `decision:${ctx.id}:${category}`, initial: {expected_version: data.item.version, entity_version: record?.version || 0, reviewer: record?.reviewer || '', opinion: record?.opinion || '', decision: record?.decision || 'approved'}, submitLabel: '保存本类人工意见',
    build: model => h('div', {}, notice('审核人是本机人工记录，无身份认证。须针对当前项目内容填写。修改已复核项目的意见会使原冻结版本失效，其他类别也需针对新版本重新记录。', 'warn'),
      h('div', {class: 'form-grid top-space'}, bind(model, 'reviewer', '复核人', {required: true, maxLength: 200}), bind(model, 'decision', '复核意见结论', {options: {approved: '本类复核通过', rejected: '本类复核不通过'}})), bind(model, 'opinion', '人工复核意见', {type: 'textarea', required: true, maxLength: 20000, rows: 7})),
    save: model => ctx.write('/review/decisions', 'PUT', {expected_version: model.expected_version, entity_version: model.entity_version, category, reviewer: model.reviewer, opinion: model.opinion, decision: model.decision}),
    refresh: async model => { const fresh = await ctx.refresh(); const latest = (await api(ctx.base + '/review')).records.find(item => item.category === category); return versionRefresh(model, fresh, latest, latest ? definition([['服务器复核人', latest.reviewer], ['服务器结论', latest.decision === 'approved' ? '通过' : '不通过'], ['服务器意见', latest.opinion], ['适用项目版本', 'v' + latest.project_version]]) : notice('此类尚无人工意见。')); },
    afterSave: async () => { await dialog.close(true); toast(SECTIONS[category] + '复核意见已保存。'); await ctx.rerender(); }
  });
  dialog.body.append(form.node);
}
async function finalize(ctx) {
  await ctx.refresh();
  const dialog = modal('人工确认并冻结内部复核版本');
  const form = editorForm({key: 'finalize:' + ctx.id, initial: {expected_version: ctx.project.version, reviewer: '', confirmation: false}, submitLabel: '确认并冻结当前版本',
    build: model => h('div', {}, notice('冻结将保存当前项目、草稿、报价、附件目录、风险及三类人工意见的不可变快照。内容修改后需重新复核；不会自动签署或提交投标。', 'warn'), bind(model, 'reviewer', '最终确认人', {required: true, maxLength: 200, className: 'top-space'}), checkbox(model, 'confirmation', '我确认已完成人工复核，并理解软件不保证合规、中标或可直接提交', {required: true})),
    save: model => ctx.write('/review/finalize', 'POST', {expected_version: model.expected_version, reviewer: model.reviewer, confirmation: model.confirmation}),
    refresh: async model => { const data = await ctx.refresh(); return versionRefresh(model, data, null, riskView(data.risk_report)); },
    afterSave: async () => { await dialog.close(true); toast('已生成内部复核冻结快照。'); await ctx.rerender(); }
  });
  dialog.body.append(form.node);
}
// 列表接口只返回摘要，完整冻结快照按需单独读取，避免每次写操作后重传数MB内容。
function frozenDialog(title, path) {
  const dialog = modal(title, {wide: true});
  const load = () => {
    dialog.body.replaceChildren(loading('正在读取不可变冻结快照…'));
    return api(path)
      .then(result => dialog.body.replaceChildren(frozenView(result.item.snapshot)))
      .catch(error => dialog.body.replaceChildren(errorPanel(error, load)));
  };
  load();
  return dialog;
}
export function exportEntry(item) {
  const names = {technical: '技术文件 DOCX', commercial: '商务文件 DOCX', qualification: '资质目录 DOCX', package: '完整成果 ZIP'};
  const base = '/api/projects/' + encodeURIComponent(item.project_id);
  return h('article', {class: 'export-entry'}, h('div', {class: 'split-label'}, actions(badge(item.mode === 'reviewed' ? '已内部复核版' : '送审稿', item.mode === 'reviewed' ? 'good' : 'warn'), badge('项目 v' + item.project_version)), h('span', {class: 'small muted'}, dateTime(item.created_at))),
    actions(...item.files.map(file => downloadButton(file, names[file.kind] || file.name))),
    item.manifest.missing_attachments?.length ? h('div', {class: 'top-space'}, notice(`成果包中有 ${item.manifest.missing_attachments.length} 份附件缺失，详见缺项清单。`, 'warn')) : null,
    actions(button('查看此导出冻结内容', () => frozenDialog('导出时不可变快照', `${base}/exports/${item.id}`), 'quiet small'), button('文件校验信息', () => {
      const dialog = modal('导出文件与哈希'); dialog.body.append(...item.files.map(file => detail(file.name, definition([['文件类型', names[file.kind] || file.kind], ['SHA-256', file.sha256], ['原始字节数', file.size]]))));
    }, 'quiet small')));
}
export async function reviewPage(ctx) {
  const [review, exports] = await Promise.all([api(ctx.base + '/review'), api(ctx.base + '/exports')]);
  const report = review.risk_report;
  const approved = ['technical', 'commercial', 'qualification'].every(category => review.records.some(record => record.category === category && record.decision === 'approved' && !record.stale && record.project_version === review.project_version));
  const canFinalize = report.can_finalize && approved && !ctx.project.archived;
  async function locate(issue) {
    if (ctx.data.requirements.some(req => req.id === issue.entity_id)) return editRequirement(ctx, issue.entity_id);
    if (ctx.data.draft?.sections.some(section => section.id === issue.entity_id)) { location.hash = '#projects/' + ctx.id + '/drafting/' + issue.entity_id; return; }
    if (ctx.data.documents.some(doc => doc.id === issue.entity_id)) { location.hash = '#projects/' + ctx.id + '/analysis'; return; }
    for (const kind of ['material', 'template', 'snippet']) if (ctx.project['selected_' + kind + '_ids'].includes(issue.entity_id)) return viewResource(kind + 's', issue.entity_id, {manage: false});
    const target = /QUOTE|FEE|TAX/.test(issue.code) ? 'quote' : /DRAFT|SECTION|PLACEHOLDER|SOURCE_VERSION/.test(issue.code) ? 'drafting' : 'analysis';
    const dialog = modal('处理建议', {small: true});
    dialog.body.append(notice(issue.message, 'warn'), h('p', {class: 'small muted top-space'}, '资料类问题请到对应资源库维护；项目字段与事实请使用页面顶部“项目与事实”。修改后需要重新检查并记录三类人工意见。'), actions(button('进入相关阶段', async () => { await dialog.close(true); location.hash = '#projects/' + ctx.id + '/' + target; })));
  }
  async function createExport(mode) {
    if (!(await confirmDialog(mode === 'reviewed' ? '创建已内部复核版成果？' : '创建送审稿？', mode === 'reviewed' ? '使用当前有效冻结快照生成技术、商务、资质目录和成果 ZIP。请继续用目标 Word/WPS 人工检查实际打印排版。' : '允许存在缺项，成果将明确标记为送审稿并附风险清单，不是可直接提交的版本。', '确认生成成果'))) return;
    const result = await ctx.write('/exports', 'POST', {expected_version: ctx.project.version, mode});
    const dialog = modal('成果已生成', {wide: true});
    dialog.body.append(notice('请点击下方按钮下载真实文件。ZIP 保留原始证明附件，不改变签章。'), exportEntry(result.item));
    await ctx.rerender();
  }
  return h('div', {}, h('div', {class: 'stage-head'}, h('div', {}, h('h2', {}, '复核与成果导出'), h('p', {}, '规则查缺，人工负责 · 没有阻断项不等于三类复核已通过')), button('重新运行风险检查', async () => { await api(ctx.base + '/review/check', {method: 'POST'}); await ctx.refresh(); await ctx.rerender(); }, 'primary')),
    card('风险与缺项清单', riskView(report, locate)),
    card('三类人工复核意见', h('div', {}, h('div', {class: 'grid-three'}, ['technical', 'commercial', 'qualification'].map(category => {
      const record = review.records.find(item => item.category === category);
      const stale = record && (record.stale || record.project_version !== review.project_version);
      return h('article', {class: 'review-card'}, h('h3', {}, SECTIONS[category] + '复核'), badge(!record ? '未记录' : stale ? '已失效 · 需重新复核' : record.decision === 'approved' ? '本类通过' : '本类不通过', !record || stale ? 'warn' : record.decision === 'approved' ? 'good' : 'bad'), h('p', {}, record?.opinion || '请对照当前内容记录本类人工意见。'), record ? h('div', {class: 'small muted'}, `${record.reviewer} · 项目 v${record.project_version}\n${dateTime(record.recorded_at)}`) : null, button(record ? '编辑 / 重新记录' : '记录人工意见', () => editDecision(ctx, category), 'small', {disabled: ctx.project.archived}));
    })), h('div', {class: 'top-space'}, notice('单机版本无身份认证，审核人仅是人工记录。任何内容、报价或引用资源变化都会使复核失效。')), h('div', {class: 'top-space'}, actions(button(review.status === 'reviewed' ? '重新确认并冻结' : '人工确认并冻结', () => finalize(ctx), 'primary', {disabled: !canFinalize}), h('span', {class: 'small muted'}, canFinalize ? '无规则阻断且三类当前版本意见已通过' : '需要无阻断风险，并具备三类当前版本通过意见'))))),
    card('创建成果文件', h('div', {}, notice('技术、商务、资质目录 DOCX 与 ZIP 成果包均由本机后端生成。送审稿允许缺项；已复核版必须使用有效冻结快照。'), h('div', {class: 'top-space'}, actions(button('生成送审稿', () => createExport('review')), button('生成已内部复核版', () => createExport('reviewed'), 'primary', {disabled: review.status !== 'reviewed' || !review.current_review_id || report.blocking_count > 0}))))),
    card('历史导出', exports.items.length ? h('div', {}, [...exports.items].reverse().map(exportEntry)) : empty('尚无导出成果', '即使存在缺项，也可以生成带风险清单的送审稿供企业内部讨论。')),
    card('内部复核冻结历史', review.snapshots.length ? h('div', {}, [...review.snapshots].reverse().map(item => h('div', {class: 'version-entry'}, h('h3', {}, `项目 v${item.project_version} · ${item.reviewer}`), h('p', {}, dateTime(item.frozen_at || item.created_at)), actions(badge(item.id === review.current_review_id ? '当前冻结' : '历史冻结', item.id === review.current_review_id ? 'good' : ''), button('查看不可变快照', () => frozenDialog('内部复核冻结快照', `${ctx.base}/review/snapshots/${item.id}`), 'small'))))) : notice('尚未形成内部复核冻结快照。')));
}
