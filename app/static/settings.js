import {api} from './api.js';
import {h, actions, badge, notice, button, linkButton, pageHead, card, loading, errorPanel, modal, confirmDialog, toast, definition, downloadButton, dateTime, bytes, retainedInputs} from './ui.js';

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
export async function settingsPage() {
  const settings = await api('/api/settings');
  return h('div', {class: 'page'}, pageHead('本地设置', '了解数据存放位置、隐私边界与恢复方式。首期仅供单机内部试用。', 'SETTINGS / 数据与边界', linkButton('完整使用帮助', '#help')),
    h('div', {class: 'settings-grid'}, h('div', {class: 'stack'},
      card('本机运行环境', h('div', {}, definition([['数据存放目录', settings.data_directory], ['监听地址', settings.host + ':' + settings.port], ['数据结构版本', settings.schema_version], ['单文件限制', bytes(settings.max_upload_bytes)], ['PDF 页数限制', settings.max_pdf_pages + ' 页'], ['隔离解析超时', settings.parse_timeout_seconds + ' 秒']]), h('div', {class: 'top-space'}, notice('路径由本机启动配置决定，此处只读显示。数据目录不能放在公开静态目录内，不提供危险的在线覆盖或迁移。')))),
      card('数据隐私', notice(settings.privacy_notice)), card('未保存输入恢复', retainedInputs())),
      h('div', {class: 'stack'}, card('本地能力与连接边界', h('div', {}, actions(badge(settings.external_ai ? '外部 AI 状态异常，请核对配置' : '外部 AI 未接入', settings.external_ai ? 'bad' : 'good'), badge(settings.cloud_ocr ? '云 OCR 状态异常' : '无云 OCR'), badge(settings.telemetry ? '遥测状态异常' : '无遥测')),
        h('p', {class: 'small muted top-space'}, '文档提取、模板组装、检索与风险检查均由本机规则执行。页面不加载外部字体、CDN 或云端服务。'), h('div', {class: 'top-space'}, notice('单机版本没有真实身份认证。审核人与核验人仅作为人工记录，不属于具备身份认证的审批。', 'warn')))),
        card('一致性备份与停机恢复', h('div', {}, notice('备份将包含项目、修订记录与原始附件。未保存的浏览器输入不在备份中。'), h('div', {class: 'top-space'}, actions(button('创建一致性备份', backup, 'primary'))), h('div', {class: 'top-space'}, h('h3', {}, '恢复须先停止本软件'), h('p', {class: 'small muted prewrap top-space'}, settings.restore_instructions)))),
        card('虚构演示资料', h('div', {}, h('p', {class: 'small muted'}, '只有点击并明确确认才会载入。示例企业、项目与证明均为虚构，不可用于真实投标。'), h('div', {class: 'top-space'}, actions(button('手动载入虚构演示', () => loadDemo(() => window.dispatchEvent(new Event('request-refresh'))), 'small'))))))));
}
export async function helpPage() {
  const response = await api('/api/help');
  return h('div', {class: 'page'}, pageHead('使用帮助', '从第一份原文到可追溯的内部成果，按顺序完成每一步人工确认。', 'GUIDE / 本机使用指南', linkButton('返回项目工作台', '#dashboard', 'primary')),
    notice('推荐顺序：项目与事实 → 招标来源与条款 → 选择资料 → 商务报价 → 生成并编辑草稿 → 规则检查及三类人工意见 → 冻结 → 导出。', '', h('p', {}, '修改内容后回到草稿检查输入是否过期；报价变更必须重新生成。')),
    h('div', {class: 'help-grid section-gap'}, response.items.map((item, index) => card(null, h('div', {}, h('span', {class: 'help-number'}, String(index + 1).padStart(2, '0') + ' / LOCAL GUIDE'), h('h2', {}, item.title), h('p', {}, item.text))))),
    h('div', {class: 'section-gap'}, card('保存、冲突与恢复', h('div', {}, h('p', {class: 'small muted prewrap'}, '表单与正文均需点击保存。未保存的文本与选择暂存于当前浏览器会话，不会发送到外部；文件选择在刷新后需要重新选择。\n遇到 409 版本冲突，点击读取最新版本并核对差异，再明确采用新版本号继续编辑，不会自动覆盖服务器内容。\n离开页面前会确认保留输入。返回同一编辑表单可恢复；如果该草稿已经成为历史只读版本，可在本地设置的“未保存输入恢复”中查看并人工复制到新稿。\n网络中断时操作可能已写入数据库，先刷新检查记录，避免重复新建、上传或生成。')))));
}
