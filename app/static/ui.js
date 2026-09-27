import {download, isWriting} from './api.js';

let sequence = 0;
export const uid = () => 'ui-' + (++sequence);
export const clone = value => JSON.parse(JSON.stringify(value));
export const BUSINESS = {supervision: '工程监理', tis: 'TIS 风险减量'};
export const CATEGORIES = {qualification: '资格条件', mandatory: '强制要求', scoring: '评分要点', delivery: '交付要求', pricing: '报价约束'};
export const SECTIONS = {technical: '技术', commercial: '商务', qualification: '资质', response: '响应表', internal: '内部复核'};
export const RESPONSE = {pending: '待响应', responded: '已响应', gap: '存在缺口', not_applicable: '不适用'};
export const KINDS = {qualification: '企业资质', personnel: '人员证照', experience: '项目业绩'};
export function h(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const child of children.flat(Infinity)) {
    if (child !== null && child !== undefined && child !== false) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  for (const [key, value] of Object.entries(attributes || {})) {
    if (value === undefined || value === null) continue;
    if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'class') node.className = value;
    else if (['value', 'checked', 'disabled', 'readOnly', 'required', 'selected', 'multiple', 'open'].includes(key)) node[key] = value;
    else node.setAttribute(key, String(value));
  }
  return node;
}
export const actions = (...nodes) => h('div', {class: 'actions'}, ...nodes);
export const badge = (text, tone = '') => h('span', {class: 'badge ' + tone}, text);
export const notice = (text, tone = '', ...nodes) => h('div', {class: 'notice ' + tone}, text, ...nodes);
export const detail = (title, ...body) => h('details', {}, h('summary', {}, title), h('div', {class: 'details-body'}, ...body));
export const text = value => value === null || value === undefined || value === '' ? '未填写' : String(value);
export const short = (value, limit = 110) => String(value || '').length > limit ? String(value).slice(0, limit) + '…' : String(value || '');
export function dateTime(value) {
  if (!value) return '未设置';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString('zh-CN', {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false, timeZoneName: 'short'});
}
export function inputDateTime(value) {
  if (!value) return '';
  const d = new Date(value);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
export const bytes = size => size >= 1048576 ? (size / 1048576).toFixed(1) + ' MB' : (size / 1024).toFixed(1) + ' KB';
export function locator(value = {}) {
  if (value.kind === 'page') return `PDF 第 ${value.page} 页`;
  if (value.kind === 'paragraph') return `Word 段落 ${value.paragraph}`;
  if (value.kind === 'table') return `Word 表格 ${value.table} · 第 ${value.row} 行`;
  return value.note ? '人工定位 · ' + value.note : '人工摘录';
}
export function reviewBadge(item) {
  return item.review_status === 'approved' ? badge('人工核验通过', 'good') : item.review_status === 'rejected' ? badge('人工核验未通过', 'bad') : badge('待人工核验', 'warn');
}
export function projectBadge(project) {
  return project.archived ? badge('已归档') : project.review_status === 'reviewed' ? badge('已内部复核', 'good') : badge('待内部复核', 'warn');
}
export function materialWarnings(item, deadline) {
  const day = new Date().toLocaleDateString('sv-SE');
  const threshold = deadline && deadline.slice(0, 10) > day ? deadline.slice(0, 10) : day;
  return actions(reviewBadge(item), item.is_demo ? badge('虚构演示', 'warn') : null,
    item.valid_until && item.valid_until < threshold ? badge('当前或截止时点已过期', 'bad') : null,
    item.valid_from && item.valid_from > day ? badge('尚未生效', 'warn') : null,
    !item.valid_until && !item.validity_note ? badge('有效期未说明', 'warn') : null);
}
export function button(label, onClick, tone = '', attrs = {}) {
  const node = h('button', {type: 'button', class: 'button ' + tone, ...attrs}, label);
  if (onClick) node.addEventListener('click', async event => {
    if (node.disabled) return;
    node.disabled = true;
    node.setAttribute('aria-busy', 'true');
    try { await onClick(event); }
    catch (error) { if (error.name !== 'AbortError') errorDialog(error); }
    finally { node.disabled = Boolean(attrs.disabled); node.removeAttribute('aria-busy'); }
  });
  return node;
}
export const linkButton = (label, href, tone = '') => h('a', {class: 'button ' + tone, href}, label);
export function toast(message, tone = '') {
  const node = h('div', {class: 'toast ' + tone}, h('span', {}, message));
  node.append(h('button', {type: 'button', 'aria-label': '关闭通知', onclick: () => node.remove()}, '×'));
  document.querySelector('#toasts').append(node);
  setTimeout(() => node.remove(), tone === 'error' ? 14000 : 6000);
}
export function pageHead(title, description, eyebrow, ...buttons) {
  return h('div', {class: 'page-head'}, h('div', {}, h('div', {class: 'eyebrow'}, eyebrow), h('h1', {}, title), h('p', {}, description)), actions(...buttons));
}
export function card(title, body, aside = null) {
  return h('section', {class: 'card'}, title ? h('header', {class: 'card-head'}, h('h2', {}, title), aside) : null, h('div', {class: 'card-body'}, body));
}
export function empty(title, description, ...buttons) {
  return h('div', {class: 'empty'}, h('div', {class: 'empty-mark', 'aria-hidden': 'true'}, '01'), h('h3', {}, title), h('p', {}, description), actions(...buttons));
}
export function loading(label = '正在读取本地数据…') { return h('div', {class: 'loading-panel', role: 'status'}, h('span', {class: 'spinner', 'aria-hidden': 'true'}), h('p', {}, label)); }
export function errorPanel(error, retry) {
  return notice(h('div', {}, h('strong', {}, error.message || '操作失败'), h('p', {class: 'small'}, error.code || '')), 'error', retry ? actions(button('重试读取', retry)) : null);
}
export function definition(entries) { return h('dl', {class: 'definition-list'}, entries.flatMap(([key, value]) => [h('dt', {}, key), h('dd', {}, value instanceof Node ? value : text(value))])); }
export function downloadButton(file, label) { return button(label || '下载原件', () => download(file.download_url, file.name), 'small'); }
export function fileRow(file) {
  return h('div', {class: 'file-row'}, h('span', {class: 'file-icon'}, file.name.split('.').pop().toUpperCase().slice(0, 5)), h('div', {class: 'file-name'}, h('strong', {}, file.name), h('p', {}, `${bytes(file.size)} · v${file.version}`)), downloadButton(file));
}
export function field(label, control, hint = '', className = '') {
  if (!control.id) control.id = uid();
  const hintId = control.id + '-hint';
  if (hint) control.setAttribute('aria-describedby', hintId);
  const node = h('div', {class: 'field ' + className}, h('label', {for: control.id}, label, control.required ? h('span', {class: 'required', 'aria-hidden': 'true'}, '*') : null), control, hint ? h('span', {class: 'hint', id: hintId}, hint) : null);
  node.control = control;
  return node;
}
export function bind(model, key, label, options = {}) {
  const {type = 'text', options: choices, hint = '', className = '', onChange, ...attrs} = options;
  const control = choices ? h('select', attrs, Object.entries(choices).map(([value, name]) => h('option', {value}, name))) : h(type === 'textarea' ? 'textarea' : 'input', {...attrs, ...(type === 'textarea' ? {} : {type})});
  control.value = model[key] ?? '';
  const update = () => { model[key] = control.value; onChange?.(control.value); };
  control.addEventListener(choices || type === 'file' ? 'change' : 'input', update);
  return field(label, control, hint, className);
}
export function checkbox(model, key, label, options = {}) {
  const control = h('input', {type: 'checkbox', checked: Boolean(model[key]), ...options});
  control.addEventListener('change', () => { model[key] = control.checked; });
  return h('label', {class: 'check'}, control, h('span', {}, label));
}
export function checks(model, key, items, {label = item => item.name || item.title, info = null, emptyText = '暂无可选内容', disabled = false} = {}) {
  if (!items.length) return notice(emptyText);
  return h('div', {class: 'check-list'}, items.map(item => {
    const input = h('input', {type: 'checkbox', checked: (model[key] || []).includes(item.id), disabled});
    input.addEventListener('change', () => {
      const selected = new Set(model[key] || []);
      if (input.checked) selected.add(item.id); else selected.delete(item.id);
      model[key] = [...selected];
    });
    return h('label', {class: 'check-card'}, input, h('div', {class: 'check-copy'}, h('strong', {}, label(item)), info ? info(item) : null));
  }));
}
export function businessChecks(model) {
  return h('div', {class: 'field'}, h('span', {class: 'field-label'}, '适用业务（至少一项）'), checks(model, 'business_types', Object.entries(BUSINESS).map(([id, name]) => ({id, name}))));
}

const editors = new Set();
const memoryBuffers = new Map();
const BUFFER_PREFIX = 'bid-local-unsaved:';
let storageWarning = false;
function stored(key) {
  if (memoryBuffers.has(key)) return memoryBuffers.get(key);
  try { const value = sessionStorage.getItem(BUFFER_PREFIX + key); return value ? JSON.parse(value) : null; } catch { return null; }
}
function stash(key, data, files = []) {
  const entry = {at: new Date().toISOString(), data: clone(data), files};
  memoryBuffers.set(key, entry);
  try { sessionStorage.setItem(BUFFER_PREFIX + key, JSON.stringify(entry)); }
  catch { if (!storageWarning) { storageWarning = true; toast('浏览器暂存不可用，输入仅保留在本页内存。关闭或刷新前请完成保存。', 'error'); } }
}
function clearStored(key) { memoryBuffers.delete(key); try { sessionStorage.removeItem(BUFFER_PREFIX + key); } catch { /* 不影响内存编辑 */ } }
function connectedEditors(root = document) {
  for (const editor of editors) if (!editor.node.isConnected) editors.delete(editor);
  return [...editors].filter(editor => root.contains(editor.node));
}
export function confirmDialog(title, message, label = '确认继续', dangerous = false) {
  return new Promise(resolve => {
    const dialog = modal(title, {small: true});
    let answered = false;
    const answer = result => { if (answered) return; answered = true; dialog.close(true); resolve(result); };
    dialog.body.append(h('p', {class: 'confirm-copy'}, message), actions(button('取消', () => answer(false)), button(label, () => answer(true), dangerous ? 'danger' : 'primary')));
    dialog.node.addEventListener('close', () => { if (!answered) { answered = true; resolve(false); } });
  });
}
export async function guard(root = document) {
  if (isWriting() || connectedEditors(root).some(editor => editor.busy)) { toast('操作正在保存，请等待完成后再离开。'); return false; }
  const dirty = connectedEditors(root).filter(editor => editor.dirty);
  if (!dirty.length) return true;
  const okay = await confirmDialog('保留未保存的修改？', '当前输入尚未写入数据库。继续离开将把文本和选择保留在本机当前浏览器会话中，返回同一编辑界面可手动恢复。文件选择无法跨刷新恢复，需要重新选择。', '保留输入并离开');
  if (okay) dirty.forEach(editor => editor.retain());
  return okay;
}
export function modal(title, {wide = false, small = false} = {}) {
  const titleId = uid();
  const node = h('dialog', {class: 'dialog' + (wide ? ' wide-dialog' : '') + (small ? ' small-dialog' : ''), 'aria-labelledby': titleId});
  const body = h('div', {class: 'dialog-body'});
  const previousFocus = document.activeElement;
  const close = async (force = false) => {
    if (!force && !(await guard(node))) return false;
    node.close(); node.remove();
    if (previousFocus?.isConnected) previousFocus.focus();
    return true;
  };
  node.append(h('div', {class: 'dialog-head'}, h('h2', {id: titleId}, title), button('×', () => close(), 'quiet close-button', {'aria-label': '关闭对话框'})), body);
  node.addEventListener('cancel', event => { event.preventDefault(); close(); });
  document.body.append(node);
  node.showModal();
  return {node, body, close};
}
export function errorDialog(error) {
  const dialog = modal('操作未完成', {small: true});
  dialog.body.append(errorPanel(error), h('p', {class: 'small muted top-space'}, '未自动重试写入。请保留输入，并根据提示核对当前记录。'));
  if (error.status === 409 || error.status === 0) dialog.body.append(actions(button('刷新页面并保留输入', async () => { await dialog.close(true); window.dispatchEvent(new Event('request-refresh')); })));
}

// 表单只暂存编辑模型；写入回调逐字段构造请求，不发送响应实体。
export function editorForm({key, initial, build, save, refresh, afterSave, submitLabel = '保存修改', readonly = false}) {
  const model = clone(initial);
  const node = h('form', {class: 'editor-form'});
  const restoreSlot = h('div', {class: 'restore-slot'});
  const errors = h('div', {class: 'form-errors', role: 'alert'});
  const fields = h('fieldset', {class: 'editor-fieldset', disabled: readonly});
  const status = h('span', {class: 'save-status'}, readonly ? '只读内容' : '修改后请显式保存');
  const submit = h('button', {type: 'submit', class: 'button primary', disabled: readonly}, submitLabel);
  let baseline = JSON.stringify(model);
  let dirty = false;
  let busy = false;
  let awaitingRestore = false;
  const selectedFiles = () => [...fields.querySelectorAll('input[type="file"]')].flatMap(input => [...input.files].map(file => file.name));
  const editor = {
    node, model,
    get dirty() { return dirty || awaitingRestore || selectedFiles().length > 0; }, get busy() { return busy; },
    retain() { if (!awaitingRestore && editor.dirty) stash(key, model, selectedFiles()); },
    syncAvailability() {
      fields.disabled = readonly || busy || awaitingRestore || isWriting();
      submit.disabled = fields.disabled;
    },
    changed() {
      if (awaitingRestore || readonly) return;
      const files = selectedFiles();
      dirty = JSON.stringify(model) !== baseline || files.length > 0;
      status.textContent = dirty ? files.length ? '未保存 · 文件需先上传，离开后须重新选择' : '未保存 · 输入已暂存于本机会话' : '无未保存修改';
      status.classList.toggle('dirty', dirty);
      if (dirty) stash(key, model, files);
      else clearStored(key);
    },
    redraw() { fields.replaceChildren(build(model, editor)); },
    clean() { dirty = false; baseline = JSON.stringify(model); clearStored(key); status.textContent = '已保存到本地数据库'; status.classList.remove('dirty'); },
    async submit() {
      if (isWriting()) { toast('其他写入尚未完成，请稍候再保存；当前输入不会丢失。'); return false; }
      if (busy || readonly || awaitingRestore || !node.reportValidity()) return false;
      busy = true; fields.disabled = true; submit.disabled = true; status.textContent = '正在保存，请勿重复操作…'; errors.replaceChildren();
      let result;
      try {
        result = await save(model, editor);
        editor.clean();
      } catch (error) {
        dirty = true; stash(key, model, selectedFiles()); status.textContent = '保存未完成 · 输入已保留'; status.classList.add('dirty');
        const panel = errorPanel(error);
        if ((error.status === 409 || error.status === 0) && refresh) {
          panel.append(actions(button('读取最新版本，保留我的输入', async () => {
            const latest = await refresh(model);
            const comparison = h('div', {class: 'top-space'}, notice('以下为服务器最新内容。当前输入没有被覆盖。请核对差异后，再明确采用新版本号继续编辑。', 'warn'), latest.view || null);
            if (latest.apply) comparison.append(actions(button('已核对差异，采用最新版本号', () => {
              latest.apply();
              stash(key, model, selectedFiles());
              errors.replaceChildren(notice('已更新版本号，仍保留你的输入。请人工合并差异后再次保存；不会自动覆盖服务器。', 'warn'));
            }, 'primary small')));
            errors.replaceChildren(comparison);
          })));
        }
        errors.append(panel); errors.scrollIntoView({block: 'nearest'});
        return false;
      } finally { busy = false; editor.syncAvailability(); }
      if (afterSave) {
        try { await afterSave(result, editor); }
        catch (error) { toast('已保存，但页面更新失败：' + error.message + '。请刷新读取。', 'error'); }
      }
      return true;
    }
  };
  node.append(restoreSlot, errors, fields, h('div', {class: 'form-footer'}, status, actions(readonly ? null : submit)));
  editor.redraw();
  node.addEventListener('input', () => editor.changed());
  node.addEventListener('change', () => editor.changed());
  node.addEventListener('submit', event => { event.preventDefault(); editor.submit(); });
  const buffer = stored(key);
  if (buffer && !readonly) {
    awaitingRestore = true;
    submit.disabled = true;
    fields.disabled = true;
    const choose = notice(`发现 ${dateTime(buffer.at)} 保留的未保存输入。它尚未写入数据库。`, 'warn');
    if (buffer.files?.length) choose.append(h('p', {}, '此前选择的文件未保存在浏览器暂存中，请重新选择：' + buffer.files.join('、')));
    choose.append(actions(button('恢复未保存输入', () => {
      Object.keys(model).forEach(k => delete model[k]); Object.assign(model, clone(buffer.data));
      awaitingRestore = false;
      editor.redraw(); editor.changed(); restoreSlot.replaceChildren(); editor.syncAvailability();
    }, 'primary small'), button('不恢复，使用服务器内容', async () => {
      if (!(await confirmDialog('放弃保留输入？', '这将清除该表单先前暂存的输入，不影响数据库内容。', '清除暂存', true))) return;
      clearStored(key); awaitingRestore = false; restoreSlot.replaceChildren(); editor.syncAvailability();
    }, 'small')));
    restoreSlot.append(choose);
  }
  editors.add(editor);
  editor.syncAvailability();
  return editor;
}
export function retainedInputs() {
  const slot = h('div');
  function render() {
    const keys = new Set(memoryBuffers.keys());
    try { for (let i = 0; i < sessionStorage.length; i++) { const key = sessionStorage.key(i); if (key.startsWith(BUFFER_PREFIX)) keys.add(key.slice(BUFFER_PREFIX.length)); } } catch { /* 内存副本仍可使用 */ }
    const entries = [...keys].map(key => ({key, entry: stored(key)})).filter(row => row.entry);
    const names = {project: '项目与事实', section: '章节正文', quote: '商务报价', requirement: '需求条款', document: '招标来源', resource: '共享资源', selection: '项目选用资料', verify: '人工核验', decision: '人工复核意见', reconcile: '草稿核对', finalize: '最终确认', copy: '模板复制'};
    slot.replaceChildren(notice('这里只保存当前浏览器会话的输入，不是数据库，也不包含文件原件。旧稿变为只读后，可在此查看暂存正文并人工复制到新稿。'), ...entries.map(({key, entry}) => h('div', {class: 'file-row'}, h('div', {class: 'file-name'}, h('strong', {}, names[key.split(':')[0]] || '编辑输入'), h('p', {}, dateTime(entry.at)), h('p', {class: 'mono'}, key)), actions(button('查看输入', () => {
      const dialog = modal('保留的未保存输入 · 只读', {wide: true});
      const labels = {body: '章节正文', content: '素材正文', text: '条款 / 摘录', name: '名称', title: '标题', opinion: '人工意见', source_note: '来源说明', response_note: '响应说明', note: '核对说明', scope: '适用范围', description: '说明', tax_note: '税率依据', tax_rate: '税率', expected_version: '编辑时项目 / 资源版本', entity_version: '编辑时实体版本'};
      function values(value, prefix = '') {
        if (Array.isArray(value)) return value.flatMap((row, index) => values(row, prefix + ' / ' + (index + 1)));
        if (value && typeof value === 'object') return Object.entries(value).flatMap(([name, child]) => values(child, prefix ? prefix + ' / ' + (labels[name] || name) : labels[name] || name));
        return [field(prefix, h('textarea', {readOnly: true, rows: String(value ?? '').length > 200 ? 8 : 2, value: typeof value === 'boolean' ? (value ? '是' : '否') : String(value ?? '')}), '只读保留，可选择文本后复制。')];
      }
      dialog.body.append(h('div', {}, notice('此副本未提交到数据库。请人工比较，不要用它直接覆盖当前版本。', 'warn'), ...(entry.files?.length ? [notice('此前选择但未随输入保留的文件：' + entry.files.join('、') + '。需要重新选择。', 'warn')] : []), h('div', {class: 'top-space'}, ...values(entry.data))));
    }, 'small'), button('清除', async () => {
      if (!(await confirmDialog('清除这份未保存输入？', '清除后无法从本机浏览器暂存中恢复，不影响数据库中的已保存内容。', '确认清除', true))) return;
      clearStored(key); render();
    }, 'quiet small')))));
    if (!entries.length) slot.append(h('p', {class: 'small muted top-space'}, '暂无保留的未保存输入。'));
  }
  render(); return slot;
}
export function versionRefresh(model, data, entity, view) {
  return {view, apply: () => { model.expected_version = data.item.version; if ('entity_version' in model) model.entity_version = entity?.version || 0; }};
}
export function serverText(title, content) { return detail(title, h('div', {class: 'prewrap small bounded'}, content || '（空白）')); }
window.addEventListener('beforeunload', event => {
  if (isWriting() || connectedEditors().some(editor => editor.dirty || editor.busy)) {
    connectedEditors().forEach(editor => editor.retain());
    event.preventDefault(); event.returnValue = '';
  }
});
window.addEventListener('api-writing', () => connectedEditors().forEach(editor => editor.syncAvailability()));
window.addEventListener('post-save-refresh-error', event => toast('保存已成功，但项目重读失败：' + event.detail + '。继续操作前请刷新。', 'error'));
