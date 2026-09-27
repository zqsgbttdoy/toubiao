import {api, apiDirect, aiConfig, rememberAIConfig, query} from './api.js';
import {h, actions, badge, notice, button, linkButton, pageHead, card, loading, errorPanel, modal, confirmDialog, toast, definition, downloadButton, dateTime, bytes, retainedInputs, editorForm, field, bind, uid, versionRefresh, serverText} from './ui.js';

export async function loadDemo(onLoaded) {
  const okay = await confirmDialog('手动载入明确虚构的演示资料？', '将向本机数据库添加监理与 TIS 两个虚构项目、合成招标文件和未核验的虚构企业资料。所有内容均非真实，禁止用于真实投标。不会自动确认条款、报价或人工核验。', '确认载入虚构演示');
  if (!okay) return;
  const result = await api('/api/demo/load', {method: 'POST', body: {confirmation: true}});
  toast(result.already_loaded ? '演示资料此前已载入，未重复创建。' : '明确虚构的演示资料已载入。');
  await onLoaded?.();
}
async function backup() {
  if (!(await confirmDialog('创建本机一致性备份？', '备份包含数据库及全部附件，会核对原始附件哈希。文件可能包含企业敏感资料，请妥善保管。备份不包括浏览器尚未保存的编辑输入。', '创建备份'))) return;
  const dialog = modal('本地一致性备份');
  dialog.body.append(loading('正在创建 SQLite 一致性快照并核对附件…'));
  try {
    const item = (await api('/api/backups', {method: 'POST'})).item;
    dialog.body.replaceChildren(notice('一致性备份已生成。请下载并妥善保管；恢复只能在停机后进行。'), h('div', {class: 'top-space'}, definition([['备份名称', item.name], ['文件大小', bytes(item.size)], ['生成时间', dateTime(item.created_at)], ['SHA-256', item.sha256]])), h('div', {class: 'top-space'}, actions(downloadButton(item, '下载一致性备份 ZIP'))));
  } catch (error) { dialog.body.replaceChildren(errorPanel(error), h('p', {class: 'small muted top-space'}, '没有把失败伪装为成功。若附件缺失或哈希不一致，请先核对本地原件。')); }
}
// ===== AI 服务（Phase 1 只读辅助） =====
const AI_PROVIDERS = [
  ['null', '禁用（默认）', '不连接任何模型。文档提取、候选条款、检索与风险检查全部由本机规则完成。'],
  ['ollama', '本地 Ollama', '连接本机 Ollama 的 OpenAI 兼容端点。正文不出本机；未视为云端时端点仅允许本机回环地址。'],
  ['openai_compat', '自定义 OpenAI 兼容端点', '连接局域网或云端兼容服务。数据将离开本机，脱敏强度自动锁定为最严且不可降低。']
];
const AI_REDACTION = [
  ['standard', '标准（本地模型）', '电话、邮箱、身份证号与信用代码硬脱敏，金额转区间，已知单位与人名转代号。'],
  ['strict', '最严（外部端点）', '在标准基础上额外脱敏地址与项目名称。端点非本机回环时强制使用。']
];
const AI_FEATURES = {summarize: '招标文件智能摘要', classify: '条款分类', generate_section: '章节草拟'};
const REDACTION_LABELS = {phones: '电话', emails: '邮箱', id_cards: '身份证号', credit_codes: '信用代码', amounts: '金额', company_names: '单位名称', person_names: '人名', addresses: '地址', project_names: '项目名称'};
const LOOPBACK_HOSTS = ['127.0.0.1', 'localhost', '::1', '[::1]'];
export function redactionText(summary) {
  const entries = Object.entries(summary || {});
  return entries.length ? entries.map(([key, count]) => `${REDACTION_LABELS[key] || key}×${count}`).join('，') : '未命中敏感信息';
}
function isLoopback(url) {
  try { return LOOPBACK_HOSTS.includes(new URL(String(url || '').trim()).hostname.toLowerCase()); } catch { return false; }
}
export function aiStatusBadge(config) {
  if (!config || !config.enabled || (config.provider || 'null') === 'null') return badge('外部 AI 未接入', 'good');
  return config.is_cloud ? badge('云端 AI 已启用 · 数据将离开本机', 'warn') : badge('本地 AI 已启用', 'info');
}
function radioGroup(model, key, label, choices, {hint = '', disabled = false, inline = false, onChange} = {}) {
  const name = uid();
  const group = h('div', {class: inline ? 'radio-row' : '', role: 'radiogroup', 'aria-label': label}, choices.map(([value, title, description]) => {
    const input = h('input', {type: 'radio', name, value, checked: String(model[key]) === value, disabled});
    input.addEventListener('change', () => { if (input.checked) { model[key] = value; onChange?.(value); } });
    return inline ? h('label', {class: 'check'}, input, h('span', {}, title))
      : h('label', {class: 'check-card'}, input, h('div', {class: 'check-copy'}, h('strong', {}, title), description ? h('p', {}, description) : null));
  }));
  return h('div', {class: 'field'}, h('span', {class: 'field-label'}, label), group, hint ? h('span', {class: 'hint'}, hint) : null);
}
function aiTestView(item) {
  const facts = definition([['端点', item.base_url || '未设置'], ['提供方', item.provider], ['配置模型', item.model || '未设置'], ['端点返回模型', item.models?.length ? item.models.join('、') : '（未返回模型列表）'], ['往返延迟', item.latency_ms + ' ms']]);
  return item.reachable
    ? notice(h('div', {class: 'ai-test-result'}, actions(badge('端点可达', 'good'), badge('延迟 ' + item.latency_ms + ' ms')), h('div', {class: 'top-space'}, facts)), '')
    : notice(h('div', {class: 'ai-test-result'}, actions(badge('连接未成功', 'bad')), h('p', {class: 'small top-space'}, item.reason || '请核对端点地址、服务是否已启动、模型是否已拉取。'), h('div', {class: 'top-space'}, facts)), 'error');
}
function aiCallRow(record) {
  const detailCell = h('td', {colSpan: '6'});
  const detailRow = h('tr', {class: 'ai-log-detail', hidden: true}, detailCell);
  let fetched = false;
  const toggle = button('展开', async () => {
    const open = detailRow.hidden;
    detailRow.hidden = !open;
    toggle.textContent = open ? '收起' : '展开';
    toggle.setAttribute('aria-expanded', String(open));
    if (!open || fetched) return;
    fetched = true;
    detailCell.replaceChildren(loading('正在读取该条审计详情…'));
    try {
      const item = (await api('/api/ai/calls/' + record.id)).item;
      detailCell.replaceChildren(definition([['审计编号', '#' + item.id], ['项目', item.project_id || '未关联'], ['提供方', item.provider], ['端点', item.endpoint_masked || '未记录'], ['人工确认', item.user_confirmed ? '已确认 · ' + dateTime(item.confirmation_at) : '未确认'], ['发送范围', (item.scope_applied || []).join('、') || '未记录'], ['脱敏命中', redactionText(item.redaction_summary)], ['延迟', item.latency_ms + ' ms'], ['错误码', item.error_code || '无'], ['发送内容指纹', item.prompt_hash || '无'], ['返回内容指纹', item.response_hash || '无']]),
        serverText('发送内容预览（脱敏后前 500 字）', item.prompt_preview), serverText('模型返回预览（前 500 字）', item.response_preview));
    } catch (error) { fetched = false; detailCell.replaceChildren(errorPanel(error)); }
  }, 'quiet small', {'aria-expanded': 'false'});
  return [h('tr', {}, h('td', {}, toggle), h('td', {class: 'small'}, dateTime(record.at)), h('td', {}, AI_FEATURES[record.feature] || record.feature), h('td', {class: 'small'}, record.model || '未记录'),
    h('td', {class: 'small number'}, `${record.prompt_tokens} / ${record.response_tokens}`),
    h('td', {}, record.status === 'success' ? badge('成功', 'good') : badge(record.fallback_used ? '已降级 · 本地规则' : '未完成', 'warn'), record.error_code ? h('div', {class: 'small muted'}, record.error_code) : null)), detailRow];
}
function aiSettingsCard(config, configError, onSaved) {
  if (!config) {
    return card('AI 服务', h('div', {}, errorPanel(configError || new Error('无法读取 AI 配置'), () => window.dispatchEvent(new Event('request-refresh'))), h('p', {class: 'small muted top-space'}, '读取失败不影响其余本地能力，文档提取与规则检查仍可正常使用。')));
  }
  const statusSlot = h('div', {class: 'badges'}, aiStatusBadge(config));
  const testSlot = h('div');
  const logSlot = h('div');
  const logState = {limit: 20, offset: 0};
  // 密钥只存在于闭包，不进入表单模型，因此不会被浏览器未保存暂存写下。
  let secretKey = '';
  async function loadCalls() {
    logSlot.replaceChildren(loading('正在读取 AI 调用审计…'));
    try {
      const data = await api('/api/ai/calls' + query({limit: logState.limit, offset: logState.offset}));
      if (!data.items.length) { logSlot.replaceChildren(notice('暂无 AI 调用记录。每次调用（包括降级为本地规则）都会在此留下审计痕迹。')); return; }
      logSlot.replaceChildren(h('div', {class: 'table-scroll'}, h('table', {class: 'ai-log-table'}, h('thead', {}, h('tr', {}, ['详情', '时间', '功能', '模型', 'tokens（发送 / 返回）', '状态'].map(label => h('th', {scope: 'col'}, label)))), h('tbody', {}, data.items.flatMap(aiCallRow)))),
        h('div', {class: 'ai-log-footer'}, h('span', {class: 'small muted'}, `共 ${data.total} 条 · 当前第 ${logState.offset + 1}–${Math.min(data.total, logState.offset + logState.limit)} 条`),
          actions(button('上一页', () => { logState.offset = Math.max(0, logState.offset - logState.limit); loadCalls(); }, 'small', {disabled: logState.offset === 0}),
            button('下一页', () => { logState.offset += logState.limit; loadCalls(); }, 'small', {disabled: logState.offset + logState.limit >= data.total}))));
    } catch (error) { logSlot.replaceChildren(errorPanel(error, loadCalls)); }
  }
  const form = editorForm({
    key: 'ai_config:default', submitLabel: '保存配置',
    initial: {
      expected_version: config.version, provider: config.provider || 'null',
      base_url: config.base_url || 'http://127.0.0.1:11434/v1',
      model: config.model || 'qwen2.5:7b-instruct', embedding_model: config.embedding_model || 'bge-m3',
      api_key_set: false, api_key_masked: config.api_key_masked || '',
      redaction_level: config.redaction_level || 'standard', daily_token_budget: String(config.daily_token_budget ?? 200000),
      default_scope: config.default_scope || ['documents'], max_concurrent: config.max_concurrent ?? 1, timeout_seconds: config.timeout_seconds ?? 120
    },
    build(model, editor) {
      const endpointSlot = h('div');
      const privacySlot = h('div');
      let keyRestoreLost = false;
      // 从浏览器暂存恢复时只能恢复标志，密钥本体未暂存，需提示重新输入。
      if (model.api_key_set && !secretKey) { model.api_key_set = false; keyRestoreLost = true; }
      const isExternal = () => model.provider === 'openai_compat' || (model.provider !== 'null' && Boolean(model.base_url.trim()) && !isLoopback(model.base_url));
      function renderPrivacy() {
        if (model.provider === 'null') { privacySlot.replaceChildren(notice('当前为禁用状态：不会向任何端点发送内容，也不会产生 AI 调用记录。')); return; }
        const external = isExternal();
        if (external) model.redaction_level = 'strict';
        privacySlot.replaceChildren(h('section', {class: 'form-section'}, h('h3', {}, '脱敏与预算'),
          external ? notice(model.provider === 'openai_compat' ? '已选择自定义 OpenAI 兼容端点：数据将离开本机，脱敏强度锁定为最严，不可降低。' : '当前端点不是本机回环地址，按外部端点处理：脱敏强度锁定为最严。', 'warn') : null,
          h('div', {class: external ? 'top-space' : ''}, radioGroup(model, 'redaction_level', '脱敏强度', AI_REDACTION, {disabled: external})),
          bind(model, 'daily_token_budget', '每日 token 预算', {type: 'number', min: '0', max: '100000000', step: '1000', required: true, hint: '填 0 表示不限制。当日累计预计用量超出预算时，调用自动降级为本地规则，不会中断工作。'})));
      }
      function renderEndpoints() {
        if (model.provider === 'null') {
          endpointSlot.replaceChildren(notice('未接入任何模型。若需试用，请先在本机启动 Ollama 并拉取模型，再回到此处选择提供方。'));
          return;
        }
        const ollama = model.provider === 'ollama';
        const keyInput = h('input', {type: 'password', maxLength: 500, autocomplete: 'off', placeholder: ollama ? '本地 Ollama 可留空' : '外部端点通常需要密钥'});
        keyInput.value = secretKey;
        keyInput.addEventListener('input', () => { secretKey = keyInput.value; model.api_key_set = secretKey.trim() !== ''; editor.changed(); });
        endpointSlot.replaceChildren(h('section', {class: 'form-section'}, h('h3', {}, '端点与模型'),
          keyRestoreLost ? notice('此前输入但尚未保存的 API 密钥未被浏览器暂存保留。已保存过的密钥不受影响；如需更换请重新输入。', 'warn') : null,
          bind(model, 'base_url', '端点地址', {required: true, maxLength: 500, placeholder: 'http://127.0.0.1:11434/v1', hint: ollama ? 'Ollama 需以 /v1 结尾；非云端时仅允许 127.0.0.1、localhost 或 ::1。' : '需为 OpenAI 兼容服务地址，通常以 /v1 结尾。', onChange: renderPrivacy}),
          h('div', {class: 'form-grid'},
            bind(model, 'model', '对话模型', {required: true, maxLength: 200, placeholder: 'qwen2.5:7b-instruct', hint: '需与端点上已部署的模型名称完全一致。'}),
            bind(model, 'embedding_model', '嵌入模型', {maxLength: 200, placeholder: 'bge-m3', hint: 'Phase 1 未启用向量检索，可保留默认值。'})),
          field('API 密钥', keyInput, model.api_key_masked ? `已保存密钥 ${model.api_key_masked}；留空表示保持不变，重新输入即覆盖。` : '密钥仅以编码形式保存在本机数据库；出于安全考虑，未保存的密钥不写入浏览器暂存。'),
          h('div', {class: 'top-space'}, actions(button('测试连接', runTest, 'small'))),
          h('p', {class: 'small muted top-space'}, '测试连接使用已保存到本机数据库的配置；修改端点、模型或密钥后请先保存再测试。'),
          h('div', {class: 'top-space'}, testSlot)));
      }
      async function runTest() {
        testSlot.replaceChildren(loading('正在测试已保存的 AI 端点…'));
        try { testSlot.replaceChildren(aiTestView((await apiDirect('/api/ai/test', {method: 'POST'})).item)); }
        catch (error) { testSlot.replaceChildren(errorPanel(error, runTest)); }
      }
      renderEndpoints();
      renderPrivacy();
      return h('div', {},
        notice('Phase 1 为只读辅助：AI 结果仅作为建议展示，不会写入项目、条款、草稿、报价或复核结论，也不自动确认任何内容。'),
        h('div', {class: 'top-space'}, radioGroup(model, 'provider', 'AI 提供方', AI_PROVIDERS, {hint: '切换提供方只改变本地表单，必须点击“保存配置”才会生效。', onChange: () => { renderEndpoints(); renderPrivacy(); }})),
        endpointSlot, privacySlot);
    },
    async save(model) {
      const url = model.base_url.trim();
      const external = model.provider === 'openai_compat' || (Boolean(url) && !isLoopback(url));
      const budget = Math.max(0, Math.min(100000000, Number(model.daily_token_budget) || 0));
      return (await api('/api/ai/config', {method: 'PUT', body: {
        expected_version: model.expected_version, enabled: model.provider !== 'null', provider: model.provider,
        base_url: url, model: model.model.trim(), embedding_model: model.embedding_model.trim(),
        api_key: secretKey.trim() || null, is_cloud: external,
        redaction_level: external ? 'strict' : model.redaction_level,
        default_scope: model.default_scope, max_concurrent: model.max_concurrent,
        daily_token_budget: budget, timeout_seconds: model.timeout_seconds
      }})).item;
    },
    async refresh(model) {
      const fresh = await aiConfig(true);
      return versionRefresh(model, {item: fresh}, null, h('div', {}, definition([['提供方', fresh.provider], ['启用', fresh.enabled ? '是' : '否'], ['端点', fresh.base_url], ['对话模型', fresh.model], ['密钥', fresh.api_key_masked || '未设置'], ['脱敏强度', fresh.redaction_level === 'strict' ? '最严' : '标准'], ['每日预算', String(fresh.daily_token_budget)]])));
    },
    async afterSave(result, editor) {
      secretKey = '';
      editor.model.expected_version = result.version;
      editor.model.api_key_set = false;
      editor.model.api_key_masked = result.api_key_masked || '';
      editor.redraw();
      editor.clean();
      rememberAIConfig(result);
      window.dispatchEvent(new CustomEvent('ai-config-changed', {detail: result}));
      statusSlot.replaceChildren(aiStatusBadge(result));
      onSaved?.(result);
      logSlot.replaceChildren();
      logButton.textContent = '查看 AI 调用日志';
      logButton.setAttribute('aria-expanded', 'false');
      toast(result.external_ai ? `AI 服务已保存并启用（${result.provider}）。每次调用前仍会展示脱敏内容并要求你逐次确认。` : 'AI 服务已保存为禁用状态，不会向任何外部端点发送内容。');
    }
  });
  const logButton = button('查看 AI 调用日志', () => {
    const open = logSlot.childElementCount === 0;
    logButton.textContent = open ? '收起 AI 调用日志' : '查看 AI 调用日志';
    logButton.setAttribute('aria-expanded', String(open));
    if (open) loadCalls(); else logSlot.replaceChildren();
  }, 'small', {'aria-expanded': 'false'});
  return card('AI 服务', h('div', {}, form.node,
    h('section', {class: 'form-section top-space'}, h('h3', {}, '调用审计'), h('p', {class: 'small muted'}, '仅记录脱敏后发送内容的前 500 字预览与内容指纹，最多保留最近 5000 条。'), h('div', {class: 'top-space'}, actions(logButton)), h('div', {class: 'top-space'}, logSlot)),
    h('p', {class: 'small muted top-space'}, '配置 API 密钥不等于授权发送。每次 AI 调用前都会展示脱敏后的待发送内容，须您明确确认才会发送。')), statusSlot);
}
export async function settingsPage() {
  let aiError = null;
  const [settings, ai] = await Promise.all([api('/api/settings'), aiConfig().catch(error => { aiError = error; return null; })]);
  const boundaryBody = h('div');
  const renderBoundary = state => boundaryBody.replaceChildren(actions(aiStatusBadge(state), badge(settings.cloud_ocr ? '云 OCR 状态异常' : '无云 OCR'), badge(settings.telemetry ? '遥测状态异常' : '无遥测')),
    h('p', {class: 'small muted top-space'}, state?.external_ai ? '文档提取、模板组装、检索与风险检查仍全部由本机规则执行；AI 只在你逐次确认脱敏内容后提供只读摘要建议。页面本身不加载外部字体、CDN 或云端服务。' : '文档提取、模板组装、检索与风险检查均由本机规则执行。页面不加载外部字体、CDN 或云端服务。'),
    h('div', {class: 'top-space'}, notice('单机版本没有真实身份认证。审核人与核验人仅作为人工记录，不属于具备身份认证的审批。', 'warn')));
  renderBoundary(ai);
  return h('div', {class: 'page'}, pageHead('本地设置', '了解数据存放位置、隐私边界与恢复方式。首期仅供单机内部试用。', 'SETTINGS / 数据与边界', linkButton('完整使用帮助', '#help')),
    h('div', {class: 'settings-grid'}, h('div', {class: 'stack'},
      card('本机运行环境', h('div', {}, definition([['数据存放目录', settings.data_directory], ['监听地址', settings.host + ':' + settings.port], ['数据结构版本', settings.schema_version], ['单文件限制', bytes(settings.max_upload_bytes)], ['PDF 页数限制', settings.max_pdf_pages + ' 页'], ['隔离解析超时', settings.parse_timeout_seconds + ' 秒']]), h('div', {class: 'top-space'}, notice('路径由本机启动配置决定，此处只读显示。数据目录不能放在公开静态目录内，不提供危险的在线覆盖或迁移。'))),
      card('数据隐私', notice(settings.privacy_notice)), card('未保存输入恢复', retainedInputs())),
      h('div', {class: 'stack'}, card('本地能力与连接边界', boundaryBody),
        aiSettingsCard(ai, aiError, renderBoundary),
        card('一致性备份与停机恢复', h('div', {}, notice('备份将包含项目、修订记录与原始附件。未保存的浏览器输入不在备份中。'), h('div', {class: 'top-space'}, actions(button('创建一致性备份', backup, 'primary'))), h('div', {class: 'top-space'}, h('h3', {}, '恢复须先停止本软件'), h('p', {class: 'small muted prewrap top-space'}, settings.restore_instructions)))),
        card('虚构演示资料', h('div', {}, h('p', {class: 'small muted'}, '只有点击并明确确认才会载入。示例企业、项目与证明均为虚构，不可用于真实投标。'), h('div', {class: 'top-space'}, actions(button('手动载入虚构演示', () => loadDemo(() => window.dispatchEvent(new Event('request-refresh'))), 'small')))))))));
}
export async function helpPage() {
  const response = await api('/api/help');
  return h('div', {class: 'page'}, pageHead('使用帮助', '从第一份原文到可追溯的内部成果，按顺序完成每一步人工确认。', 'GUIDE / 本机使用指南', linkButton('返回项目工作台', '#dashboard', 'primary')),
    notice('推荐顺序：项目与事实 → 招标来源与条款 → 选择资料 → 商务报价 → 生成并编辑草稿 → 规则检查及三类人工意见 → 冻结 → 导出。', '', h('p', {}, '修改内容后回到草稿检查输入是否过期；报价变更必须重新生成。')),
    h('div', {class: 'help-grid section-gap'}, response.items.map((item, index) => card(null, h('div', {}, h('span', {class: 'help-number'}, String(index + 1).padStart(2, '0') + ' / LOCAL GUIDE'), h('h2', {}, item.title), h('p', {}, item.text))))),
    h('div', {class: 'section-gap'}, card('保存、冲突与恢复', h('div', {}, h('p', {class: 'small muted prewrap'}, '表单与正文均需点击保存。未保存的文本与选择暂存于当前浏览器会话，不会发送到外部；文件选择在刷新后需要重新选择。\n遇到 409 版本冲突，点击读取最新版本并核对差异，再明确采用新版本号继续编辑，不会自动覆盖服务器内容。\n离开页面前会确认保留输入。返回同一编辑表单可恢复；如果该草稿已经成为历史只读版本，可在本地设置的“未保存输入恢复”中查看并人工复制到新稿。\n网络中断时操作可能已写入数据库，先刷新检查记录，避免重复新建、上传或生成。')))));
}
