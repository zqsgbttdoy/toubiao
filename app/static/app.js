import {api, aiConfig, ProjectContext} from './api.js';
import {h, badge, button, linkButton, loading, errorPanel, guard, toast} from './ui.js';
import {dashboard, projectFrame} from './projects.js';
import {analysisPage} from './analysis.js';
import {draftingPage} from './drafting.js';
import {quotePage, reviewPage} from './commercial.js';
import {libraryPage} from './library.js';
import {settingsPage, helpPage} from './settings.js';

const main = document.querySelector('#main');
const menu = document.querySelector('#menu-toggle');
const shell = document.querySelector('.app-shell');
const connection = document.querySelector('#network-state');
const routes = [['dashboard', '项目工作台'], ['templates', '模板库'], ['materials', '企业资料'], ['snippets', '历史素材'], ['settings', '本地设置']];
const navigation = document.querySelector('#navigation');
const aiBoundary = document.querySelector('#ai-boundary');
// 侧标边界声明必须跟随真实 AI 配置，不得在已接入模型时继续声称“未接入”。
function renderAIBoundary(config) {
  if (!aiBoundary) return;
  aiBoundary.textContent = !config || !config.enabled || (config.provider || 'null') === 'null' ? '数据在本地 · 外部 AI 未接入'
    : config.is_cloud ? '云端 AI 已接入 · 逐次确认后发送' : '本地 AI 已接入 · 正文不出本机';
}
aiConfig().then(renderAIBoundary).catch(() => renderAIBoundary(null));
window.addEventListener('ai-config-changed', event => renderAIBoundary(event.detail));
navigation.append(...routes.map(([route, label], index) => h('a', {class: 'nav-link', href: '#' + route}, h('span', {class: 'nav-index', 'aria-hidden': 'true'}, String(index + 1).padStart(2, '0')), label)));
let currentHash = '';
let rendering = 0;
let navigationTail = Promise.resolve();
function closeMenu() { shell.classList.remove('menu-open'); menu.setAttribute('aria-expanded', 'false'); }
menu.addEventListener('click', () => { const open = shell.classList.toggle('menu-open'); menu.setAttribute('aria-expanded', String(open)); });
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !document.querySelector('dialog[open]')) closeMenu(); });
function markNavigation(key, name) {
  navigation.querySelectorAll('a').forEach(link => {
    const active = link.getAttribute('href') === '#' + (key === 'projects' ? 'dashboard' : key);
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
  });
  document.querySelector('#breadcrumb').textContent = name;
}
async function render(hash, options = {}) {
  const ticket = ++rendering;
  main.replaceChildren(loading());
  main.setAttribute('aria-busy', 'true');
  const parts = hash.replace(/^#/, '').split('/');
  const key = parts[0] || 'dashboard';
  let page;
  try {
    if (key === 'dashboard') { markNavigation(key, '项目工作台'); page = await dashboard(); }
    else if (['templates', 'materials', 'snippets'].includes(key)) { markNavigation(key, routes.find(row => row[0] === key)[1]); page = await libraryPage(key); }
    else if (key === 'settings') { markNavigation(key, '本地设置'); page = await settingsPage(); }
    else if (key === 'help') { markNavigation(key, '使用帮助'); page = await helpPage(); }
    else if (key === 'projects' && /^[a-zA-Z0-9_-]{1,100}$/.test(parts[1] || '')) {
      const id = parts[1];
      const stage = ['analysis', 'drafting', 'quote', 'review'].includes(parts[2]) ? parts[2] : 'analysis';
      const data = await api('/api/projects/' + id);
      const context = new ProjectContext(id, data, async settings => {
        if (currentHash !== hash) return;
        return navigate(hash, {refresh: true, section: settings?.section});
      });
      const frame = projectFrame(context, stage);
      const content = stage === 'analysis' ? analysisPage(context) : stage === 'drafting' ? await draftingPage(context, options.section || parts[3] || '') : stage === 'quote' ? await quotePage(context) : await reviewPage(context);
      frame.content.append(content);
      page = frame.node;
      markNavigation(key, '项目工作台 / ' + data.item.name);
    } else {
      markNavigation('dashboard', '页面未找到');
      page = h('div', {class: 'card card-body'}, h('h1', {}, '页面未找到'), h('p', {class: 'muted top-space'}, '请从主导航进入项目或资料库。'), h('div', {class: 'top-space'}, linkButton('返回工作台', '#dashboard', 'primary')));
    }
    if (ticket !== rendering) return;
    main.replaceChildren(page);
    connection.textContent = '本地服务已连接';
    document.title = (document.querySelector('#breadcrumb').textContent || '本地工作台') + ' · 标序';
  } catch (error) {
    if (ticket !== rendering) return;
    main.replaceChildren(h('div', {class: 'card card-body'}, h('h1', {}, '暂时无法读取工作台'), h('p', {class: 'small muted top-space bottom-space'}, '输入如有修改已保留在当前浏览器会话。请检查本地服务，再重试。'), errorPanel(error, () => navigate(hash, {refresh: true})), h('div', {class: 'top-space'}, linkButton('返回项目工作台', '#dashboard'))));
    connection.textContent = '读取失败 · 可重试';
  } finally {
    if (ticket === rendering) { main.removeAttribute('aria-busy'); if (!document.querySelector('dialog[open]')) main.focus({preventScroll: true}); }
  }
}
function navigate(target, options = {}) {
  const hash = target === '#' || !target ? '#dashboard' : target;
  const transition = async () => {
    if (hash === currentHash && !options.refresh) return;
    if (currentHash && !(await guard(document))) {
      if (location.hash !== currentHash) history.replaceState(null, '', currentHash);
      return;
    }
    if (hash !== currentHash) {
      // 所有表单已通过离开保护；只在切换路由时关闭旧对话框。
      document.querySelectorAll('dialog').forEach(dialog => { dialog.close(); dialog.remove(); });
    }
    if (location.hash !== hash) history.pushState(null, '', hash);
    currentHash = hash;
    closeMenu();
    await render(hash, options);
  };
  const next = navigationTail.then(transition);
  navigationTail = next.catch(error => toast('页面切换失败：' + error.message, 'error'));
  return next;
}
document.addEventListener('click', event => {
  const link = event.target.closest('a[href^="#"]');
  if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
  const target = link.getAttribute('href');
  if (target === '#main') { event.preventDefault(); main.focus(); return; }
  event.preventDefault(); navigate(target);
});
window.addEventListener('hashchange', () => navigate(location.hash));
window.addEventListener('popstate', () => navigate(location.hash));
window.addEventListener('request-refresh', () => navigate(currentHash || '#dashboard', {refresh: true}));
window.addEventListener('api-writing', event => {
  const busy = event.detail > 0;
  connection.classList.toggle('busy', busy);
  connection.textContent = busy ? '正在写入本地数据…' : '本地服务已连接';
});
window.addEventListener('unhandledrejection', event => {
  if (event.reason?.name === 'AbortError') return;
  toast('操作未完成：' + (event.reason?.message || '请刷新后重试，未保存文本将保留。'), 'error');
});
navigate(location.hash || '#dashboard');
