// 所有业务请求同源；写请求严格串行，不推算任何版本号。
export class ApiError extends Error {
  constructor(message, status = 0, code = 'NETWORK_ERROR') {
    super(message);
    this.status = status;
    this.code = code;
  }
}
let writeTail = Promise.resolve();
let activeWrites = 0;
export function isWriting() { return activeWrites > 0; }
function localURL(path) {
  const url = new URL(path, location.origin);
  if (url.origin !== location.origin || !url.pathname.startsWith('/api/')) {
    throw new ApiError('只允许访问本机同源 API', 400, 'LOCAL_URL_REQUIRED');
  }
  return url.pathname + url.search;
}
async function execute(path, {method = 'GET', body, signal, binary = false} = {}) {
  const headers = {Accept: binary ? 'application/octet-stream' : 'application/json'};
  let payload;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(localURL(path), {method, headers, body: payload, signal, credentials: 'same-origin', cache: 'no-store', redirect: 'error'});
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError(method === 'GET' ? '无法连接本地服务，请确认启动窗口仍在运行后重试。' : '连接中断，操作结果尚不确定。输入已保留，请先刷新并检查记录，避免重复提交。');
  }
  if (!response.ok) {
    let problem;
    try { problem = await response.json(); } catch { problem = {}; }
    throw new ApiError(problem.message || `本地请求失败（${response.status}），请重试或查看服务窗口。`, response.status, problem.code || 'REQUEST_FAILED');
  }
  if (binary) return response.blob();
  try { return await response.json(); }
  catch { throw new ApiError('接口未返回预期数据。请刷新并检查操作结果，不要重复提交。', 0, 'INVALID_RESPONSE'); }
}
export function api(path, options = {}) {
  if (!options.method || options.method === 'GET') return execute(path, options);
  activeWrites += 1;
  window.dispatchEvent(new CustomEvent('api-writing', {detail: activeWrites}));
  const next = writeTail.then(() => execute(path, options));
  writeTail = next.catch(() => {});
  return next.finally(() => {
    activeWrites -= 1;
    window.dispatchEvent(new CustomEvent('api-writing', {detail: activeWrites}));
  });
}
export function query(values = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== '' && value !== undefined && value !== null) params.set(key, String(value));
  return params.size ? '?' + params.toString() : '';
}
export async function download(url, name = 'download') {
  const blob = await api(url, {binary: true});
  const objectURL = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = objectURL;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectURL), 60000);
}
export function checkFile(file) {
  if (!file) throw new ApiError('请先选择文件。', 422, 'FILE_REQUIRED');
  if (!/\.(docx|pdf)$/i.test(file.name)) throw new ApiError('仅支持 DOCX 与文字 PDF；不支持 DOC、图片、宏或加密文件。', 415, 'UNSUPPORTED_FILE');
  if (file.size === 0) throw new ApiError('文件为空，请重新选择。', 422, 'EMPTY_FILE');
  if (file.size > 20 * 1024 * 1024) throw new ApiError('单个文件不能超过 20MB，请拆分后上传。', 413, 'FILE_TOO_LARGE');
}
export async function uploadShared(file) {
  checkFile(file);
  const body = new FormData();
  body.append('file', file);
  return (await api('/api/files', {method: 'POST', body})).item;
}
export class ProjectContext {
  constructor(id, detail, rerender) { this.id = id; this.data = detail; this.rerender = rerender; this.needsRefresh = false; }
  get project() { return this.data.item; }
  get base() { return '/api/projects/' + encodeURIComponent(this.id); }
  async refresh() {
    this.data = await api(this.base);
    this.needsRefresh = false;
    return this.data;
  }
  async write(suffix, method, body) {
    if (this.needsRefresh) throw new ApiError('上次写入后未能重读项目。请先读取最新版本并核对，当前输入仍保留。', 409, 'PROJECT_REFRESH_REQUIRED');
    const result = await api(this.base + suffix, {method, body});
    this.needsRefresh = true;
    if (result.project) this.data.item = result.project;
    else if (!suffix || suffix === '/selection' || suffix === '/archive') this.data.item = result.item;
    // 即使响应带项目，需求映射也可能改变章节版本，始终重读完整项目。
    try { await this.refresh(); }
    catch (error) {
      window.dispatchEvent(new CustomEvent('post-save-refresh-error', {detail: error.message}));
    }
    return result;
  }
}
