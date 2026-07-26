function navTo(page, el) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('on'));
  document.querySelectorAll('.s-nav').forEach(n => n.classList.remove('on'));
  document.querySelectorAll('.t-ni').forEach(n => n.classList.remove('on'));
  document.getElementById('page-' + page)?.classList.add('on');
  if (el) el.classList.add('on');
  // page-specific load
  if (page === 'content') loadContent();
  if (page === 'quality') loadQualityGateArticles();
  if (page === 'publish') loadPublishPage();
  if (page === 'resources') loadResourcePage();
  if (page === 'daily') loadDailyPage();
  if (page === 'records') loadRecordsLibraryViews();
  if (page === 'reference') loadReferenceIntelligence();
  if (page === 'materials') loadMaterialAnalysis();
  if (page === 'competitors') loadCompetitorAnalysis();
  if (page === 'clients') loadClients();
  if (page === 'settings') loadSettings();
}
// ── State ─────────────────────────────────────────────
let currentClientId = '';
let distributionFavorites = [];
let distributionFavoriteMatchJob = {status: 'idle'};
let distributionFavoriteMatchTimer = null;

async function loadPublishPage() {
  const el = document.getElementById('publishDraftList');
  if (!currentClientId) { el.textContent = '请选择客户后查看发布草稿'; return; }
  const clientId = encodeURIComponent(currentClientId);
  const [r, resources, orderResult] = await Promise.all([
    api('/api/distribution/drafts?client_id=' + clientId),
    api('/api/distribution/resources?client_id=' + clientId),
    api('/api/distribution/orders?client_id=' + clientId),
  ]);
  const resourceLabel = x => x.resource_type === 'news_media' ? '新闻媒体' : '自媒体';
  const options = (resources.resources || []).filter(x => String(x.status) === '1').map(x => `<option value="${escHtml(JSON.stringify({resource_id: x.resource_id, resource_type: x.resource_type || 'self_media'}))}">${escHtml(resourceLabel(x))} · ${escHtml(x.name)} · ¥${escHtml(x.price)}</option>`).join('');
  const orderByDraft = new Map((orderResult.orders || []).map(order => [String(order.draft_id), order]));
  const preview = d => `<a class="btn btn-o btn-sm" target="_blank" href="/public/publications/${escHtml(d.preview_token)}">查看预览</a>`;
  const orderState = order => {
    if (order.status === 'published') {
      const publishedLink = order.provider_url ? `<a class="btn btn-o btn-sm" target="_blank" href="${escHtml(order.provider_url)}">查看发布页</a>` : '';
      return `<span style="font-size:12px;font-weight:700;color:var(--green)">已发布</span>${publishedLink}`;
    }
    if (order.status === 'rejected') {
      return `<span style="font-size:12px;font-weight:700;color:var(--red)">供应商已驳回</span>`;
    }
    if (order.status === 'submit_unknown') {
      return `<span style="font-size:12px;font-weight:700;color:var(--amber)">提交状态待确认，请勿重复下单</span>`;
    }
    return `<span style="font-size:12px;font-weight:700;color:var(--amber)">订单已提交，等待供应商处理</span>`;
  };
  const actions = d => {
    const order = orderByDraft.get(String(d.id));
    if (order) {
      const refresh = `<button class="btn btn-o btn-sm" onclick="refreshDistributionOrder('${escHtml(order.id)}')">刷新供应商状态</button>`;
      return `${preview(d)}${orderState(order)}${refresh}`;
    }
    return `${preview(d)}<select id="publish-resource-${escHtml(d.id)}"><option value="">选择发布资源</option>${options}</select><button class="btn btn-p btn-sm" onclick="submitDistributionOrder('${escHtml(d.id)}')">确认下单</button>`;
  };
  el.innerHTML = r.error ? escHtml(r.error) : (r.drafts || []).map(d => `<div class="article-card"><div class="article-title">${escHtml(d.article_title)}</div><div class="article-meta">门禁：${escHtml(d.gate_verdict || '未审核')} · ${escHtml(d.status)}</div><div class="article-acts">${actions(d)}</div></div>`).join('') || '暂无发布草稿';
}

async function submitDistributionOrder(draftId) {
  const selected = document.getElementById('publish-resource-' + draftId)?.value;
  if (!selected) { toast('请选择资源', 'err'); return; }
  const resource = JSON.parse(selected);
  if (!confirm('将向供应商创建真实发稿订单，可能扣费。确认提交？')) return;
  const r = await api('/api/distribution/orders', 'POST', {client_id: currentClientId, draft_id: draftId, resource_id: resource.resource_id, resource_type: resource.resource_type});
  if (r.error) { toast(r.error, 'err'); return; }
  toast(r.order?.status === 'submit_unknown' ? '状态未知，请勿重复提交' : '订单已提交');
  loadPublishPage();
}

async function refreshDistributionOrder(orderId) {
  if (!currentClientId) { toast('请先选择客户', 'err'); return; }
  const r = await api('/api/distribution/orders/' + encodeURIComponent(orderId) + '/refresh', 'POST', {client_id: currentClientId});
  if (r.error) {
    toast(r.message || r.error, 'err');
    return;
  }
  toast(r.order?.status === 'published' ? '供应商已确认发布' : '供应商状态已刷新');
  loadPublishPage();
}

async function uploadPublicationFiles(files) {
  if (!currentClientId) { toast('请先选择客户', 'err'); return; }
  const accepted = Array.from(files || []).filter(file => /\.(txt|md|docx)$/i.test(file.name));
  if (!accepted.length) { toast('请选择 txt、md 或 docx 文章', 'err'); return; }
  const form = new FormData();
  form.append('client_id', currentClientId);
  accepted.forEach(file => form.append('files', file, file.name));
  const response = await fetch('/api/distribution/drafts/upload', {method: 'POST', body: form});
  const result = await response.json();
  if (!response.ok || result.error) { toast(result.error || '上传失败', 'err'); return; }
  const rejected = result.rejected || [];
  toast(rejected.length ? `已创建 ${result.drafts.length} 篇草稿，${rejected.length} 个文件未导入` : `已创建 ${result.drafts.length} 篇发布草稿`);
  loadPublishPage();
}

function uploadPublicationInput(input) {
  uploadPublicationFiles(input.files);
  input.value = '';
}

function handlePublicationDrop(event) {
  event.preventDefault();
  uploadPublicationFiles(event.dataTransfer?.files);
}

async function loadResourcePage() {
  const el = document.getElementById('resourceList');
  loadDistributionCredentials();
  loadDistributionFavorites();
  loadDistributionFavoriteMatchStatus();
  if (!currentClientId) { el.textContent = '请选择客户后查看资源'; return; }
  const r = await api('/api/distribution/resources?client_id=' + encodeURIComponent(currentClientId));
  el.innerHTML = r.error ? escHtml(r.error) : (r.resources || []).map(x => `<div class="article-card"><div class="article-title">${escHtml(x.name)}</div><div class="article-meta">${escHtml(x.resource_type === 'news_media' ? '新闻媒体' : '自媒体')} · ID ${escHtml(x.resource_id)} · ¥${escHtml(x.price)} · ${escHtml(distributionResourceStatusLabel(x.status))}</div></div>`).join('') || '暂无已同步资源';
}

async function loadDistributionCredentials() {
  const status = document.getElementById('distributionCredentialStatus');
  if (!status) return;
  const r = await api('/api/distribution/credentials');
  if (r.error) { status.textContent = r.error; return; }
  status.textContent = r.configured ? '已配置你的 RWMeiti 凭据' : '尚未配置；配置后才能匹配和同步供应商资源';
  const placeholder = r.configured ? '已配置，留空不修改' : '填写 secret_id';
  document.getElementById('distributionSecretId').placeholder = placeholder;
  document.getElementById('distributionSecretKey').placeholder = r.configured ? '已配置，留空不修改' : '填写 secret_key';
}

async function saveDistributionCredentials() {
  const secret_id = document.getElementById('distributionSecretId')?.value.trim() || '';
  const secret_key = document.getElementById('distributionSecretKey')?.value.trim() || '';
  if (!secret_id && !secret_key) { toast('请填写 secret_id 和 secret_key', 'err'); return; }
  const r = await api('/api/distribution/credentials', 'POST', {secret_id, secret_key});
  if (r.error) { toast(r.error, 'err'); return; }
  document.getElementById('distributionSecretId').value = '';
  document.getElementById('distributionSecretKey').value = '';
  toast('分发凭据已保存');
  loadDistributionCredentials();
}

async function loadDistributionFavorites() {
  const el = document.getElementById('distributionFavoriteList');
  if (!el) return;
  const r = await api('/api/distribution/favorites');
  if (r.error) { el.textContent = r.error; return; }
  distributionFavorites = r.favorites || [];
  el.innerHTML = distributionFavorites.map(x => {
    const candidates = x.candidates || [];
    const candidateHtml = candidates.length ? candidates.map(c => `<div style="margin:4px 0 0 180px;color:var(--text2)">候选：${escHtml(c.name)} · ${escHtml(c.resource_type === 'news_media' ? '新闻媒体' : '自媒体')} · ID ${escHtml(c.resource_id)} · ¥${escHtml(c.price)} · ${escHtml(distributionResourceStatusLabel(c.status))} <button class="btn btn-o btn-sm" onclick="syncDistributionResource('${escHtml(c.resource_id)}','${escHtml(c.resource_type)}')">同步此资源</button></div>`).join('') : (distributionFavoriteMatchJob.status === 'completed' ? '<div style="margin:4px 0 0 180px">未匹配</div>' : '');
    return `<div style="margin-top:6px"><div class="article-acts"><span style="min-width:180px;font-weight:700">${escHtml(x.name)}</span><input id="favorite-resource-${escHtml(x.id)}" value="${escHtml(x.resource_id || '')}" placeholder="供应商资源 ID" style="min-width:200px"><button class="btn btn-o btn-sm" onclick="saveDistributionFavorite('${escHtml(x.id)}')">保存 ID</button><button class="btn btn-danger btn-sm" onclick="deleteDistributionFavorite('${escHtml(x.id)}')">移除</button></div>${candidateHtml}</div>`;
  }).join('') || '暂无常用资源，请先添加。';
}

async function startDistributionFavoriteMatch() {
  const r = await api('/api/distribution/favorites/match', 'POST', {});
  if (r.error) { toast(r.error, 'err'); return; }
  distributionFavoriteMatchJob = r.job || {status: 'running'};
  toast('已开始只读匹配');
  loadDistributionFavoriteMatchStatus();
}

async function loadDistributionFavoriteMatchStatus() {
  const el = document.getElementById('distributionFavoriteMatchStatus');
  if (!el) return;
  const r = await api('/api/distribution/favorites/match');
  if (r.error) { el.textContent = r.error; return; }
  const previousStatus = distributionFavoriteMatchJob.status;
  distributionFavoriteMatchJob = r.job || {status: 'idle'};
  const job = distributionFavoriteMatchJob;
  el.textContent = job.status === 'running' ? `匹配中：已扫描 ${job.scanned || 0} 条` : job.status === 'completed' ? `匹配完成：扫描 ${job.scanned || 0} 条，命中 ${job.matched || 0} 个名单项` : job.status === 'failed' ? `匹配失败：${job.error || '供应商读取失败'}` : '';
  clearTimeout(distributionFavoriteMatchTimer);
  if (job.status === 'running') distributionFavoriteMatchTimer = setTimeout(loadDistributionFavoriteMatchStatus, 2000);
  if (previousStatus === 'running' && job.status !== 'running') loadDistributionFavorites();
}

async function addDistributionFavorite() {
  const name = document.getElementById('distributionFavoriteName')?.value.trim();
  const resourceId = document.getElementById('distributionFavoriteResourceId')?.value.trim();
  if (!name) { toast('请输入媒体名称', 'err'); return; }
  const r = await api('/api/distribution/favorites', 'POST', {name, resource_id: resourceId});
  if (r.error) { toast(r.error, 'err'); return; }
  document.getElementById('distributionFavoriteName').value = '';
  document.getElementById('distributionFavoriteResourceId').value = '';
  toast('已加入常用名单');
  loadDistributionFavorites();
}

async function saveDistributionFavorite(favoriteId) {
  const resourceId = document.getElementById('favorite-resource-' + favoriteId)?.value.trim();
  const r = await api('/api/distribution/favorites', 'POST', {id: favoriteId, resource_id: resourceId});
  if (r.error) { toast(r.error, 'err'); return; }
  toast('已保存资源 ID');
  loadDistributionFavorites();
}

async function deleteDistributionFavorite(favoriteId) {
  if (!confirm('从你的常用名单中移除此资源？')) return;
  const r = await api('/api/distribution/favorites/' + encodeURIComponent(favoriteId), 'DELETE');
  if (r.error) { toast(r.error, 'err'); return; }
  toast('已移除');
  loadDistributionFavorites();
}

function syncFavoriteDistributionResources() {
  const resourceIds = distributionFavorites.map(x => x.resource_id).filter(Boolean);
  if (!resourceIds.length) { toast('请先为常用名单填写供应商资源 ID', 'err'); return; }
  document.getElementById('distributionResourceIds').value = resourceIds.join(',');
  syncDistributionResources();
}

async function syncDistributionResources() {
  if (!currentClientId) { toast('请先选择客户', 'err'); return; }
  const resourceIds = (document.getElementById('distributionResourceIds')?.value || '').split(/[,，\s]+/).filter(Boolean);
  if (!resourceIds.length) { toast('请输入至少一个常用资源 ID', 'err'); return; }
  const resourceType = document.getElementById('distributionResourceType')?.value || 'self_media';
  const r = await api('/api/distribution/resources/sync', 'POST', {client_id: currentClientId, resources: resourceIds.map(resource_id => ({resource_id, resource_type: resourceType}))});
  if (r.error) { toast(r.error, 'err'); return; }
  toast('已同步 ' + r.count + ' 个资源');
  loadResourcePage();
}

async function syncDistributionResource(resource_id, resource_type) {
  if (!currentClientId) { toast('请先选择客户', 'err'); return; }
  const r = await api('/api/distribution/resources/sync', 'POST', {client_id: currentClientId, resources: [{resource_id, resource_type}]});
  if (r.error) { toast(r.error, 'err'); return; }
  toast('已同步 ' + r.count + ' 个资源');
  loadResourcePage();
}

// Local catalog flow replaces the legacy manual-ID controls above.
async function loadResourcePage() {
  const el = document.getElementById('resourceList');
  loadDistributionCredentials();
  loadDistributionFavorites();
  loadDistributionCatalogStatus();
  searchDistributionCatalog();
  if (!currentClientId) { el.textContent = '请选择客户后查看可发布平台'; return; }
  const r = await api('/api/distribution/resources?client_id=' + encodeURIComponent(currentClientId));
  el.innerHTML = r.error ? escHtml(r.error) : (r.resources || []).map(x => `<div class="article-card"><div class="article-title">${escHtml(x.name || '未关联资源')}</div><div class="article-meta">${escHtml(distributionResourceTypeLabel(x.resource_type))} · ID ${escHtml(x.resource_id)} · ¥${escHtml(x.price)} · ${escHtml(distributionResourceStatusLabel(x.status))}</div></div>`).join('') || '暂无常用发布平台';
}

function distributionResourceTypeLabel(resourceType) {
  return resourceType === 'news_media' ? '新闻媒体' : '自媒体';
}

function distributionResourceStatusLabel(status) {
  if (String(status) === '1') return '可发布';
  if (status === undefined || status === null || String(status) === '') return '状态未知';
  return '暂不可发布';
}

async function loadDistributionFavorites() {
  const el = document.getElementById('distributionFavoriteList');
  if (!el) return;
  const r = await api('/api/distribution/favorites');
  if (r.error) { el.textContent = r.error; return; }
  distributionFavorites = r.favorites || [];
  el.innerHTML = distributionFavorites.map(x => `<div style="margin-top:6px"><div class="article-acts"><span style="min-width:180px;font-weight:700">${escHtml(x.name || '未关联资源')}</span><span style="color:var(--text2)">${escHtml(distributionResourceTypeLabel(x.resource_type))} · ID ${escHtml(x.resource_id)} · ¥${escHtml(x.price)} · ${escHtml(distributionResourceStatusLabel(x.status))}</span><button class="btn btn-danger btn-sm" onclick="deleteDistributionFavorite('${escHtml(x.id)}')">移除</button></div>${x.name ? '' : '<div style="margin:4px 0 0;color:var(--text3)">旧名单尚未关联资源，请在资源库中搜索后重新加入。</div>'}</div>`).join('') || '暂无常用平台，请先从资源库搜索添加。';
}

async function loadDistributionCatalogStatus() {
  const el = document.getElementById('distributionCatalogStatus');
  if (!el) return;
  const r = await api('/api/distribution/catalog/sync');
  if (r.error) { el.textContent = r.error; return; }
  const job = r.job || {status: 'idle'};
  el.textContent = job.status === 'running' ? `同步中：已读取 ${job.scanned || 0} 条资源` : job.status === 'completed' ? `已同步 ${job.count || 0} 条资源（${job.finished_at || ''}）` : job.status === 'failed' ? `同步失败：${job.error || '供应商读取失败'}` : '尚未同步资源库';
  clearTimeout(distributionFavoriteMatchTimer);
  if (job.status === 'running') distributionFavoriteMatchTimer = setTimeout(loadDistributionCatalogStatus, 2000);
  if (job.status === 'completed') searchDistributionCatalog();
}

async function startDistributionCatalogSync() {
  const r = await api('/api/distribution/catalog/sync', 'POST', {});
  if (r.error) { toast(r.error, 'err'); return; }
  toast('已开始完整同步资源库');
  loadDistributionCatalogStatus();
}

async function searchDistributionCatalog() {
  const el = document.getElementById('distributionCatalogResults');
  const query = document.getElementById('distributionCatalogSearch')?.value.trim() || '';
  if (!el) return;
  if (!query) { el.textContent = '请先输入名称搜索。'; return; }
  const r = await api('/api/distribution/catalog?query=' + encodeURIComponent(query));
  if (r.error) { el.textContent = r.error; return; }
  el.innerHTML = (r.resources || []).map(x => `<div style="margin-top:6px" class="article-acts"><span style="min-width:180px;font-weight:700">${escHtml(x.name)}</span><span style="color:var(--text2)">${escHtml(distributionResourceTypeLabel(x.resource_type))} · ID ${escHtml(x.resource_id)} · ¥${escHtml(x.price)} · ${escHtml(distributionResourceStatusLabel(x.status))}</span><button class="btn btn-o btn-sm" onclick="addDistributionFavorite('${escHtml(x.resource_id)}','${escHtml(x.resource_type)}')">加入常用平台</button></div>`).join('') || '本地资源库中未找到该名称；如确认是新资源，请完整同步资源库后再试。';
}

async function addDistributionFavorite(resource_id, resource_type) {
  const r = await api('/api/distribution/favorites', 'POST', {resource_id, resource_type});
  if (r.error) { toast(r.error, 'err'); return; }
  toast('已加入常用发布平台');
  loadDistributionFavorites();
  if (currentClientId) loadResourcePage();
}

async function refreshDistributionFavorites() {
  const r = await api('/api/distribution/favorites/refresh', 'POST', {});
  if (r.error) { toast(r.error, 'err'); return; }
  toast(r.failed?.length ? `已更新 ${r.count} 个平台，${r.failed.length} 个失败` : `已更新 ${r.count} 个常用平台`);
  loadDistributionFavorites();
  if (currentClientId) loadResourcePage();
}

// Resource management no longer renders a client-scoped duplicate platform list.
async function loadResourcePage() {
  loadDistributionCredentials();
  loadDistributionFavorites();
  loadDistributionCatalogStatus();
  searchDistributionCatalog();
}

async function createDistributionDraft(articleId) {
  if (!currentClientId) { toast('请先选择客户', 'err'); return; }
  const r = await api('/api/distribution/drafts', 'POST', {client_id: currentClientId, article_id: articleId});
  if (r.error) { toast(r.error, 'err'); return; }
  toast('已创建发布草稿');
  navTo('publish', document.querySelector("[onclick=\"navTo('publish',this)\"]"));
}
let currentBrand = '';
let currentClientName = '';
let currentIndustry = '';
let currentGoal = '';
let currentPlatform = 'all';  // 数据页固定汇总全部平台
let currentClientPlatforms = [];
let groupPlatformMode = 'contract';
const CRAWL_PLATFORM_NAMES = {all:'全部平台', doubao:'豆包', deepseek:'DeepSeek', yuanbao:'元宝', qwen:'千问', kimi:'Kimi'};
const CRAWL_PLATFORM_ORDER = ['deepseek', 'yuanbao', 'qwen', 'kimi', 'doubao'];

function sortCrawlPlatforms(platforms) {
  const rank = new Map(CRAWL_PLATFORM_ORDER.map((id, index) => [id, index]));
  return [...platforms].sort((a, b) => {
    const aRank = rank.has(a.id) ? rank.get(a.id) : CRAWL_PLATFORM_ORDER.length;
    const bRank = rank.has(b.id) ? rank.get(b.id) : CRAWL_PLATFORM_ORDER.length;
    return aRank - bRank;
  });
}

function normalizeContractPlatforms(platforms) {
  const allowed = new Set(CRAWL_PLATFORM_ORDER);
  const selected = Array.isArray(platforms) ? platforms.filter(p => allowed.has(p)) : [];
  return sortCrawlPlatforms(selected.map(id => ({id, name: CRAWL_PLATFORM_NAMES[id] || id}))).map(p => p.id);
}

function platformCheckboxHtml(id, checked=false, prefix='platform') {
  const label = CRAWL_PLATFORM_NAMES[id] || id;
  return `<label style="display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:800;color:var(--text2);padding:5px 9px;border:1.5px solid var(--border);border-radius:999px;background:white">
    <input type="checkbox" data-platform-choice="${prefix}" value="${escHtml(id)}" ${checked ? 'checked' : ''} style="width:auto">
    ${escHtml(label)}
  </label>`;
}

function getCheckedPlatformIds(prefix) {
  return [...document.querySelectorAll(`input[data-platform-choice="${prefix}"]:checked`)].map(el => el.value);
}

function renderContractPlatformChoices(containerId, selectedIds, prefix) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const selected = new Set(normalizeContractPlatforms(selectedIds));
  el.innerHTML = CRAWL_PLATFORM_ORDER.map(id => platformCheckboxHtml(id, selected.has(id), prefix)).join('');
}

function renderGroupPlatformChoices() {
  const el = document.getElementById('grpPlatformChoices');
  if (!el) return;
  const platforms = groupPlatformMode === 'custom'
    ? CRAWL_PLATFORM_ORDER
    : normalizeContractPlatforms(currentClientPlatforms);
  const contractBtn = document.getElementById('grpPlatformModeContract');
  const customBtn = document.getElementById('grpPlatformModeCustom');
  if (contractBtn && customBtn) {
    contractBtn.className = groupPlatformMode === 'contract' ? 'btn btn-p btn-sm' : 'btn btn-o btn-sm';
    customBtn.className = groupPlatformMode === 'custom' ? 'btn btn-p btn-sm' : 'btn btn-o btn-sm';
  }
  if (!platforms.length) {
    el.innerHTML = '<span style="font-size:11px;color:var(--red);font-weight:800">请先在客户管理配置合同平台</span>';
    return;
  }
  el.innerHTML = platforms.map(id => platformCheckboxHtml(id, true, 'group-crawl')).join('');
}

function setGroupPlatformMode(mode) {
  groupPlatformMode = mode === 'custom' ? 'custom' : 'contract';
  renderGroupPlatformChoices();
}

function getSelectedGroupCrawlPlatformIds() {
  return normalizeContractPlatforms(getCheckedPlatformIds('group-crawl'));
}

function toast(msg, type='ok') {
  const el = document.getElementById('toast');
  el.textContent = msg; el.className = 'show ' + type;
  setTimeout(() => el.className = '', 2800);
}
async function api(url, method='GET', body=null) {
  const opts = {method, headers:{'Content-Type':'application/json'}};
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  try { return await res.json(); }
  catch { return {error: '服务器错误'}; }
}
function spin(id, on) {
  const el = document.getElementById(id);
  if (el) el.style.display = on ? 'inline-block' : 'none';
}
function disableBtn(id, on) {
  const el = document.getElementById(id);
  if (el) el.disabled = on;
}
function escHtml(v) {
  return String(v ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}
function normalizeClipboardText(text) {
  return String(text ?? '').replace(/\u0000/g, '').replace(/\r\n?/g, '\n');
}
function fallbackCopyText(text, successMessage) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  ta.style.top = '0';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  ta.setSelectionRange(0, ta.value.length);
  try {
    const ok = document.execCommand('copy');
    if (!ok) throw new Error('copy rejected');
    toast(successMessage);
    return true;
  } catch(e) {
    toast('复制失败，请手动选中复制', 'err');
    return false;
  } finally {
    document.body.removeChild(ta);
  }
}
async function copyTextToClipboard(text, successMessage='已复制 ✦') {
  const value = normalizeClipboardText(text);
  if (!value) { toast('暂无可复制内容', 'err'); return false; }
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      toast(successMessage);
      return true;
    }
  } catch(e) {}
  return fallbackCopyText(value, successMessage);
}

// ── Navigation ────────────────────────────────────────

// ── Client ────────────────────────────────────────────
async function loadClientsDropdown() {
  const clients = await api('/api/clients');
  const sel = document.getElementById('globalClient');
  const cur = sel.value;
  sel.innerHTML = '<option value="">— 选择客户 —</option>';
  clients.forEach(c => {
    const o = document.createElement('option');
    o.value = c.id; o.textContent = c.brand + ' · ' + c.name;
    o.dataset.brand = c.brand; o.dataset.name = c.name;
    o.dataset.industry = c.industry || '';
    o.dataset.goal = c.goal || '';
    o.dataset.platforms = JSON.stringify(c.contract_platforms || []);
    if (c.id === cur) o.selected = true;
    sel.appendChild(o);
  });
}
function onClientChange() {
  const sel = document.getElementById('globalClient');
  const opt = sel.options[sel.selectedIndex];
  currentClientId = sel.value;
  currentBrand = opt?.dataset?.brand || '';
  currentClientName = opt?.dataset?.name || '';
  currentIndustry = opt?.dataset?.industry || '';
  currentGoal = opt?.dataset?.goal || '';
  try { currentClientPlatforms = normalizeContractPlatforms(JSON.parse(opt?.dataset?.platforms || '[]')); }
  catch { currentClientPlatforms = []; }
  clearActiveGroupSelection();
  renderGroupPlatformChoices();
  resetDailyTaskFilter();
  loadGroups();
  loadDailyGroupFilter();  // 切换客户时刷新问题组筛选器
  // 如果当前在当日整理页面，自动刷新数据+模板
  if (document.getElementById('page-daily')?.classList.contains('on')) {
    loadDailyPage();
  }
  if (document.getElementById('page-records')?.classList.contains('on')) {
    loadRecordsLibraryViews();
  }
  if (document.getElementById('page-content')?.classList.contains('on')) loadContent();
  if (document.getElementById('page-materials')?.classList.contains('on')) loadMaterialAnalysis();
  if (document.getElementById('page-competitors')?.classList.contains('on')) loadCompetitorAnalysis();
  if (document.getElementById('page-reference')?.classList.contains('on')) {
    loadReferenceIntelligence();
  }
  // 全局刷新模板提示条（当日整理顶部）和内容生产模板列表
  loadTemplatesForContent();
  loadMaterials();
}
const clientContentOptions = {};
async function loadClients() {
  const clients = await api('/api/clients');
  const el = document.getElementById('clientList');
  renderContractPlatformChoices('cl-platforms', ['deepseek'], 'new-client');
  if (!clients.length) { el.innerHTML = '<div class="empty"><i class="ti ti-users"></i><p>暂无客户</p></div>'; return; }
  el.innerHTML = clients.map(c => `
    <div style="display:flex;align-items:center;gap:12px;padding:12px;background:rgba(255,255,255,.7);border-radius:var(--r-sm);margin-bottom:8px;border:1.5px solid var(--border2)">
      <div style="width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,#818cf8,#c084fc);display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:900;color:white;flex-shrink:0">${c.brand[0]}</div>
      <div style="flex:1">
        <div style="font-size:13px;font-weight:800;color:#312e81">${c.brand}</div>
        <div style="font-size:11px;color:var(--text2)">${c.name} · ${c.industry}</div>
        <div style="font-size:10px;color:var(--text3);margin-top:2px">目标：${c.goal || '未设定'}</div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:8px">
          <span style="font-size:10px;color:var(--text3);font-weight:800">合同平台</span>
          ${CRAWL_PLATFORM_ORDER.map(id => platformCheckboxHtml(id, (c.contract_platforms || []).includes(id), `client-${c.id}`)).join('')}
          <button class="btn btn-o btn-sm" onclick="saveClientPlatforms('${c.id}')">保存平台</button>
        </div>
        <div id="client-content-options-${c.id}" style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border2);font-size:11px;color:var(--text3)">加载内容选择项…</div>
      </div>
      <span class="badge badge-p">${c.created}</span>
      <button class="btn btn-danger" onclick="delClient('${c.id}')">删除</button>
    </div>`).join('');
  document.querySelectorAll('[id^="client-content-options-"]').forEach(el => el.remove());
}
async function loadClientContentOptions(id) {
  const el = document.getElementById('content-choice-options');
  if (!id) {
    if (el) el.textContent = '请选择客户后配置人群角度、FAQ 与竞品规则';
    return;
  }
  const data = await api('/api/clients/' + encodeURIComponent(id) + '/content-options');
  if (data.error) return;
  clientContentOptions[id] = data;
  renderClientContentOptions(id);
}
function renderClientContentOptions(id) {
  const data = clientContentOptions[id];
  const el = document.getElementById('content-choice-options');
  if (!data || !el) return;
  const choices = (field, label) => {
    const items = data[field] || [];
    const rows = items.map((item, index) => `<div style="display:flex;align-items:center;gap:6px;margin:4px 0"><button class="btn btn-o btn-sm" onclick="toggleClientChoice('${id}','${field}',${index})">${item.enabled ? '停用' : '启用'}</button><span style="flex:1;${item.enabled ? '' : 'opacity:.45;text-decoration:line-through'}">${escHtml(item.text)}</span>${item.source === 'ai' ? '<span class="badge badge-p">AI</span>' : ''}<button class="btn btn-danger btn-sm" onclick="deleteClientChoice('${id}','${field}',${index})">删除</button></div>`).join('') || '<span style="color:var(--text3)">暂无，首次生成会自动补齐</span>';
    return `<div style="margin-top:8px"><b>${label}</b>${rows}<div style="display:flex;gap:6px;margin-top:4px"><input id="choice-new-${id}-${field}" placeholder="手动新增" style="max-width:240px;padding:5px 7px"><button class="btn btn-o btn-sm" onclick="addClientChoice('${id}','${field}')">添加</button></div></div>`;
  };
  const rules = data.competitor_rules || {must_use:[], banned:[]};
  const candidateRows = (data.competitor_candidates || []).map(name => {
    const state = rules.must_use.includes(name) ? 'must' : rules.banned.includes(name) ? 'banned' : 'random';
    return `<div style="display:flex;align-items:center;gap:8px;margin:4px 0"><span style="flex:1">${escHtml(name)}</span><select onchange="setClientCompetitorRule('${id}',decodeURIComponent('${encodeURIComponent(name)}'),this.value)" style="width:auto;padding:4px"><option value="random" ${state === 'random' ? 'selected' : ''}>随机池</option><option value="must" ${state === 'must' ? 'selected' : ''}>必须用</option><option value="banned" ${state === 'banned' ? 'selected' : ''}>禁止用</option></select></div>`;
  }).join('') || '<span style="color:var(--text3)">暂无竞品 Markdown 标题</span>';
  el.innerHTML = `<div style="font-weight:800;color:var(--text2)">内容生产选择项</div>${choices('audience_angles','人群角度')}${choices('faq_questions','FAQ 问题')}<div style="margin-top:8px"><b>竞品规则</b>${candidateRows}</div>`;
}
async function saveClientContentOptionField(id, field) {
  const data = clientContentOptions[id];
  const result = await api('/api/clients/' + encodeURIComponent(id), 'PUT', {[field]: data[field]});
  if (result.error) { toast(result.error, 'err'); return; }
  clientContentOptions[id][field] = result.client[field] || [];
  renderClientContentOptions(id);
}
async function toggleClientChoice(id, field, index) {
  const item = clientContentOptions[id]?.[field]?.[index];
  if (!item) return;
  item.enabled = !item.enabled;
  await saveClientContentOptionField(id, field);
}
async function deleteClientChoice(id, field, index) {
  if (!clientContentOptions[id]) return;
  clientContentOptions[id][field].splice(index, 1);
  await saveClientContentOptionField(id, field);
}
async function addClientChoice(id, field) {
  const input = document.getElementById(`choice-new-${id}-${field}`);
  const text = input?.value.trim();
  if (!text) return;
  const items = clientContentOptions[id][field];
  if (!items.some(item => item.text === text)) items.push({text, enabled:true, source:'manual'});
  await saveClientContentOptionField(id, field);
}
async function setClientCompetitorRule(id, name, state) {
  const data = clientContentOptions[id];
  if (!data) return;
  const rules = data.competitor_rules || {must_use:[], banned:[]};
  rules.must_use = rules.must_use.filter(item => item !== name);
  rules.banned = rules.banned.filter(item => item !== name);
  if (state === 'must') rules.must_use.push(name);
  if (state === 'banned') rules.banned.push(name);
  const result = await api('/api/clients/' + encodeURIComponent(id), 'PUT', {competitor_rules:rules});
  if (result.error) { toast(result.error, 'err'); return; }
  data.competitor_rules = result.client.competitor_rules || rules;
  renderClientContentOptions(id);
}
async function addClient() {
  const name = document.getElementById('cl-name').value.trim();
  const brand = document.getElementById('cl-brand').value.trim();
  if (!name || !brand) { toast('请填写客户名和品牌名', 'err'); return; }
  const contract_platforms = normalizeContractPlatforms(getCheckedPlatformIds('new-client'));
  if (!contract_platforms.length) { toast('请至少选择一个合同平台', 'err'); return; }
  await api('/api/clients','POST',{
    name, brand,
    industry: document.getElementById('cl-industry').value,
    goal: document.getElementById('cl-goal').value,
    contract_platforms
  });
  toast('客户已添加 ✦');
  ['cl-name','cl-brand','cl-industry','cl-goal'].forEach(id => document.getElementById(id).value = '');
  loadClients(); loadClientsDropdown();
}
async function saveClientPlatforms(id) {
  const contract_platforms = normalizeContractPlatforms(getCheckedPlatformIds(`client-${id}`));
  if (!contract_platforms.length) { toast('请至少选择一个合同平台', 'err'); return; }
  await api('/api/clients/'+id, 'PUT', {contract_platforms});
  toast('合同平台已保存');
  await loadClientsDropdown();
  if (id === currentClientId) {
    currentClientPlatforms = contract_platforms;
    renderGroupPlatformChoices();
  }
  loadClients();
}
async function delClient(id) {
  if (!confirm('确认删除？')) return;
  await api('/api/clients/'+id,'DELETE');
  toast('已删除'); loadClients(); loadClientsDropdown();
}

// ── 平台重新登录 ──────────────────────────────────────
async function platformLogin(platform) {
  const names = {doubao:'豆包', deepseek:'DeepSeek', yuanbao:'元宝', qwen:'千问', kimi:'Kimi'};
  const pName = platform.charAt(0).toUpperCase() + platform.slice(1);
  const btnId = `btnLogin${pName}`;
  const btn = document.getElementById(btnId);
  if (btn) { btn.disabled = true; btn.textContent = '通知中…'; }
  try {
    await api('/api/crawl_jobs/login', 'POST', { platform });
    toast(`${names[platform]} 补登录任务已创建，请保持本地 worker 运行`);
    if (btn) {
      btn.disabled = false;
      btn.textContent = `已通知${names[platform]}`;
    }
  } catch(e) {
    toast('创建补登录任务失败：' + e.message, 'err');
    if (btn) { btn.disabled = false; btn.textContent = names[platform]; }
  }
}
function doubaoLogin() { platformLogin('doubao'); }

// ── Content ───────────────────────────────────────────
async function loadContent() {
  ensureContentHistoryDate();
  loadContentMaterials();
  loadClientContentOptions(currentClientId);
  loadContentGenerations();
}

function ensureContentHistoryDate() {
  const el = document.getElementById('contentHistoryDate');
  if (el && !el.value) el.value = getLocalDateString();
}

function getContentHistoryDate() {
  ensureContentHistoryDate();
  return document.getElementById('contentHistoryDate')?.value || getLocalDateString();
}

function getLocalDateString() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

async function loadContentMaterials() {
  const el = document.getElementById('contentMaterialList');
  if (!el) return;
  if (!currentClientId) {
    el.innerHTML = '<div style="font-size:11px;color:var(--text3)">请先选择客户</div>';
    return;
  }
  const files = await api('/api/content/materials/' + currentClientId);
  if (!Array.isArray(files) || !files.length) {
    el.innerHTML = '<div style="font-size:11px;color:var(--text3)">暂无内容生产资料，支持 txt / md / pdf / doc / docx / xlsx</div>';
    return;
  }
  el.innerHTML = files.map(f => `
    <div style="display:flex;align-items:flex-start;gap:10px;padding:9px 0;border-bottom:1px solid var(--border2)">
      <i class="ti ti-file-text" style="color:var(--teal);font-size:16px"></i>
      <div style="flex:1">
        <div style="font-size:12px;font-weight:700;color:var(--text)">${escHtml(f.original_name || f.name)}</div>
        <div style="font-size:10px;color:var(--text3)">${(f.size/1024).toFixed(1)}KB · ${escHtml(f.uploaded || '')}</div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:5px">
          <span class="badge ${materialStatusClass(f)}" style="font-size:9px">${escHtml(materialDisplayStatus(f))}</span>
          ${materialIssueText(f) ? `<span class="badge badge-r" style="font-size:9px">${escHtml(materialIssueText(f))}</span>` : ''}
        </div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
        ${materialUsageButton(f, 'toggleContentMaterialUsage')}
        <button class="btn btn-danger btn-sm" onclick="delContentMaterial('${encodeURIComponent(f.id || f.name)}')">删除</button>
      </div>
    </div>`).join('');
}

async function uploadContentMaterial(input) {
  if (!currentClientId) { toast('请先选择客户','err'); return; }
  const files = Array.from(input.files || []);
  if (!files.length) return;
  const formData = new FormData();
  files.forEach(file => formData.append('file', file));
  try {
    const res = await fetch('/api/content/materials/' + currentClientId + '/upload', {
      method: 'POST', body: formData
    });
    const r = await res.json();
    if (r.error) { toast(r.error,'err'); return; }
    toast(`内容生产资料上传成功：${(r.materials||[]).length || 1} 份 ✦`);
    loadContentMaterials();
  } catch(e) {
    toast('上传失败：' + e.message, 'err');
  }
  input.value = '';
}

async function delContentMaterial(id) {
  if (!confirm('确认删除该内容生产资料？')) return;
  await api(`/api/content/materials/${currentClientId}/${id}`, 'DELETE');
  toast('已删除');
  loadContentMaterials();
}

async function toggleContentMaterialUsage(id, confirmed) {
  const r = await api(`/api/content/materials/${currentClientId}/${id}/confirm`, 'POST', {confirmed});
  if (r.error) { toast(r.error, 'err'); return; }
  toast(confirmed ? '已设为使用' : '已设为不使用');
  loadContentMaterials();
}

let selectedContentArticleType = '对比型';
let activeContentBatchJobId = '';
let contentBatchPollTimer = null;
function selectContentArticleType(type) {
  selectedContentArticleType = type === '介绍型' ? '介绍型' : '对比型';
  const compareBtn = document.getElementById('contentArticleTypeCompare');
  const introBtn = document.getElementById('contentArticleTypeIntro');
  if (compareBtn && introBtn) {
    compareBtn.className = selectedContentArticleType === '对比型' ? 'btn btn-p btn-sm' : 'btn btn-o btn-sm';
    introBtn.className = selectedContentArticleType === '介绍型' ? 'btn btn-p btn-sm' : 'btn btn-o btn-sm';
  }
}

async function generateContentArticle() {
  if (!currentClientId) { toast('请先选择客户','err'); return; }
  if (Number(document.getElementById('contentGenerationCount')?.value || 1) > 1) {
    return generateContentBatch();
  }
  spin('spContentGenerate', true);
  disableBtn('btnContentGenerate', true);
  const statusEl = document.getElementById('contentGenerateStatus');
  statusEl.textContent = '当前模型生成中，请稍候...';
  try {
    const r = await api('/api/content/generate', 'POST', contentGenerationPayload());
    if (r.error) { toast(r.error, 'err'); return; }
    renderContentGenerations(r.articles || []);
    statusEl.textContent = `已生成：${r.article?.title || '新文章'}`;
    toast('文章生成成功 ✦');
  } finally {
    spin('spContentGenerate', false);
    disableBtn('btnContentGenerate', false);
  }
}
function contentGenerationPayload() {
  return {
    client_id: currentClientId,
    history_date: getContentHistoryDate(),
    article_type: selectedContentArticleType,
    use_material_package: document.getElementById('useMaterialPackage')?.checked !== false,
    use_material_web_supplement: document.getElementById('useMaterialWebSupplement')?.checked !== false,
    use_competitors: document.getElementById('useCompetitorMaterials')?.checked !== false
  };
}
function renderContentBatchProgress(job) {
  const el = document.getElementById('contentBatchProgress');
  if (!el || !job) return;
  const items = job.items || [];
  const running = items.find(item => item.status === '生成中');
  const progress = running ? `第 ${running.index}/${job.count} 篇` : `已处理 ${items.filter(item => item.status !== '排队').length}/${job.count} 篇`;
  const terminal = ['completed', 'cancelled'].includes(job.status);
  el.style.display = 'block';
  el.innerHTML = `<div style="font-size:12px;font-weight:800;color:var(--text2);margin-bottom:5px">${escHtml(progress)} · ${escHtml(job.status || '')}</div>
    ${(items || []).map(item => `<span class="badge ${item.status === '失败' || item.status === '门禁拦截' ? 'badge-r' : item.status === '完成' ? 'badge-g' : 'badge-a'}" style="margin:0 5px 5px 0">${item.index}. ${escHtml(item.status)}${item.title ? `：${escHtml(item.title)}` : ''}${item.error ? `：${escHtml(item.error)}` : ''}</span>`).join('')}
    ${terminal ? '' : '<button class="btn btn-o btn-sm" onclick="cancelContentBatchGeneration()">终止</button>'}`;
}
async function generateContentBatch() {
  if (!currentClientId) { toast('请先选择客户','err'); return; }
  const count = Number(document.getElementById('contentGenerationCount')?.value || 5);
  spin('spContentGenerate', true);
  disableBtn('btnContentGenerate', true);
  const statusEl = document.getElementById('contentGenerateStatus');
  statusEl.textContent = '批量任务创建中...';
  const r = await api('/api/content/generate_batch', 'POST', {...contentGenerationPayload(), count});
  if (r.error || !r.job) {
    spin('spContentGenerate', false);
    disableBtn('btnContentGenerate', false);
    toast(r.error || '批量任务创建失败', 'err');
    return;
  }
  activeContentBatchJobId = r.job.job_id;
  renderContentBatchProgress(r.job);
  pollContentBatchGeneration();
}
async function pollContentBatchGeneration() {
  if (!activeContentBatchJobId) return;
  const r = await api(`/api/content/generate_batch/${encodeURIComponent(activeContentBatchJobId)}`);
  if (r.error || !r.job) {
    finishContentBatchGeneration();
    toast(r.error || '批量任务状态读取失败', 'err');
    return;
  }
  renderContentBatchProgress(r.job);
  if (['completed', 'cancelled'].includes(r.job.status)) {
    finishContentBatchGeneration();
    await Promise.all([loadContentGenerations(), loadQualityGateArticles()]);
    toast(r.job.status === 'cancelled' ? '批量生成已终止' : '批量生成完成 ✦');
    return;
  }
  contentBatchPollTimer = setTimeout(pollContentBatchGeneration, 1000);
}
async function cancelContentBatchGeneration() {
  if (!activeContentBatchJobId) return;
  const r = await api(`/api/content/generate_batch/${encodeURIComponent(activeContentBatchJobId)}/cancel`, 'POST', {});
  if (r.error) { toast(r.error, 'err'); return; }
  renderContentBatchProgress(r.job);
}
function finishContentBatchGeneration() {
  if (contentBatchPollTimer) clearTimeout(contentBatchPollTimer);
  contentBatchPollTimer = null;
  activeContentBatchJobId = '';
  spin('spContentGenerate', false);
  disableBtn('btnContentGenerate', false);
}
async function loadContentGenerations() {
  const el = document.getElementById('contentArticleList');
  if (!currentClientId) {
    if (el) el.innerHTML = '<div class="empty"><i class="ti ti-writing"></i><p>请先选择客户</p></div>';
    return;
  }
  const r = await api('/api/content/generations?client_id=' + currentClientId + '&date=' + encodeURIComponent(getContentHistoryDate()));
  if (r.error) { toast(r.error, 'err'); return; }
  renderContentGenerations(r.articles || []);
}
async function loadQualityGateArticles() {
  const el = document.getElementById('qualityArticleList');
  if (!currentClientId) {
    if (el) el.innerHTML = '<div class="empty"><i class="ti ti-shield-check"></i><p>请先选择客户</p></div>';
    return;
  }
  const r = await api('/api/content/generations?client_id=' + encodeURIComponent(currentClientId));
  if (r.error) { toast(r.error, 'err'); return; }
  renderQualityGateArticles(r.articles || []);
}
function qualityGateFailedChecks(article) {
  const report = article?.gate_report || {};
  return [...(report.code_layer || []), ...(report.llm_layer || [])].filter(item => item && item.passed === false);
}
function qualityGateReason(article) {
  const first = qualityGateFailedChecks(article)[0];
  if (!first) return '';
  return (first.evidence || [])[0] || first.check_id || '需要人工确认';
}
const QUALITY_GATE_CHECK_DESCRIPTIONS = {
  banned_words: '禁用词命中',
  title_brand: '标题不得直接点名客户或本次机构',
  meta_discourse: '成文不得泄漏内部工作用语',
  shingle_duplicate: '与近期文章的重复度提示',
  fact_traceability: '数字与主张可溯源',
  competitor_fairness: '机构比较应公平呈现',
  semantic_marketing: '营销与绝对化语义复核',
  competitor_claim_repetition: '竞品强主张复读检查',
  llm_response: '门禁模型返回结果检查',
  quality_gate_internal: '门禁内部异常提示',
};
function qualityGateCheckDescription(checkId) {
  return QUALITY_GATE_CHECK_DESCRIPTIONS[checkId] || '质量门禁检查项';
}
function qualityGateBadge(article) {
  if (article?.generation_status === '人工已编辑') return '<span class="badge badge-p">人工已编辑</span>';
  const verdict = article?.gate_report?.verdict;
  if (verdict === 'pass') return '<span class="badge badge-g">已审核 · 可发布</span>';
  if (verdict === 'blocked') return `<span class="badge badge-r">审核不通过：${escHtml(qualityGateReason(article))} · 建议修改后再用</span>`;
  if (verdict === 'warn') return `<span class="badge badge-a">审核提示：${escHtml(qualityGateReason(article))} · 人工判断</span>`;
  return '<span class="badge badge-a">未审核</span>';
}
function contentGenerationPatternNames(a) {
  const entries = a?.provenance?.entries || {};
  return ['skeleton', 'opening_module', 'ending_module', 'faq_module', 'table_module']
    .map(key => entries[key]?.name).concat((entries.body_modules || []).map(item => item?.name))
    .filter(Boolean).join(' · ');
}
function renderContentGenerations(articles) {
  const countEl = document.getElementById('content-article-count');
  if (countEl) countEl.textContent = articles.length + ' 篇';
  const el = document.getElementById('contentArticleList');
  if (!el) return;
  if (!articles.length) {
    el.innerHTML = '<div class="empty"><i class="ti ti-writing"></i><p>暂无文章，请先生成</p></div>';
    return;
  }
  window._contentGenerationCache = articles;
  el.innerHTML = articles.map(a => {
    const title = escHtml(a.title || '未命名文章');
    const model = escHtml(a.model || '未知模型');
    const articleType = escHtml(a.article_type || '未标记类型');
    const createdAt = escHtml(a.created_at || '');
    const summary = escHtml((a.content || '').slice(0, 160));
    const patterns = contentGenerationPatternNames(a);
    return `
    <div class="article-card">
      <div class="article-title">${title}</div>
      <div class="article-meta">
        <span class="badge badge-p">调用模型：${model}</span>
        <span class="badge badge-g">${articleType}</span>
        ${qualityGateBadge(a)}
        <span class="badge badge-g">资料 ${a.material_count || 0} 份</span>
        <span class="badge badge-a">样例 ${((a.sample_link_count || 0) + (a.selected_article_count || 0))} 个</span>
        <span style="font-size:10px;color:var(--text3)">${createdAt}</span>
      </div>
      ${patterns ? `<div style="font-size:10px;color:var(--text3);margin:5px 0">写法：${escHtml(patterns)}</div>` : ''}
      <div class="article-summary">${summary}${(a.content || '').length > 160 ? '...' : ''}</div>
      <div class="article-acts">
        <button class="btn btn-o btn-sm" onclick="viewContentGeneration('${a.id}')">查看全文</button>
        <button class="btn btn-o btn-sm" onclick="copyContentGeneration('${a.id}')">复制</button>
        <button class="btn btn-o btn-sm" onclick="manualEditContentGeneration('${a.id}')">人工编辑</button>
        <button class="btn btn-p btn-sm" onclick="aiModifyContentGeneration('${a.id}')">AI 修改</button>
        <button class="btn btn-danger btn-sm" onclick="deleteContentGeneration('${a.id}')">删除</button>
      </div>
    </div>`;
  }).join('');
}
function renderQualityGateArticles(articles) {
  const countEl = document.getElementById('quality-article-count');
  if (countEl) countEl.textContent = articles.length + ' 篇';
  const el = document.getElementById('qualityArticleList');
  if (!el) return;
  window._qualityGateArticleCache = articles;
  if (!articles.length) {
    el.innerHTML = '<div class="empty"><i class="ti ti-shield-check"></i><p>暂无已生产文章</p></div>';
    return;
  }
  el.innerHTML = articles.map(a => {
    const checks = qualityGateFailedChecks(a);
    const details = checks.length
      ? `<div class="quality-gate-details">${checks.map(item => `<span class="badge ${item.severity === 'block' ? 'badge-r' : 'badge-a'}">${escHtml(item.check_id)}（${escHtml(qualityGateCheckDescription(item.check_id))}）：${escHtml((item.evidence || []).join('；') || '未通过')}</span>`).join('')}</div>`
      : '<div class="quality-gate-details"><span style="font-size:11px;color:var(--text3)">无未通过检查项</span></div>';
    return `<div class="article-card">
      <div class="article-title">${escHtml(a.title || '未命名文章')}</div>
      <div class="article-meta">${qualityGateBadge(a)}<span class="badge badge-p">${escHtml(a.article_type || '未标记类型')}</span><span style="font-size:10px;color:var(--text3)">${escHtml(a.created_at || '')}</span></div>
      ${details}
      <div class="article-summary">${escHtml((a.content || '').slice(0, 160))}${(a.content || '').length > 160 ? '...' : ''}</div>
      <div class="article-acts"><button class="btn btn-o btn-sm" onclick="viewContentGeneration('${a.id}')">查看全文</button><button class="btn btn-o btn-sm" onclick="copyContentGeneration('${a.id}')">复制</button><button class="btn btn-o btn-sm" onclick="manualEditContentGeneration('${a.id}')">人工编辑</button><button class="btn btn-o btn-sm" onclick="createDistributionDraft('${a.id}')">创建发布草稿</button><button class="btn btn-p btn-sm" onclick="aiModifyContentGeneration('${a.id}')">AI 修改</button></div>
    </div>`;
  }).join('');
}
function findContentGeneration(id) {
  return [...(window._contentGenerationCache || []), ...(window._qualityGateArticleCache || [])].find(item => item.id === id);
}
let contentEditMode = '';
let contentEditArticleId = '';
function openContentEditDialog(article, mode) {
  const modal = document.getElementById('contentEditModal');
  if (!modal || !article) return;
  contentEditMode = mode;
  contentEditArticleId = article.id;
  document.getElementById('contentEditModalTitle').textContent = mode === 'manual' ? '人工编辑文章' : 'AI 修改文章';
  document.getElementById('contentEditModalLabel').textContent = mode === 'manual' ? '完整文章（首行作为标题）' : '本次修改指令（会连同原文和历史修改词交给 AI）';
  document.getElementById('contentEditModalInput').value = mode === 'manual' ? (article.content || '') : '';
  modal.style.display = 'flex';
}
function closeContentEditDialog(force=false) {
  const save = document.getElementById('contentEditModalSave');
  if (!force && contentEditMode === 'ai' && save?.disabled && !confirm('AI 修改仍在进行中，确认关闭？')) return;
  document.getElementById('contentEditModal').style.display = 'none';
  contentEditArticleId = ''; contentEditMode = '';
}
function manualEditContentGeneration(id) { openContentEditDialog(findContentGeneration(id), 'manual'); }
function aiModifyContentGeneration(id) { openContentEditDialog(findContentGeneration(id), 'ai'); }
async function saveContentEditDialog() {
  const value = document.getElementById('contentEditModalInput').value.trim();
  if (!value || !contentEditArticleId || !currentClientId) { toast('请填写内容或修改指令', 'err'); return; }
  const save = document.getElementById('contentEditModalSave');
  const defaultLabel = save.innerHTML;
  save.disabled = true;
  if (contentEditMode === 'ai') save.innerHTML = '<span class="spin" style="display:inline-block"></span> AI 修改中，含门禁重检（约 1-3 分钟）…';
  try {
    const url = `/api/content/generations/${encodeURIComponent(contentEditArticleId)}${contentEditMode === 'ai' ? '/ai_modify' : ''}?client_id=${encodeURIComponent(currentClientId)}`;
    const r = await api(url, contentEditMode === 'ai' ? 'POST' : 'PUT', contentEditMode === 'ai' ? {instruction: value} : {content: value});
    if (r.error) { toast(r.error, 'err'); return; }
    const mode = contentEditMode;
    closeContentEditDialog(true);
    await Promise.all([loadContentGenerations(), loadQualityGateArticles()]);
    toast(mode === 'ai' ? 'AI 修改版本已生成' : '文章已人工保存');
  } finally { save.disabled = false; save.innerHTML = defaultLabel; }
}
function viewContentGeneration(id) {
  const a = findContentGeneration(id);
  if (!a) return;
  const title = escHtml(a.title || '生成文章');
  const win = window.open('','_blank','width=760,height=680');
  win.document.write(`<html><head><title>${title}</title><link href="{{ url_for('static', filename='css/app.css') }}" rel="stylesheet"></head><body><h1>${title}</h1><pre>${escHtml(a.content || '')}</pre></body></html>`);
}
function copyContentGeneration(id) {
  const a = findContentGeneration(id);
  if (!a) return;
  copyTextToClipboard(a.content || '', '文章已复制 ✦');
}
async function deleteContentGeneration(id) {
  if (!currentClientId || !id) return;
  if (!confirm('确认删除这篇历史生成结果？')) return;
  const r = await api('/api/content/generations/' + encodeURIComponent(id) + '?client_id=' + encodeURIComponent(currentClientId) + '&date=' + encodeURIComponent(getContentHistoryDate()), 'DELETE');
  if (r.error) { toast(r.error, 'err'); return; }
  renderContentGenerations(r.articles || []);
  toast('已删除');
}
// ── Settings ──────────────────────────────────────────
const PRESETS = {
  deepseek:{label:'DeepSeek',base_url:'https://api.deepseek.com',model:'deepseek-chat'},
  botclaw_claude:{label:'Claude（中转）',base_url:'https://ai.botclaw.top/v1',model:'claude-sonnet-4-20250514'},
  openai:{label:'OpenAI',base_url:'https://api.openai.com/v1',model:'gpt-4o'},
  custom:{label:'自定义',base_url:'',model:''}
};
let selectedPreset = 'deepseek';
function updateApiStatus(s) {
  const statusEl = document.getElementById('apiStatusText');
  const modelEl = document.getElementById('modelText');
  if (!statusEl || !modelEl) return;
  if (s?.has_key) {
    statusEl.textContent = 'API 已配置';
    statusEl.style.color = 'var(--teal)';
    modelEl.textContent = s.model || '已配置模型';
  } else {
    statusEl.textContent = 'API 未配置';
    statusEl.style.color = 'var(--red)';
    modelEl.textContent = '请先完成设置';
  }
}

async function refreshApiStatus() {
  try {
    const s = await api('/api/settings');
    updateApiStatus(s);
    return s;
  } catch {
    updateApiStatus({has_key:false});
    return null;
  }
}

async function loadSettings() {
  const s = await api('/api/settings');
  document.getElementById('set-url').value = s.base_url||'';
  document.getElementById('set-model').value = s.model||'';
  const tavilyInput = document.getElementById('set-tavily-key');
  if (tavilyInput) tavilyInput.placeholder = s.has_tavily_key ? '已配置，留空则不修改' : '填入 Tavily API Key';
  selectedPreset = s.preset||'deepseek';
  renderPresets();
  updateApiStatus(s);
}
function renderPresets() {
  document.getElementById('presetGrid').innerHTML = Object.entries(PRESETS).map(([k,v]) => `
    <div onclick="selectPreset('${k}')" style="padding:10px 12px;background:${selectedPreset===k?'rgba(109,92,247,.12)':'rgba(255,255,255,.8)'};border:1.5px solid ${selectedPreset===k?'var(--pri)':'var(--border2)'};border-radius:var(--r-sm);cursor:pointer;transition:all .15s">
      <div style="font-size:12px;font-weight:800;color:${selectedPreset===k?'var(--pri)':'#312e81'}">${v.label}</div>
      <div style="font-size:10px;color:var(--text3);margin-top:2px">${v.model||'自定义'}</div>
    </div>`).join('');
}
function selectPreset(k) {
  selectedPreset = k;
  const p = PRESETS[k];
  if (p.base_url) document.getElementById('set-url').value = p.base_url;
  if (p.model) document.getElementById('set-model').value = p.model;
  renderPresets();
}
async function saveSettings() {
  const key = document.getElementById('set-key').value.trim();
  const tavilyKey = document.getElementById('set-tavily-key')?.value.trim() || '';
  const url = document.getElementById('set-url').value.trim();
  const model = document.getElementById('set-model').value.trim();
  if (!url||!model) { toast('请填写接口地址和模型名称','err'); return; }
  await api('/api/settings','POST',{api_key:key||'***',tavily_api_key:tavilyKey||'***',base_url:url,model,preset:selectedPreset});
  updateApiStatus({has_key:true, has_tavily_key:!!tavilyKey, model});
  document.getElementById('set-key').value = '';
  const tavilyInput = document.getElementById('set-tavily-key');
  if (tavilyInput) {
    tavilyInput.value = '';
    if (tavilyKey) tavilyInput.placeholder = '已配置，留空则不修改';
  }
  toast('配置已保存 ✦');
}
async function testApi() {
  spin('spTest',true);
  const r = document.getElementById('testResult');
  r.textContent = '测试中...'; r.style.color = 'var(--text2)';
  try {
    const res = await api('/api/settings/test','POST');
    if (res.ok) { r.textContent = '✓ ' + res.reply; r.style.color = 'var(--teal)'; }
    else { r.textContent = '✗ ' + res.error; r.style.color = 'var(--red)'; }
  } catch(e) { r.textContent = '请求失败'; r.style.color = 'var(--red)'; }
  finally { spin('spTest',false); }
}

// ══════════════════════════════════════════════════════
// 平台颜色配置 & 引用标签渲染
// ══════════════════════════════════════════════════════
const PLATFORM_COLORS = {
  '土巴兔':    {bg:'#fef3c7', border:'#f59e0b', text:'#92400e'},
  '新浪家居':  {bg:'#fee2e2', border:'#f87171', text:'#991b1b'},
  '网易家居':  {bg:'#fce7f3', border:'#f472b6', text:'#9d174d'},
  '今日头条':  {bg:'#dbeafe', border:'#60a5fa', text:'#1e40af'},
  '搜狐':      {bg:'#e0f2fe', border:'#38bdf8', text:'#0c4a6e'},
  '百家号':    {bg:'#dcfce7', border:'#4ade80', text:'#14532d'},
  '知乎':      {bg:'#ede9fe', border:'#a78bfa', text:'#4c1d95'},
  '小红书':    {bg:'#fce7f3', border:'#ec4899', text:'#831843'},
  '抖音':      {bg:'#f0fdf4', border:'#34d399', text:'#064e3b'},
  '微信公众号':{bg:'#d1fae5', border:'#10b981', text:'#065f46'},
  '百度百科':  {bg:'#dbeafe', border:'#3b82f6', text:'#1e3a8a'},
  '凤凰网':    {bg:'#fff7ed', border:'#fb923c', text:'#7c2d12'},
  '腾讯新闻':  {bg:'#eff6ff', border:'#3b82f6', text:'#1d4ed8'},
  '网易新闻':  {bg:'#fdf4ff', border:'#c084fc', text:'#6b21a8'},
  '新浪新闻':  {bg:'#fff1f2', border:'#fb7185', text:'#9f1239'},
  '链家':      {bg:'#ecfdf5', border:'#34d399', text:'#065f46'},
  '安居客':    {bg:'#fffbeb', border:'#fbbf24', text:'#78350f'},
  '未知':      {bg:'#f3f4f6', border:'#9ca3af', text:'#374151'},
};

function getPlatformColor(platform) {
  return PLATFORM_COLORS[platform] || {bg:'#f3f4f6', border:'#d1d5db', text:'#4b5563'};
}

let currentGroupId = '';
let currentGroupQuestions = [];

function clearActiveGroupSelection() {
  currentGroupId = '';
  currentGroupQuestions = [];
  const card = document.getElementById('groupDetailCard');
  if (card) card.style.display = 'none';
  const questionList = document.getElementById('groupQuestionList');
  if (questionList) questionList.innerHTML = '<div class="empty"><i class="ti ti-list"></i><p>暂无问题</p></div>';
  const status = document.getElementById('grpCrawlStatus');
  if (status) status.textContent = '';
  const result = document.getElementById('grpCrawlResult');
  if (result) {
    result.style.display = 'none';
    result.innerHTML = '';
  }
}

function showCreateGroup() {
  const c = document.getElementById('createGroupCard');
  c.style.display = c.style.display === 'none' ? 'block' : 'none';
}

async function loadGroups() {
  if (!currentClientId) return;
  const groups = await api('/api/groups/' + currentClientId);
  const el = document.getElementById('groupList');
  // 更新记录库问题组下拉
  const filter = document.getElementById('rec-group-filter');
  if (filter) {
    const selectedGroup = filter.value;
    filter.innerHTML = '<option value="">请选择问题组</option>' +
      groups.map(g => `<option value="${g.id}">${g.name}（${g.questions.length}题）</option>`).join('');
    filter.value = groups.some(g => g.id === selectedGroup) ? selectedGroup : (groups[0]?.id || '');
    filter.dataset.clientId = currentClientId;
  }
  if (!groups.length) {
    el.innerHTML = '<div class="empty"><i class="ti ti-folder"></i><p>暂无问题组</p></div>';
    return;
  }
  el.innerHTML = groups.map(g => `
    <div class="card" style="margin-bottom:10px;cursor:pointer" onclick="openGroup('${g.id}')">
      <div style="display:flex;align-items:center;justify-content:space-between">
        <div>
          <div style="font-size:14px;font-weight:800;color:#312e81;margin-bottom:3px">${g.name}</div>
          <div style="font-size:11px;color:var(--text2)">${g.description || '暂无描述'}</div>
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          <span class="badge badge-p">${g.questions.length} 题</span>
          <span style="font-size:11px;color:var(--text3)">${g.created}</span>
          <button class="btn btn-danger btn-sm" onclick="event.stopPropagation();delGroup('${g.id}')">删除</button>
        </div>
      </div>
      <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">
        ${g.questions.slice(0,3).map(q => `<span style="font-size:10px;padding:3px 8px;background:var(--pri-ll);color:var(--pri);border-radius:6px;font-weight:700">${q.slice(0,25)}${q.length>25?'…':''}</span>`).join('')}
        ${g.questions.length > 3 ? `<span style="font-size:10px;color:var(--text3)">...还有${g.questions.length-3}题</span>` : ''}
      </div>
    </div>`).join('');
}

async function createGroup() {
  const name = document.getElementById('grp-name').value.trim();
  if (!name) { toast('请填写组名称','err'); return; }
  await api('/api/groups/' + currentClientId, 'POST', {
    name, description: document.getElementById('grp-desc').value
  });
  toast('问题组已创建 ✦');
  document.getElementById('grp-name').value = '';
  document.getElementById('grp-desc').value = '';
  document.getElementById('createGroupCard').style.display = 'none';
  loadGroups();
}

async function delGroup(gid) {
  if (!confirm('确认删除该问题组？')) return;
  await api(`/api/groups/${currentClientId}/${gid}`, 'DELETE');
  toast('已删除');
  document.getElementById('groupDetailCard').style.display = 'none';
  loadGroups();
}

async function openGroup(gid) {
  const groups = await api('/api/groups/' + currentClientId);
  const g = groups.find(x => x.id === gid);
  if (!g) return;
  currentGroupId = gid;
  currentGroupQuestions = [...g.questions];
  document.getElementById('groupDetailName').textContent = '📁 ' + g.name;
  document.getElementById('groupDetailDesc').textContent = g.description || '';
  document.getElementById('groupDetailCard').style.display = 'block';
  document.getElementById('groupDetailCard').scrollIntoView({behavior:'smooth'});
  renderGroupQuestions();
  renderGroupPlatformChoices();
}

function renderGroupQuestions() {
  const el = document.getElementById('groupQuestionList');
  if (!currentGroupQuestions.length) {
    el.innerHTML = '<div class="empty"><i class="ti ti-list"></i><p>暂无问题</p></div>';
    return;
  }
  el.innerHTML = currentGroupQuestions.map((q,i) => `
    <div class="question-item">
      <span class="question-num">${String(i+1).padStart(2,'0')}</span>
      <span class="question-text">${escHtml(q)}</span>
      <button class="question-del" onclick="delGroupQ(${i})">×</button>
    </div>`).join('');
}

async function persistGroupQuestions(silent=false) {
  if (!currentGroupId) return false;
  const r = await api(`/api/groups/${currentClientId}/${currentGroupId}`, 'PUT', {
    questions: currentGroupQuestions
  });
  if (r.error) {
    toast(r.error || '保存失败', 'err');
    return false;
  }
  if (!silent) toast('问题组已保存 ✦');
  loadGroups();
  return true;
}

async function delGroupQ(i) {
  currentGroupQuestions.splice(i, 1);
  renderGroupQuestions();
  await persistGroupQuestions(true);
  toast('问题已删除并保存');
}

async function addManualQuestion() {
  const box = document.getElementById('groupBatchQuestionBox');
  const input = document.getElementById('groupBatchQuestionInput');
  box.style.display = box.style.display === 'none' ? 'block' : 'none';
  if (box.style.display !== 'none') input.focus();
}

function parseBatchQuestions(raw) {
  return String(raw || '')
    .split(/\r?\n/)
    .map(line => line.replace(/^\s*(?:[-*•]\s*|[（(]?\d+[）)]?[.、)]?\s*)/, '').trim())
    .filter(Boolean);
}

async function addBatchQuestions() {
  const input = document.getElementById('groupBatchQuestionInput');
  const parsed = parseBatchQuestions(input.value);
  const seen = new Set(currentGroupQuestions);
  const additions = parsed.filter(q => {
    if (seen.has(q)) return false;
    seen.add(q);
    return true;
  });
  if (!additions.length) {
    toast('没有可添加的新问题', 'err');
    return;
  }
  currentGroupQuestions.push(...additions);
  input.value = '';
  document.getElementById('groupBatchQuestionBox').style.display = 'none';
  renderGroupQuestions();
  await persistGroupQuestions(true);
  toast(`已添加 ${additions.length} 个问题并保存 ✦`);
}

async function saveGroupQuestions() {
  await persistGroupQuestions(false);
}

function getGroupCrawlPlatformChoicesForJobs() {
  return sortCrawlPlatforms(getSelectedGroupCrawlPlatformIds().map(id => ({
    id,
    name: CRAWL_PLATFORM_NAMES[id] || id
  })));
}

async function enqueueGroupCrawlJobs() {
  if (!currentClientId) { toast('请先选择客户','err'); return; }
  if (!currentGroupId) { toast('请先打开问题组','err'); return; }
  if (!currentGroupQuestions.length) { toast('该组暂无问题','err'); return; }
  const repeat = parseInt(document.getElementById('grpRepeat').value) || 1;
  const platforms = getGroupCrawlPlatformChoicesForJobs();
  if (!platforms.length) {
    toast('请先选择至少一个爬取平台', 'err');
    return;
  }
  const total = currentGroupQuestions.length * repeat * platforms.length;
  if (!confirm(`将创建 ${platforms.length} 个本地 worker 任务\n${currentGroupQuestions.length} 题 × ${repeat} 次 × ${platforms.length} 平台 = ${total} 个样本，确认？`)) return;

  const btn = document.getElementById('btnCrawlGroup');
  btn.disabled = true;
  document.getElementById('grpCrawlStatus').textContent = '正在创建本地 worker 任务...';
  document.getElementById('grpCrawlResult').style.display = 'block';

  try {
    const jobs = [];
    const errors = [];
    const batchId = `batch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    for (const platform of platforms) {
      const resp = await fetch('/api/crawl_jobs', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          client_id: currentClientId,
          brand: currentBrand,
          group_id: currentGroupId,
          platform: platform.id,
          repeat_count: repeat,
          batch_id: batchId
        })
      });
      const data = await resp.json();
      if (data.error) errors.push(`${platform.name}：${data.message || data.error}`);
      else jobs.push({platform, job: data.job});
    }

    document.getElementById('grpCrawlStatus').textContent =
      `已创建 ${jobs.length} 个本地 worker 任务${errors.length ? `，失败 ${errors.length} 个` : ''}`;
    document.getElementById('grpCrawlResult').innerHTML = `
      <div style="padding:10px;background:var(--bg);border:1px solid var(--border2);border-radius:var(--r-sm);font-size:12px;line-height:1.7">
        <div style="font-weight:900;color:var(--text);margin-bottom:6px">本地 worker 任务已创建</div>
        ${jobs.map(({platform, job}) => `
          <div style="display:flex;gap:8px;align-items:center;justify-content:space-between;border-top:1px solid var(--border2);padding:6px 0">
            <span>${escHtml(platform.name)} · ${escHtml(job.id)}</span>
            <button class="btn btn-danger btn-sm" onclick="cancelCrawlJob('${escHtml(job.id)}')">取消</button>
          </div>`).join('')}
        ${errors.length ? `<div style="color:var(--red);margin-top:8px">${errors.map(escHtml).join('<br>')}</div>` : ''}
      </div>`;
    if (jobs.length) toast('本地 worker 任务已创建');
  } catch(e) {
    toast('创建任务失败：' + e.message, 'err');
    document.getElementById('grpCrawlStatus').textContent = '创建任务失败';
  } finally {
    btn.disabled = false;
  }
}

async function cancelCrawlJob(jobId) {
  if (!jobId) return;
  try {
    const resp = await fetch(`/api/crawl_jobs/${encodeURIComponent(jobId)}/cancel`, {method: 'POST'});
    const data = await resp.json();
    if (data.error) throw new Error(data.message || data.error);
    toast('任务已取消');
  } catch(e) {
    toast('取消失败：' + e.message, 'err');
  }
}

function buildTaskFilterOptions(records) {
  const tasks = new Map();
  (records || []).forEach(r => {
    if (!r.task_id) return;
    if (!tasks.has(r.task_id)) {
      tasks.set(r.task_id, {
        task_id: r.task_id,
        count: 0,
        latest: '',
        platforms: new Set()
      });
    }
    const task = tasks.get(r.task_id);
    task.count += 1;
    if ((r.crawl_time || '') > task.latest) task.latest = r.crawl_time || '';
    if (r.source_platform) task.platforms.add(CRAWL_PLATFORM_NAMES[r.source_platform] || r.source_platform);
  });
  return [...tasks.values()].sort((a, b) => (b.latest || '').localeCompare(a.latest || ''));
}

function updateTaskFilterOptions(selectId, records, defaultToLatest=false) {
  const sel = document.getElementById(selectId);
  if (!sel) return '';
  const previous = sel.value;
  const tasks = buildTaskFilterOptions(records);
  const allLabel = selectId === 'dailyTaskFilter' ? '今日全部' : '全部批次';
  sel.innerHTML = `<option value="">${allLabel}</option>` + tasks.map(t => {
    const shortId = t.task_id.length > 8 ? t.task_id.slice(-8) : t.task_id;
    const platforms = [...t.platforms].join('、') || '未知平台';
    const label = `${t.latest || '未知时间'} · ${platforms} · ${t.count}条 · #${shortId}`;
    return `<option value="${escHtml(t.task_id)}">${escHtml(label)}</option>`;
  }).join('');
  if (previous && tasks.some(t => t.task_id === previous)) {
    sel.value = previous;
  } else if (defaultToLatest && tasks.length && sel.dataset.manual !== '1') {
    sel.value = tasks[0].task_id;
  } else {
    sel.value = '';
  }
  return sel.value;
}

function resetDailyTaskFilter() {
  const sel = document.getElementById('dailyTaskFilter');
  if (!sel) return;
  sel.dataset.manual = '';
  sel.value = '';
}

function markDailyTaskFilterManual() {
  const sel = document.getElementById('dailyTaskFilter');
  if (sel) sel.dataset.manual = '1';
}

function onRecDateChange() {
  // 选了日期就取消「全部」高亮
  const btn = document.getElementById('btnRecDateAll');
  if (btn) { btn.className = 'btn btn-o btn-sm'; btn.style.color = ''; }
  loadRawRecords();
}

function clearRecDate() {
  // 清空日期=全部
  const input = document.getElementById('rec-date-filter');
  if (input) input.value = '';
  const btn = document.getElementById('btnRecDateAll');
  if (btn) { btn.className = 'btn btn-p btn-sm'; }
  loadRawRecords();
}

async function onRecGroupChange() {
  const groupId = document.getElementById('rec-group-filter')?.value || '';
  const questionSel = document.getElementById('rec-question-filter');
  if (!questionSel) return;
  questionSel.innerHTML = '<option value="">全部问题</option>';
  if (groupId) {
    try {
      const groups = await api('/api/groups/' + currentClientId);
      const group = groups.find(g => g.id === groupId);
      if (group && group.questions) {
        group.questions.forEach(q => {
          const opt = document.createElement('option');
          opt.value = q;
          opt.textContent = q.length > 40 ? q.slice(0, 40) + '...' : q;
          opt.title = q;
          questionSel.appendChild(opt);
        });
      }
    } catch(e) {}
  }
  loadRawRecords();
}

async function loadRawRecords() {
  const group_id = document.getElementById('rec-group-filter')?.value || '';
  const question_filter = document.getElementById('rec-question-filter')?.value || '';
  const date = document.getElementById('rec-date-filter')?.value || '';
  const mentioned = document.getElementById('rec-mentioned-filter')?.value || '';
  let url = `/api/raw_records?client_id=${currentClientId}&platform=${currentPlatform}`;
  if (group_id) url += `&group_id=${group_id}`;
  if (question_filter) url += `&question=${encodeURIComponent(question_filter)}`;
  if (date) url += `&date=${date}`;
  if (mentioned) url += `&mentioned_only=${mentioned}`;
  const allRecords = await api(url);
  const taskId = updateTaskFilterOptions('rec-task-filter', allRecords, false);
  const records = taskId ? allRecords.filter(r => r.task_id === taskId) : allRecords;
  document.getElementById('rec-count').textContent = records.length + ' 条';

  // 加载平台统计（传入日期，空=全部）
  let statsUrl = `/api/raw_records/platform_stats?client_id=${currentClientId}&platform=${currentPlatform}`;
  if (group_id) statsUrl += `&group_id=${group_id}`;
  if (question_filter) statsUrl += `&question=${encodeURIComponent(question_filter)}`;
  if (date) statsUrl += `&date=${date}`;  // 有日期就按日期，没有就全部
  if (mentioned) statsUrl += `&mentioned_only=${mentioned}`;
  if (taskId) statsUrl += `&task_id=${encodeURIComponent(taskId)}`;
  const stats = await api(statsUrl);
  renderPlatformStats(stats);
  loadRecordQuestionTrend(question_filter);
  loadRecordArticlePool();
  loadRecordSourceTrend();

  const el = document.getElementById('rawRecordList');
  if (!records.length) {
    el.innerHTML = '<div class="empty"><i class="ti ti-database"></i><p>暂无记录，请先爬取数据</p></div>';
    return;
  }
  el.innerHTML = records.slice(0,30).map(r => {
    // GEO颜色规则：未提及强制0+红色；提及>=60绿色；提及<60黄色
    const geoScore = r.brand_mentioned ? (r.geo_score||0) : 0;
    const scoreColor = !r.brand_mentioned ? 'var(--red)' : geoScore>=60 ? 'var(--teal)' : 'var(--amber)';
    return `
    <div style="padding:12px;background:rgba(255,255,255,.8);border:1.5px solid var(--border2);border-radius:var(--r-sm);margin-bottom:8px">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:8px">
        <div style="font-size:12px;font-weight:800;color:#312e81;flex:1">${r.question}</div>
        <div style="display:flex;gap:6px;align-items:center;margin-left:10px;flex-shrink:0">
          ${r.brand_mentioned?'<span class="badge badge-g">已提及</span>':'<span class="badge badge-r">未提及</span>'}
          <span style="font-weight:900;color:${scoreColor};font-size:13px">GEO ${geoScore}</span>
          <span style="font-size:10px;color:var(--text3)">${r.crawl_time}</span>
          ${r.round>1?`<span class="badge badge-pk">第${r.round}次</span>`:''}
        </div>
      </div>
      <div style="font-size:11px;color:var(--text2);line-height:1.6;margin-bottom:8px;max-height:60px;overflow:hidden">${(r.answer||'').slice(0,200)}${(r.answer||'').length>200?'...':''}</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        ${(r.refs||[]).map(ref => renderRefTag(ref, r.brand || currentBrand)).join('')}
      </div>
    </div>`;
  }).join('');
}

async function loadLegacyRecordQuestionViews() {
  const questionSel = document.getElementById('rec-question-filter');
  if (!currentClientId || !questionSel) return;
  if (questionSel.dataset.clientId !== currentClientId) {
    const selectedQuestion = questionSel.value;
    questionSel.innerHTML = '<option value="">请选择问题</option>';
    try {
      const records = await api(`/api/raw_records?client_id=${encodeURIComponent(currentClientId)}`);
      [...new Set((records || []).map(record => record.question).filter(Boolean))].forEach(question => {
        const option = document.createElement('option');
        option.value = question;
        option.textContent = question.length > 60 ? question.slice(0, 60) + '...' : question;
        option.title = question;
        questionSel.appendChild(option);
      });
      questionSel.value = [...questionSel.options].some(option => option.value === selectedQuestion)
        ? selectedQuestion : '';
    } catch (error) {
      questionSel.innerHTML = '<option value="">问题加载失败</option>';
    }
    questionSel.dataset.clientId = currentClientId;
  }
  loadRecordQuestionTrend(questionSel.value);
  loadRecordArticlePool();
  loadRecordSourceTrend();
}

async function loadRecordsLibraryViews() {
  const groupSel = document.getElementById('rec-group-filter');
  if (!currentClientId || !groupSel) return;
  if (groupSel.dataset.clientId !== currentClientId) await loadGroups();
  loadRecordGroupTrend(groupSel.value);
  loadRecordArticlePool();
  loadRecordSourceTrend();
  loadQueryScenes();
}

function renderQuerySceneRows(rows) {
  const el = document.getElementById('querySceneRows');
  if (!el) return;
  if (!rows?.length) {
    el.innerHTML = '<div style="color:var(--text3);font-size:12px">请先提取场景词</div>';
    return;
  }
  const body = rows.map(row => `<tr><td>${escHtml(row.group_name || '未命名问题组')}</td><td>${escHtml(row.query || '')}</td><td>${escHtml((row.scene_terms || []).join('、') || '未识别具体场景词')}</td></tr>`).join('');
  el.innerHTML = `<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr><th>问题组</th><th>Query</th><th>场景词</th></tr></thead><tbody>${body}</tbody></table></div>`;
}

async function loadQueryScenes() {
  if (!currentClientId) return;
  try {
    const data = await api(`/api/records/selection-evidence/${encodeURIComponent(currentClientId)}`);
    renderQuerySceneRows(data.rows || []);
  } catch (error) {
    renderQuerySceneRows([]);
  }
}

async function refreshQueryScenes(dryRun=false) {
  if (!currentClientId) { toast('请先选择客户', 'err'); return; }
  disableBtn('btnRefreshQueryScenes', true);
  disableBtn('btnDryRunQueryScenes', true);
  try {
    const data = await api(`/api/records/selection-evidence/${encodeURIComponent(currentClientId)}/refresh`, 'POST', {dry_run: dryRun});
    if (data.error) { toast(data.error, 'err'); return; }
    renderQuerySceneRows(data.rows || []);
    toast(dryRun ? '试运行完成，结果未保存' : (data.updated ? `已更新 ${data.updated} 条场景词` : '场景词已是最新'));
  } finally {
    disableBtn('btnRefreshQueryScenes', false);
    disableBtn('btnDryRunQueryScenes', false);
  }
}

function renderRecordGroupLine(data) {
  const el = document.getElementById('recordGroupTrend');
  if (!el) return;
  if (!data.dates?.length) {
    el.innerHTML = '<div style="color:var(--text3);font-size:12px">该问题组暂无采集记录</div>';
    return;
  }
  const width = 640, height = 188, left = 34, right = 10, top = 14, bottom = 34;
  const ratios = data.overall.map(item => item.total ? item.mentioned / item.total : 0);
  const xFor = index => data.dates.length === 1 ? (left + width - right) / 2 : left + index * ((width - left - right) / (data.dates.length - 1));
  const yFor = ratio => top + (1 - ratio) * (height - top - bottom);
  const points = ratios.map((ratio, index) => `${xFor(index)},${yFor(ratio)}`).join(' ');
  const dots = ratios.map((ratio, index) => `<circle cx="${xFor(index)}" cy="${yFor(ratio)}" r="4" fill="var(--pri)"><title>${data.dates[index]} ${Math.round(ratio * 100)}%</title></circle>`).join('');
  const labels = data.dates.map((day, index) => `<text x="${xFor(index)}" y="${height - 12}" text-anchor="middle" fill="var(--text3)" font-size="10">${escHtml(day.slice(5))}</text>`).join('');
  const details = data.overall.map((item, index) => {
    const rate = item.total ? Math.round(item.mentioned / item.total * 100) : 0;
    return `<span style="font-size:11px;color:var(--text2)">${data.dates[index]} <b style="color:var(--pri)">${rate}%</b> (${item.mentioned}/${item.total})</span>`;
  }).join('<span style="color:var(--border)">·</span>');
  el.innerHTML = `<div style="font-size:12px;font-weight:800;color:#312e81;margin-bottom:6px">问题组总提及率</div><svg viewBox="0 0 ${width} ${height}" style="display:block;width:100%;min-width:480px;height:188px" aria-label="问题组总提及率折线图"><line x1="${left}" y1="${top}" x2="${left}" y2="${height - bottom}" stroke="var(--border)"/><line x1="${left}" y1="${height - bottom}" x2="${width - right}" y2="${height - bottom}" stroke="var(--border)"/><text x="2" y="${top + 4}" fill="var(--text3)" font-size="10">100%</text><text x="9" y="${height - bottom + 4}" fill="var(--text3)" font-size="10">0%</text><polyline points="${points}" fill="none" stroke="var(--pri)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>${dots}${labels}</svg><div style="display:flex;gap:6px 10px;flex-wrap:wrap;margin-top:4px">${details}</div>`;
}

function renderRecordGroupQuestionMatrix(data) {
  const el = document.getElementById('recordGroupQuestionMatrix');
  if (!el) return;
  if (!data.dates?.length) {
    el.innerHTML = '<div style="color:var(--text3);font-size:12px">该问题组暂无采集记录</div>';
    return;
  }
  const columns = `minmax(160px,1.6fr) repeat(${data.dates.length}, minmax(72px,1fr))`;
  const header = data.dates.map(day => `<span style="text-align:center">${escHtml(day)}</span>`).join('');
  const rows = data.questions.map(row => `<div style="display:grid;grid-template-columns:${columns};gap:6px;align-items:center;padding:7px 0;border-top:1px solid var(--border2)"><span style="font-size:11px;font-weight:800;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(row.question)}">${escHtml(row.question)}</span>${row.values.map(item => {
    if (!item.total) return '<span style="font-size:11px;text-align:center;color:var(--text3)">—</span>';
    const ratio = item.mentioned / item.total;
    return `<span title="${item.mentioned}/${item.total} 次实际爬取提及品牌" style="font-size:11px;text-align:center;padding:4px 2px;border-radius:6px;background:rgba(109,92,247,${0.08 + ratio * 0.22});color:${ratio ? '#312e81' : 'var(--text2)'}">${item.mentioned}/${item.total}</span>`;
  }).join('')}</div>`).join('');
  el.innerHTML = `<div style="overflow-x:auto"><div style="min-width:620px"><div style="display:grid;grid-template-columns:${columns};gap:6px;padding-bottom:6px;font-size:10px;color:var(--text3)"><span>问题</span>${header}</div>${rows}</div></div><div style="font-size:10px;color:var(--text3);margin-top:8px">单元格为“提及品牌的实际爬取次数 / 当日实际爬取次数”；— 表示当天没有该题的采集记录。</div>`;
}

async function loadRecordGroupTrend(groupId) {
  const line = document.getElementById('recordGroupTrend');
  const matrix = document.getElementById('recordGroupQuestionMatrix');
  if (!line || !matrix) return;
  if (!currentClientId || !groupId) {
    line.innerHTML = '<div style="color:var(--text3);font-size:12px">请先选择一个问题组</div>';
    matrix.innerHTML = '<div style="color:var(--text3);font-size:12px">请选择问题组后查看</div>';
    return;
  }
  try {
    const data = await api(`/api/records/group_trend?client_id=${encodeURIComponent(currentClientId)}&group_id=${encodeURIComponent(groupId)}`);
    renderRecordGroupLine(data);
    renderRecordGroupQuestionMatrix(data);
  } catch (error) {
    line.innerHTML = '<div style="color:var(--text3);font-size:12px">问题组提及变化暂不可用</div>';
    matrix.innerHTML = '';
  }
}

async function loadRecordQuestionTrend(question) {
  const el = document.getElementById('recordQuestionTrend');
  if (!el) return;
  if (!currentClientId || !question) {
    el.innerHTML = '<div style="color:var(--text3);font-size:12px">请先选择一个问题</div>';
    return;
  }
  try {
    const data = await api(`/api/records/question_trend?client_id=${encodeURIComponent(currentClientId)}&question=${encodeURIComponent(question)}`);
    const rows = Object.entries(data.trend || {});
    if (!rows.length) {
      el.innerHTML = '<div style="color:var(--text3);font-size:12px">该问题暂无记录</div>';
      return;
    }
    el.innerHTML = rows.map(([platform, items]) => `
      <div style="display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px solid var(--border2)">
        <span style="font-size:12px;font-weight:800;color:#312e81;min-width:70px">${escHtml(CRAWL_PLATFORM_NAMES[platform] || platform)}</span>
        <div style="display:flex;gap:6px;flex-wrap:wrap">${items.map(item =>
          `<span title="${item.records} 条记录" style="font-size:11px;padding:3px 7px;border-radius:8px;background:${item.mentioned ? 'rgba(52,211,153,.12)' : 'rgba(244,114,182,.10)'};color:${item.mentioned ? '#047857' : '#be123c'}">${item.date} ${item.mentioned ? '✓' : '✕'}</span>`
        ).join('')}</div>
      </div>`).join('');
  } catch (error) {
    el.innerHTML = '<div style="color:var(--text3);font-size:12px">提及变化暂不可用</div>';
  }
}

function renderRecordPoolItem(article, retained) {
  const title = escHtml(article.title || '未命名文章');
  const articleTitle = article.url
    ? `<a href="${escHtml(article.url)}" target="_blank" rel="noopener" style="color:#312e81;text-decoration:none">${title}</a>`
    : title;
  return `<div style="padding:8px 0;border-bottom:1px solid var(--border2)">
    <div style="font-size:12px;font-weight:800;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${articleTitle}</div>
    <div style="font-size:11px;color:var(--text3);margin-top:4px">当日被引 ${article.today_count} 次 · 累计 ${article.total_count} 次 · 首次 ${article.first_seen_date}${retained ? ` · 已留存 ${article.retained_days} 天` : ''}</div>
    <div style="font-size:10px;color:var(--text3);margin-top:3px">涉及 AI：${article.ai_platforms.map(platform => escHtml(CRAWL_PLATFORM_NAMES[platform] || platform)).join('、')}</div>
  </div>`;
}

async function loadRecordArticlePool() {
  const el = document.getElementById('recordArticlePool');
  const input = document.getElementById('recordArticlePoolDate');
  if (!el || !currentClientId) return;
  try {
    const selectedDate = input?.value || '';
    const data = await api(`/api/records/article_pool?client_id=${encodeURIComponent(currentClientId)}${selectedDate ? `&date=${selectedDate}` : ''}`);
    if (input && data.date) input.value = data.date;
    if (!data.new_entries?.length && !data.retained?.length) {
      el.innerHTML = '<div style="color:var(--text3);font-size:12px">该日期暂无引用文章</div>';
      return;
    }
    el.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px">
      <div><div style="font-size:12px;font-weight:800;color:var(--pri)">新进</div>${data.new_entries.length ? data.new_entries.map(article => renderRecordPoolItem(article, false)).join('') : '<div style="color:var(--text3);font-size:12px;margin-top:8px">无新进文章</div>'}</div>
      <div><div style="font-size:12px;font-weight:800;color:#047857">留存</div>${data.retained.length ? data.retained.map(article => renderRecordPoolItem(article, true)).join('') : '<div style="color:var(--text3);font-size:12px;margin-top:8px">无留存文章</div>'}</div>
    </div>`;
  } catch (error) {
    el.innerHTML = '<div style="color:var(--text3);font-size:12px">引用文章池暂不可用</div>';
  }
}

async function loadLegacyRecordSourceTrend() {
  const el = document.getElementById('recordSourceTrend');
  if (!el || !currentClientId) return;
  try {
    const sourceTrend = await api(`/api/records/source_trend?client_id=${encodeURIComponent(currentClientId)}`);
    if (!sourceTrend.weeks?.length || !sourceTrend.series?.length) {
      el.innerHTML = '<div style="color:var(--text3);font-size:12px">暂无引用来源数据</div>';
      return;
    }
    const columns = `minmax(90px,1.2fr) repeat(${sourceTrend.weeks.length},minmax(48px,1fr))`;
    const weekHeader = sourceTrend.weeks.map(week => `<span style="text-align:center">${escHtml(week)}</span>`).join('');
    const rows = sourceTrend.series.map(item => `<div style="display:grid;grid-template-columns:${columns};gap:6px;align-items:center;padding:7px 0;border-top:1px solid var(--border2)">
      <span style="font-size:11px;font-weight:800;color:${item.source === '其他' ? 'var(--text2)' : '#312e81'};overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="累计被引 ${item.total_count} 次">${escHtml(item.source)}</span>
      ${item.shares.map(share => {
        const pct = Math.round(share * 100);
        return `<div title="${(share * 100).toFixed(1)}%" style="font-size:10px;text-align:center"><div style="height:5px;background:var(--pri-ll);border-radius:4px;overflow:hidden"><div style="width:${pct}%;height:100%;background:var(--pri)"></div></div><span>${pct}%</span></div>`;
      }).join('')}
    </div>`).join('');
    el.innerHTML = `<div style="overflow-x:auto"><div style="min-width:620px"><div style="display:grid;grid-template-columns:${columns};gap:6px;padding-bottom:6px;font-size:10px;color:var(--text3)"><span>来源站</span>${weekHeader}</div>${rows}</div></div>`;
  } catch (error) {
    el.innerHTML = '<div style="color:var(--text3);font-size:12px">引用来源趋势暂不可用</div>';
  }
}

async function loadRecordSourceTrend() {
  const el = document.getElementById('recordSourceTrend');
  if (!el || !currentClientId) return;
  try {
    const sourceTrend = await api(`/api/records/source_trend?client_id=${encodeURIComponent(currentClientId)}`);
    if (!sourceTrend.dates?.length || !sourceTrend.series?.length) {
      el.innerHTML = '<div style="color:var(--text3);font-size:12px">暂无引用来源数据</div>';
      return;
    }
    const colors = ['#6d5cf7', '#06b6d4', '#f59e0b', '#22c55e', '#f43f5e', '#94a3b8'];
    const legend = sourceTrend.series.map((item, index) => `<span style="display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--text2)"><i style="width:9px;height:9px;border-radius:3px;background:${colors[index % colors.length]}"></i>${escHtml(item.source)}（${item.total_count}）</span>`).join('');
    const bars = sourceTrend.dates.map((day, dateIndex) => `<div style="display:grid;grid-template-columns:88px minmax(220px,1fr);gap:10px;align-items:center;padding:8px 0;border-top:1px solid var(--border2)"><span style="font-size:11px;font-weight:800;color:#312e81">${escHtml(day)}</span><div class="record-source-bar" style="display:flex;height:18px;overflow:hidden;border-radius:6px;background:var(--border2)">${sourceTrend.series.map((item, sourceIndex) => {
      const share = item.shares[dateIndex] || 0;
      return share ? `<span title="${escHtml(item.source)} ${(share * 100).toFixed(1)}%" style="width:${share * 100}%;background:${colors[sourceIndex % colors.length]}"></span>` : '';
    }).join('')}</div></div>`).join('');
    el.innerHTML = `<div style="display:flex;gap:7px 12px;flex-wrap:wrap;margin-bottom:8px">${legend}</div><div>${bars}</div><div style="font-size:10px;color:var(--text3);margin-top:8px">固定显示这 7 个采集日累计被引最多的 5 个来源站，其余合并为“其他”。</div>`;
  } catch (error) {
    el.innerHTML = '<div style="color:var(--text3);font-size:12px">引用来源趋势暂不可用</div>';
  }
}

function renderPlatformStats(stats) {
  const el = document.getElementById('platformStatsBars');
  const note = document.getElementById('platformStatsNote');
  if (note) note.textContent = `共 ${stats.total_refs||0} 条引用`;
  if (!stats.platform_weights?.length) {
    el.innerHTML = '<div style="color:var(--text3);font-size:12px">暂无数据</div>';
  } else {
    el.innerHTML = stats.platform_weights.slice(0,6).map(p => `
      <div class="bar-row">
        <span class="b-lbl">${p.platform}</span>
        <div class="b-track"><div class="b-fill" style="width:${p.pct}%;background:linear-gradient(90deg,var(--pri),var(--pri-l))"></div></div>
        <span class="b-pct" style="color:var(--pri)">${p.pct}%</span>
        <span style="font-size:10px;color:var(--text3);width:60px">均位第${p.avg_position}条</span>
      </div>`).join('');
  }
  // 高频文章
  const artEl = document.getElementById('topArticlesList');
  if (!stats.top_articles?.length) {
    artEl.innerHTML = '<div style="color:var(--text3);font-size:12px">暂无数据</div>';
  } else {
    artEl.innerHTML = stats.top_articles.map((a,i) => `
      <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border2)">
        <span style="width:22px;height:22px;border-radius:8px;background:var(--pri-ll);color:var(--pri);font-size:11px;font-weight:900;display:flex;align-items:center;justify-content:center;flex-shrink:0">${i+1}</span>
        <div style="flex:1;min-width:0">
          <a href="${a.url}" target="_blank" style="font-size:12px;font-weight:700;color:#312e81;text-decoration:none;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${a.title}">${a.title}</a>
          <span class="badge badge-p" style="font-size:9px">${a.platform}</span>
        </div>
        <span style="font-size:11px;font-weight:800;color:var(--pri);flex-shrink:0">被引 ${a.count} 次</span>
      </div>`).join('');
  }
}

const PLATFORM_CLASS = {
  '土巴兔': 'ptag-tubaitu', '新浪家居': 'ptag-sina', '新浪': 'ptag-sina',
  '网易家居': 'ptag-163', '网易': 'ptag-163',
  '今日头条': 'ptag-toutiao', '头条': 'ptag-toutiao',
  '搜狐': 'ptag-sohu', '知乎': 'ptag-zhihu',
  '百度百科': 'ptag-baidu', '百家号': 'ptag-baijiahao',
  '抖音': 'ptag-douyin', '小红书': 'ptag-xiaohongshu',
  '微信公众号': 'ptag-weixin', '微信': 'ptag-weixin',
};

function getPlatformClass(platform) {
  for (const [key, cls] of Object.entries(PLATFORM_CLASS)) {
    if (platform && platform.includes(key)) return cls;
  }
  return 'ptag-default';
}

function checkBrandInTitle(title, brand) {
  if (!brand || !title) return false;
  // 检查标题是否包含品牌关键词（支持品牌名的前几个字）
  const keywords = [brand, brand.slice(0, 2), brand.slice(0, 3)].filter(k => k.length >= 2);
  return keywords.some(k => title.includes(k));
}

function renderRefTag(ref, brand) {
  const pClass = getPlatformClass(ref.platform);
  const hasBrand = checkBrandInTitle(ref.title, brand);
  const cls = hasBrand ? 'ptag ptag-brand' : `ptag ${pClass}`;
  const pos = ref.position ? `<span style="opacity:.6">#${ref.position}</span> ` : '';
  const shortTitle = (ref.title || '').slice(0, 20) + ((ref.title || '').length > 20 ? '…' : '');
  return `<a href="${ref.url || '#'}" target="_blank" class="${cls}" title="${ref.title}">${pos}${ref.platform || '未知'} · ${shortTitle}</a>`;
}

function renderRefTags(refs, brand) {
  if (!refs || !refs.length) return '<span style="font-size:11px;color:var(--text3)">无引用源</span>';
  return refs.map(r => renderRefTag(r, brand)).join('');
}


// ══════════════════════════════════════════════════════
// 资料上传 & 智能主题生成
// ══════════════════════════════════════════════════════
let smartTopics = [];
let latestMaterialPackageMarkdown = '';
let latestMaterialWebSupplementMarkdown = '';
let latestCompetitorUploadMarkdown = '';
let latestCompetitorWebMarkdown = '';
let latestCompetitorMergedMarkdown = '';

function loadMaterialAnalysis() {
  loadMaterials();
  loadMaterialPackageResult();
  loadMaterialWebSupplement();
}

async function loadCompetitorAnalysis() {
  await loadCompetitorEntities();
  await loadCompetitorResult();
}

async function loadMaterials() {
  if (!currentClientId) return;
  const files = await api('/api/materials/' + currentClientId);
  const el = document.getElementById('materialList');
  if (!files.length) {
    el.innerHTML = '<div style="font-size:11px;color:var(--text3)">暂无资料，支持 txt / md / pdf / doc / docx / xlsx</div>';
    return;
  }
  el.innerHTML = files.map(f => `
    <div style="display:flex;align-items:flex-start;gap:10px;padding:9px 0;border-bottom:1px solid var(--border2)">
      <i class="ti ti-file-text" style="color:var(--pri);font-size:16px"></i>
      <div style="flex:1">
        <div style="font-size:12px;font-weight:700;color:var(--text)">${escHtml(f.original_name || f.name)}</div>
        <div style="font-size:10px;color:var(--text3)">${(f.size/1024).toFixed(1)}KB · ${escHtml(f.uploaded || '')} · ${escHtml(f.source || 'upload')}</div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:5px">
          <span class="badge ${materialStatusClass(f)}" style="font-size:9px">${escHtml(materialDisplayStatus(f))}</span>
          ${materialIssueText(f) ? `<span class="badge badge-r" style="font-size:9px">${escHtml(materialIssueText(f))}</span>` : ''}
        </div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
        <button class="btn btn-danger btn-sm" onclick="delMaterial('${encodeURIComponent(f.id || f.name)}')">删除</button>
      </div>
    </div>`).join('');
}

async function uploadMaterial(input) {
  if (!currentClientId) { toast('请先选择客户','err'); return; }
  const files = Array.from(input.files || []);
  if (!files.length) return;
  const formData = new FormData();
  files.forEach(file => formData.append('file', file));
  try {
    const res = await fetch('/api/materials/' + currentClientId + '/upload', {
      method: 'POST', body: formData
    });
    const r = await res.json();
    if (r.error) { toast(r.error,'err'); return; }
    toast(`资料上传成功：${(r.materials||[]).length || 1} 份 ✦`);
    loadMaterials();
  } catch(e) {
    toast('上传失败：' + e.message, 'err');
  }
  input.value = '';
}

async function delMaterial(filename) {
  if (!confirm('确认删除该资料？')) return;
  await api(`/api/materials/${currentClientId}/${filename}`, 'DELETE');
  toast('已删除');
  loadMaterials();
}

function materialUsageButton(file, handlerName) {
  const canUse = !!file?.cache_dir && !materialIssueText(file);
  const next = !file?.confirmed;
  const label = file?.confirmed ? '不使用' : '使用';
  const cls = file?.confirmed ? 'btn btn-o btn-sm' : 'btn btn-p btn-sm';
  const disabled = canUse ? '' : ' disabled title="该资料暂不可用"';
  return `<button class="${cls}"${disabled} onclick="${handlerName}('${encodeURIComponent(file?.id || file?.name)}', ${next})">${label}</button>`;
}

function materialDisplayStatus(file) {
  if (file?.confirmed && file?.cache_dir) return '可用';
  if (file?.diagnostics?.dependency_error) return '解析失败';
  if (file?.status === '解析失败' || file?.status === '文本过少' || file?.status === '疑似扫描件') return file.status;
  return '不可用';
}

function materialStatusClass(file) {
  const status = materialDisplayStatus(file);
  if (status === '可用') return 'badge-g';
  if (status === '解析失败' || status === '文本过少' || status === '疑似扫描件' || status === '不可用') return 'badge-r';
  return 'badge-p';
}

function materialIssueText(file) {
  if (file?.diagnostics?.dependency_error) return '解析依赖缺失';
  if (file?.status === '文本过少') return '正文过少，未参与生成';
  if (file?.status === '疑似扫描件') return '疑似扫描件，未参与生成';
  return '';
}

function renderMaterialPackageResult(result) {
  const box = document.getElementById('materialPackageResult');
  if (!box) return;
  const status = result?.status || result || {};
  const markdown = result?.markdown || '';
  latestMaterialPackageMarkdown = markdown;
  if (!markdown && status.status !== 'failed') {
    box.style.display = 'none';
    box.innerHTML = '';
    return;
  }
  box.style.display = 'block';
  if (status.status === 'failed') {
    box.innerHTML = `<div style="font-size:12px;font-weight:800;color:var(--red)">AI解析失败：${escHtml(status.error || '未知错误')}</div>`;
    return;
  }
  const filter = status.filter || {};
  const reducer = status.reducer || {};
  const output = status.output || {};
  const preview = window.marked ? marked.parse(markdown) : `<pre>${escHtml(markdown)}</pre>`;
  box.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px">
      <div>
        <div style="font-size:13px;font-weight:900;color:#312e81">AI资料解析结果</div>
        <div style="font-size:10px;color:var(--text3);margin-top:3px">
          可读 ${filter.readable_units ?? '-'} · 保留 ${filter.kept_units ?? '-'} · 二阶段输出 ${reducer.reduced_units ?? '-'} · Markdown ${output.markdown_chars ?? markdown.length} 字
        </div>
      </div>
      <div class="acts">
        <button class="btn btn-o btn-sm" onclick="copyMaterialPackageMarkdown()">复制</button>
        <button class="btn btn-p btn-sm" onclick="downloadMaterialPackageMarkdown()">下载.md</button>
      </div>
    </div>
    <div class="report-md" style="max-height:360px;overflow:auto;border:1px solid var(--border2);border-radius:var(--r-sm);padding:12px;background:white">${preview}</div>
  `;
}

async function loadMaterialPackageResult() {
  if (!currentClientId) return;
  const result = await api(`/api/materials/${currentClientId}/package-result`);
  if (result?.ok === false && !result.markdown) {
    renderMaterialPackageResult({});
    return;
  }
  renderMaterialPackageResult(result);
}

async function analyzeMaterialPackage() {
  if (!currentClientId) { toast('请先选择客户','err'); return; }
  const box = document.getElementById('materialPackageResult');
  if (box) {
    box.style.display = 'block';
    box.innerHTML = '<div style="font-size:12px;font-weight:800;color:var(--pri)">AI正在解析资料，请等待...</div>';
  }
  spin('spAnalyzeMaterials', true);
  disableBtn('btnAnalyzeMaterials', true);
  try {
    const result = await api(`/api/materials/${currentClientId}/analyze-package`, 'POST', {});
    if (result?.ok === false || result?.error) {
      renderMaterialPackageResult({status: {status: 'failed', error: result.error || '解析失败'}, markdown: ''});
      toast(result.error || 'AI解析失败', 'err');
      return;
    }
    renderMaterialPackageResult({status: result, markdown: result.markdown || ''});
    toast('AI资料解析完成');
  } catch(e) {
    renderMaterialPackageResult({status: {status: 'failed', error: e.message}, markdown: ''});
    toast('AI解析失败：' + e.message, 'err');
  } finally {
    spin('spAnalyzeMaterials', false);
    disableBtn('btnAnalyzeMaterials', false);
  }
}

function copyMaterialPackageMarkdown() {
  if (!latestMaterialPackageMarkdown) { toast('暂无可复制结果','err'); return; }
  navigator.clipboard.writeText(latestMaterialPackageMarkdown).then(() => toast('资料已复制 ✦'));
}

function downloadMaterialPackageMarkdown() {
  if (!currentClientId || !latestMaterialPackageMarkdown) { toast('暂无可下载结果','err'); return; }
  window.location.href = `/api/materials/${currentClientId}/injection.md`;
}

function renderMaterialWebSupplement(result) {
  const box = document.getElementById('materialWebSupplementResult');
  if (!box) return;
  const markdown = result?.markdown || '';
  latestMaterialWebSupplementMarkdown = markdown;
  if (!markdown && !result?.error) {
    box.style.display = 'none';
    box.innerHTML = '';
    return;
  }
  box.style.display = 'block';
  if (result?.error) {
    box.innerHTML = `<div style="font-size:12px;font-weight:800;color:var(--red)">联网扩展失败：${escHtml(result.error)}</div>`;
    return;
  }
  const preview = window.marked ? marked.parse(markdown) : `<pre>${escHtml(markdown)}</pre>`;
  box.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px">
      <div>
        <div style="font-size:13px;font-weight:900;color:#312e81">AI联网扩展资料</div>
        <div style="font-size:10px;color:var(--text3);margin-top:3px">二阶段生成结果，可复制或下载</div>
      </div>
      <div class="acts">
        <button class="btn btn-o btn-sm" onclick="copyMaterialWebSupplementMarkdown()">复制</button>
        <button class="btn btn-p btn-sm" onclick="downloadMaterialWebSupplementMarkdown()">下载.md</button>
      </div>
    </div>
    <div class="report-md" style="max-height:360px;overflow:auto;border:1px solid var(--border2);border-radius:var(--r-sm);padding:12px;background:white">${preview}</div>
  `;
}

async function loadMaterialWebSupplement() {
  if (!currentClientId) return;
  const result = await api(`/api/materials/${currentClientId}/web-supplement`);
  if (result?.ok === false && !result.markdown) {
    renderMaterialWebSupplement({});
    return;
  }
  renderMaterialWebSupplement(result);
}

function materialWebErrorMessage(error) {
  if (error === 'material_injection_not_found') return '请先完成 AI解析资料，再联网扩展';
  if (error === 'missing_tavily_api_key') return '缺少 Tavily API Key，请先在系统设置中配置';
  return error || '联网扩展失败';
}

async function expandMaterialPackage() {
  if (!currentClientId) { toast('请先选择客户','err'); return; }
  const box = document.getElementById('materialWebSupplementResult');
  if (box) {
    box.style.display = 'block';
    box.innerHTML = '<div style="font-size:12px;font-weight:800;color:var(--pri)">AI正在联网扩展资料，完成后这里只显示补充资料正文...</div>';
  }
  spin('spExpandMaterials', true);
  disableBtn('btnExpandMaterials', true);
  try {
    const result = await api(`/api/materials/${currentClientId}/expand-web`, 'POST', {});
    if (result?.error || result?.ok === false) {
      const message = materialWebErrorMessage(result.error);
      renderMaterialWebSupplement({error: message});
      toast(message, 'err');
      return;
    }
    renderMaterialWebSupplement(result);
    toast('AI联网扩展完成');
  } catch(e) {
    renderMaterialWebSupplement({error: e.message});
    toast('联网扩展失败：' + e.message, 'err');
  } finally {
    spin('spExpandMaterials', false);
    disableBtn('btnExpandMaterials', false);
  }
}

function copyMaterialWebSupplementMarkdown() {
  if (!latestMaterialWebSupplementMarkdown) { toast('暂无可复制结果','err'); return; }
  navigator.clipboard.writeText(latestMaterialWebSupplementMarkdown).then(() => toast('联网扩展资料已复制 ✦'));
}

function downloadMaterialWebSupplementMarkdown() {
  if (!currentClientId || !latestMaterialWebSupplementMarkdown) { toast('暂无可下载结果','err'); return; }
  window.location.href = `/api/materials/${currentClientId}/web-supplement.md`;
}

function competitorNamesFromInput() {
  const value = document.getElementById('competitorNames')?.value || '';
  return value.split(/[\n,，]+/).map(s => s.trim()).filter(Boolean).slice(0, 10);
}

async function loadCompetitorEntities() {
  if (!currentClientId) return competitorNamesFromInput();
  const el = document.getElementById('competitorNames');
  if (!el) return [];
  if (el.dataset.clientId && el.dataset.clientId !== currentClientId) el.value = '';
  el.dataset.clientId = currentClientId;
  if (el.value.trim()) return competitorNamesFromInput();
  try {
    const date = document.getElementById('dailyDate')?.value || new Date().toISOString().slice(0,10);
    const result = await api(`/api/competitors/${currentClientId}/entities?date=${date}`);
    const names = (result.entities || []).map(e => e.name).filter(Boolean);
    if (names.length && !el.value.trim()) el.value = names.join('\n');
    return names;
  } catch(e) {}
  return competitorNamesFromInput();
}

function normalizeCompetitorEntityName(name) {
  return String(name || '').replace(/^#+\s*/, '').replace(/^[\d.、\s-]+/, '').trim();
}

function markdownHeadingTitle(line) {
  const match = String(line || '').match(/^##(?!#)\s+(.+)$/);
  return match ? normalizeCompetitorEntityName(match[1]) : '';
}

function splitMarkdownByHeadings(markdown) {
  const text = String(markdown || '').trim();
  if (!text) return [];
  const sections = [];
  let current = [];
  text.split(/\n/).forEach(line => {
    if (/^##(?!#)\s+\S/.test(line) && current.length) {
      sections.push(current.join('\n').trim());
      current = [line];
    } else {
      current.push(line);
    }
  });
  if (current.length) sections.push(current.join('\n').trim());
  return sections.filter(Boolean);
}

function competitorEntityNamesFromResult(result) {
  const names = [...competitorNamesFromInput()];
  const statusNames = result?.status?.competitors || result?.competitors || [];
  statusNames.forEach(item => names.push(typeof item === 'string' ? item : item?.name));
  [result?.upload_markdown, result?.web_markdown, result?.uploadMarkdown, result?.webMarkdown].forEach(markdown => {
    splitMarkdownByHeadings(markdown).forEach(section => {
      const title = markdownHeadingTitle(section.split(/\n/, 1)[0]);
      if (title && !/(资料|补充|整理包|上传|联网)/.test(title) && title.length <= 40) names.push(title);
    });
  });
  const seen = new Set();
  return names.map(normalizeCompetitorEntityName).filter(name => {
    if (!name || seen.has(name)) return false;
    seen.add(name);
    return true;
  }).slice(0, 20);
}

function extractCompetitorEntitySections(markdown, entityName) {
  const text = String(markdown || '').trim();
  const entity = String(entityName || '').trim().toLowerCase();
  if (!text || !entity) return '';
  const sections = splitMarkdownByHeadings(text);
  const matched = sections.filter(section => section.toLowerCase().includes(entity));
  if (matched.length) return matched.join('\n\n');
  return sections.length <= 1 && text.toLowerCase().includes(entity) ? text : '';
}

function buildCompetitorEntityGroups(entityNames, uploadMarkdown, webMarkdown) {
  const groups = (entityNames || []).map(name => ({
    name,
    upload: extractCompetitorEntitySections(uploadMarkdown, name),
    web: extractCompetitorEntitySections(webMarkdown, name),
  })).filter(group => group.upload || group.web);
  if (!groups.length && (uploadMarkdown || webMarkdown)) {
    groups.push({
      name: '未按竞品实体识别',
      upload: String(uploadMarkdown || '').trim(),
      web: String(webMarkdown || '').trim(),
    });
  }
  return groups;
}

function markdownPreview(markdown) {
  return window.marked ? marked.parse(markdown) : `<pre>${escHtml(markdown)}</pre>`;
}

function formatCompetitorEntityGroupsMarkdown(groups) {
  return (groups || []).map(group => [
    `## ${group.name}`,
    group.upload ? `### 上传资料整理\n\n${group.upload}` : '',
    group.web ? `### 联网资料补充\n\n${group.web}` : '',
  ].filter(Boolean).join('\n\n')).join('\n\n---\n\n');
}

function renderCompetitorEntityGroups(groups) {
  if (!groups.length) return '<div style="font-size:12px;color:var(--text3)">暂无竞品资料结果</div>';
  return groups.map(group => `
    <div style="padding:12px 0;border-top:1px solid var(--border2)">
      <div style="font-size:13px;font-weight:900;color:#312e81;margin-bottom:8px">${escHtml(group.name)}</div>
      ${group.upload ? `
        <div style="font-size:11px;font-weight:900;color:var(--pri);margin:8px 0 6px">上传资料整理</div>
        <div class="report-md" style="max-height:260px;overflow:auto;border:1px solid var(--border2);border-radius:var(--r-sm);padding:12px;background:white">${markdownPreview(group.upload)}</div>
      ` : ''}
      ${group.web ? `
        <div style="font-size:11px;font-weight:900;color:var(--teal);margin:10px 0 6px">联网资料补充</div>
        <button class="btn btn-o btn-sm" onclick="reSearchCompetitorWeb(${JSON.stringify(group.name)})">重新搜索</button>
        <div class="report-md" style="max-height:260px;overflow:auto;border:1px solid var(--border2);border-radius:var(--r-sm);padding:12px;background:white">${markdownPreview(group.web)}</div>
      ` : ''}
    </div>
  `).join('');
}

function renderCompetitorMaterialResult(result) {
  const box = document.getElementById('competitorMaterialResult');
  if (!box) return;
  latestCompetitorUploadMarkdown = result?.upload_markdown || result?.uploadMarkdown || result?.upload || '';
  latestCompetitorWebMarkdown = result?.web_markdown || result?.webMarkdown || result?.markdown || '';
  const groups = buildCompetitorEntityGroups(
    competitorEntityNamesFromResult(result),
    latestCompetitorUploadMarkdown,
    latestCompetitorWebMarkdown,
  );
  latestCompetitorMergedMarkdown = formatCompetitorEntityGroupsMarkdown(groups);
  if (!groups.length && !result?.error) {
    box.style.display = 'none';
    box.innerHTML = '';
    return;
  }
  box.style.display = 'block';
  if (result?.error) {
    box.innerHTML = `<div style="font-size:12px;font-weight:800;color:var(--red)">竞品资料处理失败：${escHtml(result.error)}</div>`;
    return;
  }
  box.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px">
      <div>
        <div style="font-size:13px;font-weight:900;color:#312e81">竞品资料解析结果</div>
        <div style="font-size:10px;color:var(--text3);margin-top:3px">按竞品实体聚合展示；上传资料和联网资料可分开下载</div>
      </div>
      <div class="acts">
        <button class="btn btn-o btn-sm" onclick="copyCompetitorMaterialMarkdown()">复制</button>
        <button class="btn btn-o btn-sm" onclick="downloadCompetitorUploadMarkdown()">下载上传.md</button>
        <button class="btn btn-p btn-sm" onclick="downloadCompetitorWebMarkdown()">下载联网.md</button>
      </div>
    </div>
    ${renderCompetitorEntityGroups(groups)}
  `;
}

async function loadCompetitorResult() {
  if (!currentClientId) return;
  const result = await api(`/api/competitors/${currentClientId}/result`);
  if (result?.ok === false) {
    renderCompetitorMaterialResult({});
    return;
  }
  renderCompetitorMaterialResult(result);
}

async function analyzeCompetitorUpload(input) {
  if (!currentClientId) { toast('请先选择客户','err'); return; }
  const files = Array.from(input.files || []);
  if (!files.length) return;
  const formData = new FormData();
  files.forEach(file => formData.append('file', file));
  formData.append('competitors', competitorNamesFromInput().join('\n'));
  const box = document.getElementById('competitorMaterialResult');
  if (box) {
    box.style.display = 'block';
    box.innerHTML = '<div style="font-size:12px;font-weight:800;color:var(--pri)">AI正在整理上传竞品资料...</div>';
  }
  try {
    const res = await fetch(`/api/competitors/${currentClientId}/analyze-upload`, { method: 'POST', body: formData });
    const result = await res.json();
    if (result?.error || result?.ok === false) {
      renderCompetitorMaterialResult({error: result.error || '竞品资料解析失败'});
      toast(result.error || '竞品资料解析失败', 'err');
      return;
    }
    latestCompetitorUploadMarkdown = result.markdown || '';
    renderCompetitorMaterialResult({upload_markdown: latestCompetitorUploadMarkdown, web_markdown: latestCompetitorWebMarkdown});
    toast('竞品上传资料解析完成');
  } catch(e) {
    renderCompetitorMaterialResult({error: e.message});
    toast('竞品资料解析失败：' + e.message, 'err');
  } finally {
    input.value = '';
  }
}

async function expandCompetitorWeb(force=[]) {
  if (!currentClientId) { toast('请先选择客户','err'); return; }
  const competitors = competitorNamesFromInput();
  if (!competitors.length) { toast('请先填写竞品名称','err'); return; }
  const qualifier = document.getElementById('competitorQualifier')?.value || '';
  const box = document.getElementById('competitorMaterialResult');
  if (box) {
    box.style.display = 'block';
    box.innerHTML = '<div style="font-size:12px;font-weight:800;color:var(--pri)">AI正在联网搜索并整理竞品资料...</div>';
  }
  spin('spCompetitorWeb', true);
  disableBtn('btnCompetitorWeb', true);
  try {
    const result = await api(`/api/competitors/${currentClientId}/expand-web`, 'POST', { competitors, qualifier, force });
    if (result?.error || result?.ok === false) {
      const message = result.error === 'missing_tavily_api_key' ? '缺少 Tavily API Key，请先在系统设置中配置' : (result.error || '竞品联网扩展失败');
      renderCompetitorMaterialResult({error: message});
      toast(message, 'err');
      return;
    }
    latestCompetitorWebMarkdown = result.markdown || '';
    renderCompetitorMaterialResult({upload_markdown: latestCompetitorUploadMarkdown, web_markdown: latestCompetitorWebMarkdown});
    const failed = result.failed?.length ? `；失败：${result.failed.join('、')}` : '';
    toast(`竞品联网资料整理完成；本次名单已覆盖更新${failed}`);
  } catch(e) {
    renderCompetitorMaterialResult({error: e.message});
    toast('竞品联网扩展失败：' + e.message, 'err');
  } finally {
    spin('spCompetitorWeb', false);
    disableBtn('btnCompetitorWeb', false);
  }
}

function reSearchCompetitorWeb(name) {
  if (!name) return;
  expandCompetitorWeb([name]);
}

function copyCompetitorMaterialMarkdown() {
  const markdown = latestCompetitorMergedMarkdown || [latestCompetitorUploadMarkdown, latestCompetitorWebMarkdown].filter(Boolean).join('\n\n---\n\n');
  if (!markdown) { toast('暂无可复制结果','err'); return; }
  copyTextToClipboard(markdown, '竞品资料已复制 ✦');
}

function downloadCompetitorUploadMarkdown() {
  if (!currentClientId || !latestCompetitorUploadMarkdown) { toast('暂无上传资料整理结果','err'); return; }
  window.location.href = `/api/competitors/${currentClientId}/upload.md`;
}

function downloadCompetitorWebMarkdown() {
  if (!currentClientId || !latestCompetitorWebMarkdown) { toast('暂无联网资料整理结果','err'); return; }
  window.location.href = `/api/competitors/${currentClientId}/web.md`;
}

// ══════════════════════════════════════════════════════
// 软文模板管理
// ══════════════════════════════════════════════════════
async function loadTemplates() {
  const cid = currentClientId;
  if (!cid) return;
  const files = await api(`/api/templates/${cid}`);
  const el = document.getElementById('templateList');
  const preview = document.getElementById('templatePreview');
  const status = document.getElementById('templateStatus');
  const detailBtn = document.getElementById('btnTemplateDetail');

  if (!files.length) {
    if (el) el.innerHTML = '<div style="font-size:11px;color:var(--text3)">暂未上传模板，支持 .txt / .md 格式</div>';
    if (status) { status.textContent = '未上传'; status.style.color = 'var(--text3)'; }
    if (detailBtn) detailBtn.style.display = 'none';
    if (preview) preview.style.display = 'none';
    return;
  }

  const active = files.find(f => f.active);
  if (status) {
    status.textContent = '✓ ' + (active?.original || active?.name || '已上传');
    status.style.color = 'var(--teal)';
  }
  if (detailBtn) detailBtn.style.display = 'inline-flex';

  if (el) el.innerHTML = files.map(f => `
    <div style="display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid var(--border2)">
      <i class="ti ti-file-text" style="color:${f.active?'var(--pri)':'var(--text3)'};font-size:15px"></i>
      <div style="flex:1">
        <div style="font-size:11px;font-weight:700;color:${f.active?'#312e81':'var(--text2)'}">
          ${f.original||f.name} ${f.active?'<span class="badge badge-p" style="font-size:9px">当前激活</span>':''}
        </div>
        <div style="font-size:10px;color:var(--text3)">${(f.size/1024).toFixed(1)}KB · ${f.modified}</div>
      </div>
      <button class="btn btn-danger btn-sm" onclick="deleteTemplate('${f.name}')">删除</button>
    </div>`).join('');

  const r = await api(`/api/templates/${cid}/preview`);
  if (r.content && preview) {
    preview.style.display = 'block';
    const tc = document.getElementById('templateContent');
    if (tc) tc.textContent = r.content.slice(0, 500) + (r.content.length > 500 ? '\n...(预览前500字)' : '');
  }
}

function toggleTemplateDetail() {
  const detail = document.getElementById('templateDetail');
  const btn = document.getElementById('btnTemplateDetail');
  if (!detail) return;
  const isHidden = detail.style.display === 'none';
  detail.style.display = isHidden ? 'block' : 'none';
  if (btn) btn.textContent = isHidden ? '收起' : '查看模板';
}

async function loadTemplatesForContent() {
  const cid = currentClientId;
  if (!cid) return;
  const files = await api(`/api/templates/${cid}`);
  const el = document.getElementById('templateListContent');
  if (!el) return;
  if (!files.length) {
    el.innerHTML = '<div style="font-size:11px;color:var(--text3)">暂未上传模板，深度分析时将不使用模板框架</div>';
    return;
  }
  el.innerHTML = files.map(f => `
    <div style="display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid var(--border2)">
      <i class="ti ti-file-description" style="color:${f.active?'var(--pri)':'var(--text3)'};font-size:15px"></i>
      <div style="flex:1">
        <div style="font-size:11px;font-weight:700;color:${f.active?'#312e81':'var(--text2)'}">
          ${f.original||f.name}
          ${f.active?'<span class="badge badge-g" style="font-size:9px">当前激活</span>':''}
        </div>
        <div style="font-size:10px;color:var(--text3)">${(f.size/1024).toFixed(1)}KB · ${f.modified}</div>
      </div>
      <button class="btn btn-danger btn-sm" onclick="deleteTemplateFromContent('${f.name}')">删除</button>
    </div>`).join('');
}

async function uploadTemplateFromContent(input) {
  const cid = currentClientId;
  if (!cid) { toast('请先选择客户', 'err'); return; }
  const file = input.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch(`/api/templates/${cid}/upload`, { method: 'POST', body: formData });
    const r = await res.json();
    if (r.error) { toast(r.error, 'err'); return; }
    toast('模板上传成功 喵～✦');
    loadTemplatesForContent();
    loadTemplates();
  } catch(e) {
    toast('上传失败：' + e.message, 'err');
  }
  input.value = '';
}

async function deleteTemplateFromContent(filename) {
  const cid = currentClientId;
  if (!cid) return;
  if (!confirm('确认删除该模板？')) return;
  await api(`/api/templates/${cid}/${encodeURIComponent(filename)}`, 'DELETE');
  toast('已删除 喵～');
  loadTemplatesForContent();
  loadTemplates();
}

async function uploadTemplate(input) {
  const cid = currentClientId;
  if (!cid) { toast('请先选择客户', 'err'); return; }
  const file = input.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch(`/api/templates/${cid}/upload`, { method: 'POST', body: formData });
    const r = await res.json();
    if (r.error) { toast(r.error, 'err'); return; }
    toast('模板上传成功 喵～✦');
    loadTemplates();
  } catch(e) {
    toast('上传失败：' + e.message, 'err');
  }
  input.value = '';
}

async function deleteTemplate(filename) {
  const cid = currentClientId;
  if (!cid) return;
  if (!confirm('确认删除该模板？')) return;
  await api(`/api/templates/${cid}/${encodeURIComponent(filename)}`, 'DELETE');
  toast('已删除 喵～');
  loadTemplates();
}

// ══════════════════════════════════════════════════════
// 引用情报分析模块
// ══════════════════════════════════════════════════════
function getReferenceDate() {
  const el = document.getElementById('referenceDate');
  if (el && !el.value) el.value = new Date().toISOString().slice(0,10);
  return el?.value || new Date().toISOString().slice(0,10);
}

let referenceAnalyzeJobId = '';
let referenceAnalyzePollTimer = null;
let referenceAnalyzeSmoothTimer = null;
let referenceBackendProgress = 0;
let referenceDisplayProgress = 0;
let referenceBackendStage = 'fetch';
const referenceStageLabels = {
  fetch: '抓取文章',
  filter: '过滤定性',
  anatomy: '逐篇解剖',
  ingest: '入库比对',
  completed: '已完成'
};

function referenceStageText() {
  return referenceStageLabels[referenceBackendStage] || '生成中';
}

function setReferenceProgressVisible(visible) {
  const wrap = document.getElementById('referenceAnalyzeProgress');
  if (wrap) wrap.style.display = visible ? '' : 'none';
}

function renderReferenceProgress(text) {
  const bar = document.getElementById('referenceAnalyzeProgressBar');
  const label = document.getElementById('referenceAnalyzeProgressText');
  if (bar) bar.style.width = `${Math.max(0, Math.min(100, referenceDisplayProgress))}%`;
  if (label && text) label.textContent = text;
}

function stopReferenceAnalyzeTimers() {
  if (referenceAnalyzePollTimer) clearInterval(referenceAnalyzePollTimer);
  if (referenceAnalyzeSmoothTimer) clearInterval(referenceAnalyzeSmoothTimer);
  referenceAnalyzePollTimer = null;
  referenceAnalyzeSmoothTimer = null;
}

function startReferenceSmoothProgress() {
  if (referenceAnalyzeSmoothTimer) clearInterval(referenceAnalyzeSmoothTimer);
  referenceAnalyzeSmoothTimer = setInterval(() => {
    const cap = Math.min(99, referenceBackendProgress + 4);
    if (referenceDisplayProgress < cap) {
      referenceDisplayProgress += Math.min(0.8, cap - referenceDisplayProgress);
      renderReferenceProgress(referenceStageText() + '...');
    }
  }, 200);
}

async function loadReferenceIntelligence() {
  getReferenceDate();
  loadPatternLibrary();
}

async function analyzeReferenceIntelligence() {
  if (!currentClientId) { toast('请先选择客户', 'err'); return; }
  const date = getReferenceDate();
  stopReferenceAnalyzeTimers();
  referenceAnalyzeJobId = '';
  referenceBackendProgress = 3;
  referenceBackendStage = 'fetch';
  referenceDisplayProgress = 0;
  setReferenceProgressVisible(true);
  renderReferenceProgress('抓取文章...');
  startReferenceSmoothProgress();
  spin('spReferenceAnalyze', true);
  disableBtn('btnReferenceAnalyze', true);
  try {
    const data = await api('/api/reference_intelligence/analyze', 'POST', {
      client_id: currentClientId,
      date
    });
    if (data.error) {
      toast(data.message || data.error, 'err');
      stopReferenceAnalyzeTimers();
      setReferenceProgressVisible(false);
      spin('spReferenceAnalyze', false);
      disableBtn('btnReferenceAnalyze', false);
      return;
    }
    referenceAnalyzeJobId = data.job_id || '';
    referenceBackendProgress = Number(data.progress || 3);
    referenceBackendStage = data.stage || 'fetch';
    pollReferenceAnalysisStatus();
    referenceAnalyzePollTimer = setInterval(pollReferenceAnalysisStatus, 1500);
  } catch(e) {
    toast('生成失败：' + e.message, 'err');
    stopReferenceAnalyzeTimers();
    setReferenceProgressVisible(false);
    spin('spReferenceAnalyze', false);
    disableBtn('btnReferenceAnalyze', false);
  }
}

async function pollReferenceAnalysisStatus() {
  if (!referenceAnalyzeJobId) return;
  try {
    const data = await api(`/api/reference_intelligence/analyze_status?job_id=${referenceAnalyzeJobId}`);
    referenceBackendProgress = Number(data.progress || referenceBackendProgress || 0);
    referenceBackendStage = data.stage || referenceBackendStage;
    if (data.status === 'completed') {
      referenceBackendProgress = 100;
      referenceDisplayProgress = 100;
      renderReferenceProgress('已完成');
      stopReferenceAnalyzeTimers();
      spin('spReferenceAnalyze', false);
      disableBtn('btnReferenceAnalyze', false);
      await loadReferenceIntelligence();
      toast('引用情报已生成');
      setTimeout(() => setReferenceProgressVisible(false), 800);
    } else if (data.status === 'failed') {
      stopReferenceAnalyzeTimers();
      renderReferenceProgress('生成失败');
      spin('spReferenceAnalyze', false);
      disableBtn('btnReferenceAnalyze', false);
      toast(data.error || '生成失败，请稍后重试或联系技术排查', 'err');
    } else if (data.status === 'canceled') {
      stopReferenceAnalyzeTimers();
      renderReferenceProgress('已终止');
      spin('spReferenceAnalyze', false);
      disableBtn('btnReferenceAnalyze', false);
      toast('已终止生成');
    } else {
      renderReferenceProgress(referenceStageText() + '...');
    }
  } catch(e) {
    stopReferenceAnalyzeTimers();
    renderReferenceProgress('生成失败');
    spin('spReferenceAnalyze', false);
    disableBtn('btnReferenceAnalyze', false);
    toast('生成失败：' + e.message, 'err');
  }
}

async function cancelReferenceAnalysis() {
  if (!referenceAnalyzeJobId) return;
  try {
    const data = await api('/api/reference_intelligence/analyze_cancel', 'POST', {
      job_id: referenceAnalyzeJobId
    });
    referenceBackendProgress = Number(data.progress || referenceBackendProgress || 0);
    renderReferenceProgress('已终止');
  } catch(e) {
    toast('终止失败：' + e.message, 'err');
  }
}

// ══════════════════════════════════════════════════════
// 当日数据整理模块
// ══════════════════════════════════════════════════════
function patternLibraryStatusLabel(status) {
  return ({candidate: '候选', active: '已转正', retired: '已退役'})[status] || status || '未知';
}

function patternLibraryDomainCount(sources) {
  const domains = new Set();
  (sources || []).forEach(source => {
    try {
      const hostname = new URL(source.url || '').hostname;
      if (hostname) domains.add(hostname);
    } catch (_) {}
  });
  return domains.size;
}

function patternLibraryRiskMarks(entry) {
  return [...new Set((entry.sources || []).flatMap(source => source.risk_marks || []).filter(Boolean))];
}

function patternLibrarySafeUrl(url) {
  try {
    const parsed = new URL(String(url || ''));
    return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : '';
  } catch (_) {
    return '';
  }
}

function patternLibraryEmpty(message) {
  return `<div class="empty"><i class="ti ti-books"></i><p>${escHtml(message)}</p></div>`;
}

function renderPatternLibraryDetail(entry) {
  const payload = entry.payload || {};
  if (entry.kind === 'skeleton') {
    const sections = Array.isArray(payload.sections) ? payload.sections : [];
    return `
      ${sections.length ? `<div class="pattern-detail-block"><strong>章节序列</strong><ol>${sections.map(section => `<li>${escHtml(section)}</li>`).join('')}</ol></div>` : ''}
      ${payload.signature ? `<div class="pattern-detail-block"><strong>识别特征</strong><p>${escHtml(payload.signature)}</p></div>` : ''}
      ${payload.risk_notes ? `<div class="pattern-detail-block pattern-risk-note"><strong>风险提示</strong><p>${escHtml(payload.risk_notes)}</p></div>` : ''}`;
  }
  if (entry.kind === 'module') {
    const storedExamples = Array.isArray(payload.excerpts) ? payload.excerpts : [];
    const examples = storedExamples.length ? storedExamples : (payload.excerpt ? [{excerpt: payload.excerpt, excerpt_verified: payload.excerpt_verified}] : []);
    return `
      ${payload.pattern ? `<div class="pattern-detail-block"><strong>套路描述</strong><p>${escHtml(payload.pattern)}</p></div>` : ''}
      ${examples.length ? `<div class="pattern-detail-block"><strong>摘录例句</strong>${examples.map(example => `<blockquote>${escHtml(example.excerpt || '')}${example.excerpt_verified ? '<span class="pattern-verified">原文已核验</span>' : ''}</blockquote>`).join('')}</div>` : ''}
      ${payload.risk_notes ? `<div class="pattern-detail-block pattern-risk-note"><strong>风险提示</strong><p>${escHtml(payload.risk_notes)}</p></div>` : ''}`;
  }
  const labels = Array.isArray(payload.raw_labels) ? payload.raw_labels : [payload.feature || entry.name].filter(Boolean);
  return `<div class="pattern-detail-block"><strong>归并前原始措辞</strong><div class="pattern-label-list">${labels.map(label => `<span>${escHtml(label)}</span>`).join('')}</div></div>`;
}

function renderPatternLibrarySources(sources) {
  if (!sources.length) return '';
  return `<div class="pattern-sources"><strong>来源</strong>${sources.map(source => {
    const url = patternLibrarySafeUrl(source.url);
    const title = escHtml(source.title || source.url || '未命名文章');
    const risks = Array.isArray(source.risk_marks) ? source.risk_marks : [];
    const aliases = Array.isArray(source.alias_urls) ? source.alias_urls : [];
    return `<div class="pattern-source">
      <div>${url ? `<a href="${escHtml(url)}" target="_blank" rel="noopener noreferrer">${title}</a>` : title}</div>
      <div class="pattern-source-meta">引用 ${Number(source.citation_count || 0)} 次${risks.length ? ` · ${escHtml(risks.join('、'))}` : ''}${aliases.length ? ` · 同稿 ${aliases.length} 个 URL` : ''}</div>
    </div>`;
  }).join('')}</div>`;
}

function renderPatternLibraryEntry(entry, canWrite = false) {
  const sources = Array.isArray(entry.sources) ? entry.sources : [];
  const risks = patternLibraryRiskMarks(entry);
  const allSourcesRisky = sources.length > 0 && sources.every(source => (source.risk_marks || []).length > 0);
  const action = entry.status === 'candidate'
    ? {status: 'active', label: '转正', className: 'btn btn-p btn-sm'}
    : entry.status === 'active'
      ? {status: 'retired', label: '退役', className: 'btn btn-danger btn-sm'}
      : {status: 'candidate', label: '恢复为候选', className: 'btn btn-o btn-sm'};
  const moduleType = entry.kind === 'module' && entry.payload?.type ? `<span class="badge badge-p">${escHtml(entry.payload.type)}</span>` : '';
  return `<article class="pattern-entry ${entry.status === 'retired' ? 'is-retired' : ''}">
    <div class="pattern-entry-top">
      <div class="pattern-entry-title"><span>${escHtml(entry.name || '未命名条目')}</span>${moduleType}</div>
      <div class="pattern-entry-actions">
        <span class="pattern-status status-${escHtml(entry.status)}">${escHtml(patternLibraryStatusLabel(entry.status))}</span>
        ${canWrite ? `<button class="${action.className}" data-pattern-entry="${escHtml(entry.id)}" data-pattern-status="${action.status}">${action.label}</button>` : ''}
      </div>
    </div>
    <div class="pattern-entry-meta">
      <span>证据 ${Number(entry.evidence_count || 0)}</span>
      <span>来源域名 ${patternLibraryDomainCount(sources)}</span>
      ${risks.length ? risks.map(risk => `<span class="pattern-risk-chip">${escHtml(risk)}</span>`).join('') : '<span>无风险标记</span>'}
    </div>
    ${entry.status === 'candidate' && allSourcesRisky ? '<p class="pattern-risk-warning">全部来源带风险标记，请确认结构可复用后再转正。</p>' : ''}
    <details class="pattern-entry-details">
      <summary>查看详情与来源</summary>
      ${renderPatternLibraryDetail(entry)}
      ${renderPatternLibrarySources(sources)}
    </details>
  </article>`;
}

function renderPatternLibraryEntries(data) {
  const entries = Array.isArray(data?.entries) ? data.entries : [];
  const byKind = {
    skeleton: entries.filter(entry => entry.kind === 'skeleton'),
    module: entries.filter(entry => entry.kind === 'module'),
    checklist: entries.filter(entry => entry.kind === 'checklist'),
  };
  const counts = entries.reduce((total, entry) => {
    total[entry.status] = (total[entry.status] || 0) + 1;
    return total;
  }, {candidate: 0, active: 0, retired: 0});
  const summary = document.getElementById('patternLibrarySummary');
  if (summary) {
    summary.innerHTML = [
      ['条目总数', entries.length, 'total'], ['候选', counts.candidate, 'candidate'],
      ['已转正', counts.active, 'active'], ['已退役', counts.retired, 'retired'],
    ].map(([label, value, type]) => `<div class="pattern-library-stat stat-${type}"><span>${label}</span><strong>${value}</strong></div>`).join('');
  }
  const recent = data?.recent_ingest;
  const ingest = document.getElementById('patternLibraryIngest');
  if (ingest) {
    ingest.textContent = recent
      ? `最近入库：${recent.cards} 张卡，新建 ${recent.created} / 归并 ${recent.matched}，错误 ${recent.errors}${recent.date ? `（${recent.date}）` : ''}`
      : '暂无 stage2 入库报告。';
  }
  const groups = [
    ['Skeletons', 'SkeletonCount', byKind.skeleton, '暂无骨架条目'],
    ['Modules', 'ModuleCount', byKind.module, '暂无段落模式条目'],
    ['Checklists', 'ChecklistCount', byKind.checklist, '暂无引用友好清单条目'],
  ];
  groups.forEach(([listSuffix, countSuffix, group, empty]) => {
    const list = document.getElementById(`patternLibrary${listSuffix}`);
    const count = document.getElementById(`patternLibrary${countSuffix}`);
    if (count) count.textContent = `${group.length} 条`;
    if (list) list.innerHTML = group.length ? group.map(entry => renderPatternLibraryEntry(entry, Boolean(data?.can_write))).join('') : patternLibraryEmpty(empty);
  });
  document.querySelectorAll('[data-pattern-status]').forEach(button => {
    button.addEventListener('click', () => updatePatternLibraryStatus(button.dataset.patternEntry, button.dataset.patternStatus));
  });
}

function renderPatternLibraryUnavailable(message) {
  const content = document.getElementById('patternLibraryContent');
  const summary = document.getElementById('patternLibrarySummary');
  if (summary) summary.innerHTML = '';
  if (content) content.innerHTML = patternLibraryEmpty(message);
}

async function loadPatternLibrary() {
  const scopeSelect = document.getElementById('patternLibraryScope');
  if (!scopeSelect) return;
  try {
    const data = await api('/api/pattern-library/scopes');
    if (data.error) throw new Error(data.error);
    const scopes = Array.isArray(data.scopes) ? data.scopes : [];
    const previous = scopeSelect.value;
    scopeSelect.innerHTML = scopes.map(item => `<option value="${escHtml(item.scope)}">${escHtml(item.scope)}（${Number(item.entry_count || 0)} 条）</option>`).join('');
    if (!scopes.length) {
      renderPatternLibraryUnavailable('暂无写法库条目');
      return;
    }
    scopeSelect.value = scopes.some(item => item.scope === previous) ? previous : scopes[0].scope;
    await loadPatternLibraryEntries();
  } catch (error) {
    renderPatternLibraryUnavailable(`写法库加载失败：${error.message}`);
  }
}

async function loadPatternLibraryEntries() {
  const scopeSelect = document.getElementById('patternLibraryScope');
  const scope = scopeSelect?.value;
  if (!scope) return;
  try {
    const data = await api(`/api/pattern-library/entries?scope=${encodeURIComponent(scope)}`);
    if (data.error) throw new Error(data.error);
    renderPatternLibraryEntries(data);
  } catch (error) {
    renderPatternLibraryUnavailable(`写法库加载失败：${error.message}`);
  }
}

async function updatePatternLibraryStatus(entryId, status) {
  const scope = document.getElementById('patternLibraryScope')?.value;
  if (!scope || !entryId) return;
  try {
    const data = await api('/api/pattern-library/status', 'POST', {scope, entry_id: entryId, status});
    if (data.error) throw new Error(data.error);
    toast(`已更新为${patternLibraryStatusLabel(status)}`);
    await loadPatternLibraryEntries();
  } catch (error) {
    toast(`状态更新失败：${error.message}`, 'err');
  }
}

let dailySelectedIds = new Set();


const DAILY_PAGE_SIZE = 20;

function dailyRecordPlatformName(r) {
  const platform = (r.source_platform || '').trim();
  return platform ? (CRAWL_PLATFORM_NAMES[platform] || platform) : '未知平台';
}

function renderDailyRecord(r) {
  const platformName = dailyRecordPlatformName(r);
  const brandMentionBadge = r.brand_mentioned ? '<span class="badge badge-g">品牌已提及</span>' : '';
  const div = document.createElement('div');
  div.id = 'rec-' + r.id;
  div.style.cssText = 'display:flex;align-items:flex-start;gap:10px;padding:10px;background:rgba(255,255,255,.8);border:1.5px solid var(--border2);border-radius:var(--r-sm);margin-bottom:6px';
  div.innerHTML = `
    <input type="checkbox" style="margin-top:3px;width:auto;accent-color:var(--pri)" onchange="toggleDailySelect('${r.id}',this.checked)" id="chk-${r.id}">
    <div style="flex:1;min-width:0">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;flex-wrap:wrap">
        <span style="font-size:12px;font-weight:800;color:#312e81">${r.question}</span>
        <span class="badge badge-p">${escHtml(platformName)}</span>
        ${brandMentionBadge}
        ${r.round > 1 ? `<span class="badge badge-pk">第${r.round}次</span>` : ''}
        <span style="font-size:10px;color:var(--text3);margin-left:auto">${r.crawl_time||''}</span>
      </div>
      <div style="font-size:11px;color:var(--text2);margin-bottom:6px;max-height:40px;overflow:hidden">${(r.answer||'').slice(0,120)}${(r.answer||'').length>120?'...':''}</div>
      <div style="display:flex;gap:4px;flex-wrap:wrap">${renderRefTags(r.refs||[], currentBrand)}</div>
    </div>
    <button class="btn btn-danger btn-sm" style="flex-shrink:0" onclick="deleteDailyRecord('${r.id}')">删除</button>`;
  return div;
}

function renderDailyRecordPage(el) {
  const records = window._dailyRecords || [];
  const page = window._dailyPage || 0;
  const start = page * DAILY_PAGE_SIZE;
  const items = records.slice(start, start + DAILY_PAGE_SIZE);
  // 用 DocumentFragment 批量插入，减少重绘
  const frag = document.createDocumentFragment();
  items.forEach(r => frag.appendChild(renderDailyRecord(r)));
  // 移除旧的加载提示
  const oldLoader = el.querySelector('#dailyLoader');
  if (oldLoader) oldLoader.remove();
  el.appendChild(frag);
  // 还有更多时加载提示
  if (start + DAILY_PAGE_SIZE < records.length) {
    const loader = document.createElement('div');
    loader.id = 'dailyLoader';
    loader.style.cssText = 'text-align:center;padding:12px;color:var(--text3);font-size:11px;font-weight:700';
    loader.textContent = `已加载 ${start + items.length} / ${records.length} 条，继续滚动加载更多...`;
    el.appendChild(loader);
  }
}

function onDailyScroll() {
  const mainEl = document.querySelector('.main');
  const el = document.getElementById('dailyRecordList');
  if (!mainEl || !el) return;
  const records = window._dailyRecords || [];
  const page = window._dailyPage || 0;
  if ((page + 1) * DAILY_PAGE_SIZE >= records.length) return;
  // 距底部100px时触发加载
  const scrollBottom = mainEl.scrollTop + mainEl.clientHeight;
  const listBottom = el.offsetTop + el.offsetHeight;
  if (scrollBottom >= listBottom - 100) {
    window._dailyPage = page + 1;
    renderDailyRecordPage(el);
  }
}

function loadDailyPage() {
  const el = document.getElementById('dailyDate');
  if (el && !el.value) el.value = new Date().toISOString().slice(0,10);
  if (!currentClientId) {
    document.getElementById('dailyRecordList').innerHTML = '<div class="info-banner">请先在右上角选择客户，再查看当日数据 喵～</div>';
    return;
  }
  loadDailyGroupFilter();  // 加载问题组筛选器
  loadDailyData();
}

async function loadDailyGroupFilter() {
  // 加载问题组到筛选器（切换客户时调用）
  const sel = document.getElementById('dailyGroupFilter');
  if (!sel || !currentClientId) return;
  try {
    const groups = await api(`/api/groups/${currentClientId}`);
    sel.innerHTML = '<option value="">全部问题组</option>' +
      (groups || []).map(g => `<option value="${g.id}">${g.name}</option>`).join('');
  } catch(e) {}
}

async function loadDailyData() {
  if (!currentClientId) return;
  const date = document.getElementById('dailyDate').value || new Date().toISOString().slice(0,10);
  const groupId = document.getElementById('dailyGroupFilter')?.value || '';

  // 加载记录列表（带问题组过滤）
  const allRecords = await api(`/api/daily/records?client_id=${currentClientId}&date=${date}&platform=${currentPlatform}${groupId ? '&group_id='+groupId : ''}`);
  const taskId = updateTaskFilterOptions('dailyTaskFilter', allRecords, true);
  const records = taskId ? allRecords.filter(r => r.task_id === taskId) : allRecords;
  document.getElementById('dailyRecordCount').textContent = records.length + ' 条';
  dailySelectedIds.clear();
  updateBatchDeleteBtn();

  // 更新KPI
  const mentioned = records.filter(r => r.brand_mentioned).length;
  const avgScore = records.length ? Math.round(records.reduce((s,r) => s+(r.geo_score||0), 0)/records.length*10)/10 : 0;
  const totalRefs = records.reduce((s,r) => s+(r.ref_count||0), 0);
  document.getElementById('dk-total').textContent = records.length;
  document.getElementById('dk-mention').textContent = records.length ? Math.round(mentioned/records.length*100) + '%' : '--%';
  document.getElementById('dk-score').textContent = avgScore || '--';
  document.getElementById('dk-refs').textContent = totalRefs;

  // 渲染记录列表
  const el = document.getElementById('dailyRecordList');
  if (!records.length) {
    el.innerHTML = '<div class="empty"><i class="ti ti-database"></i><p>当日暂无数据</p></div>';
    window._dailyRecords = [];
    window._dailyPage = 0;
    document.getElementById('dailyTopArticles').innerHTML = '<div style="color:var(--text3);font-size:12px">暂无数据</div>';
    renderDailyInsights({ai_platforms:[], mentioned_entities:[], top_ref_platforms:[]});
    renderDailyEntityStatus({status:'not_found'});
    return;
  }
  // 分页懒加载：只渲染前20条，滚动到底自动加载
  window._dailyRecords = records;
  window._dailyPage = 0;
  el.innerHTML = '';
  renderDailyRecordPage(el);

  // 监听滚动（绑定到main容器）
  const mainEl = document.querySelector('.main');
  if (mainEl) {
    mainEl.onscroll = null;
    mainEl.addEventListener('scroll', onDailyScroll, { passive: true });
  }

  // 加载高频引用文章（来源平台分布已合并到 AI 平台分类）
  loadDailyTopArticles(date, groupId, taskId);
  loadDailyInsights(date, groupId, taskId);
  loadDailyEntityStatus(date, taskId);
}

async function loadDailyInsights(date, groupId, taskId='') {
  try {
    const gParam = groupId ? `&group_id=${groupId}` : '';
    const taskParam = taskId ? `&task_id=${encodeURIComponent(taskId)}` : '';
    const r = await api(`/api/daily/insights?client_id=${currentClientId}&date=${date}&platform=${currentPlatform}${gParam}${taskParam}`);
    renderDailyInsights(r.insights || {});
  } catch(e) {
    renderDailyInsights({ai_platforms:[], mentioned_entities:[], top_ref_platforms:[]});
  }
}

function renderDailyEntityStatus(status) {
  const el = document.getElementById('dailyEntityStatus');
  if (!el) return;
  const map = {
    queued: ['实体识别排队中', 'var(--amber)'],
    running: ['实体识别处理中', 'var(--pri)'],
    completed: [`实体识别已完成${status?.changed !== undefined ? ` · 更新 ${status.changed} 条` : ''}`, 'var(--teal)'],
    failed: [`实体识别失败${status?.error ? `：${status.error}` : ''}`, 'var(--red)'],
    skipped: ['实体识别已跳过', 'var(--text3)'],
    not_found: ['暂无实体识别任务', 'var(--text3)'],
    unknown: ['实体识别状态未知', 'var(--text3)']
  };
  const [label, color] = map[status?.status || 'unknown'] || map.unknown;
  el.textContent = label;
  el.style.color = color;
}

async function loadDailyEntityStatus(date, taskId='') {
  try {
    const taskParam = taskId ? `&task_id=${encodeURIComponent(taskId)}` : '';
    const status = await api(`/api/daily/entity_status?client_id=${currentClientId}&date=${date}${taskParam}`);
    renderDailyEntityStatus(status);
  } catch(e) {
    renderDailyEntityStatus({status:'unknown', error:e.message});
  }
}

async function generateDailyEntities() {
  if (!currentClientId) { toast('请先选择客户', 'err'); return; }
  const btn = document.getElementById('dailyEntityGenerateBtn');
  const oldHtml = btn ? btn.innerHTML : '';
  const date = document.getElementById('dailyDate').value || new Date().toISOString().slice(0,10);
  const groupId = document.getElementById('dailyGroupFilter')?.value || '';
  const taskId = document.getElementById('dailyTaskFilter')?.value || '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<i class="ti ti-loader-2"></i> 生成中';
  }
  try {
    const r = await api('/api/daily/entities/generate', 'POST', {
      client_id: currentClientId,
      date,
      platform: currentPlatform,
      group_id: groupId,
      task_id: taskId,
    });
    if (r.error) { toast(r.message || r.error, 'err'); return; }
    renderDailyEntityStatus(r.entity_normalize || {status:'queued'});
    toast('已开始生成竞品提及');
  } catch(e) {
    toast('生成失败：' + e.message, 'err');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = oldHtml;
    }
  }
}

function renderDailyEntityDeleteButton(entityName) {
  const encodedName = encodeURIComponent(entityName || '');
  return `<button class="btn btn-danger btn-sm" title="从当前筛选范围删除该实体" onclick="deleteDailyEntity(decodeURIComponent('${encodedName}'))">删除</button>`;
}

async function deleteDailyEntity(entityName) {
  if (!currentClientId || !entityName) return;
  if (!confirm(`确认从当前竞品展示范围删除「${entityName}」？\n原始回答不会删除，只移除这个AI识别实体。`)) return;
  const date = document.getElementById('dailyDate').value || new Date().toISOString().slice(0,10);
  const groupId = document.getElementById('dailyGroupFilter')?.value || '';
  const taskId = document.getElementById('dailyTaskFilter')?.value || '';
  try {
    const r = await api('/api/daily/entities/delete', 'POST', {
      client_id: currentClientId,
      date,
      platform: currentPlatform,
      group_id: groupId,
      task_id: taskId,
      name: entityName
    });
    if (!r.ok) { toast(r.error || '删除失败', 'err'); return; }
    toast(`已删除 ${r.removed || 0} 处实体识别结果`);
    loadDailyData();
  } catch(e) {
    toast('删除失败：' + e.message, 'err');
  }
}

function renderDailyInsights(insights) {
  const platforms = insights.ai_platforms || [];
  const entities = insights.mentioned_entities || [];
  const note = document.getElementById('dailyAiPlatformNote');
  if (note) note.textContent = `共 ${insights.total_records || 0} 条记录`;
  if (typeof insights.mention_rate !== 'undefined') {
    document.getElementById('dk-mention').textContent = `${Math.round(insights.mention_rate)}%`;
  }

  const aiEl = document.getElementById('dailyAiPlatformCompare');
  if (aiEl) {
    aiEl.innerHTML = platforms.length ? platforms.map(p => {
      const refRows = (p.ref_platforms || []).slice(0, 6).map(rp => `
        <div style="display:flex;align-items:center;gap:6px;margin-top:5px">
          <span style="width:64px;font-size:10px;color:var(--text2);font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(rp.platform)}">${escHtml(rp.platform)}</span>
          <div style="flex:1;height:6px;background:rgba(167,139,250,.12);border-radius:20px;overflow:hidden">
            <div style="height:100%;width:${Math.min(100, rp.pct || 0)}%;background:linear-gradient(90deg,var(--pri),var(--teal));border-radius:20px"></div>
          </div>
          <span style="width:54px;text-align:right;font-size:10px;color:var(--pri);font-weight:800">×${escHtml(rp.count)}</span>
        </div>`).join('');
      return `
      <div style="padding:9px 0;border-bottom:1px solid var(--border2)">
        <div style="display:grid;grid-template-columns:72px 1fr 70px 48px;gap:8px;align-items:center">
          <span style="font-size:12px;font-weight:900;color:#312e81">${escHtml(p.platform_name || p.source_platform)}</span>
          <span style="font-size:11px;color:var(--text2)">记录 ${escHtml(p.total_records)} · 引用 ${escHtml(p.total_refs)}</span>
          <span class="badge badge-g" style="text-align:center">${escHtml(p.brand_mentions)} 品牌提及</span>
          <span style="font-size:11px;font-weight:800;color:var(--pri);text-align:right">${escHtml(p.mention_rate)}%</span>
        </div>
        <div style="font-size:10px;color:var(--text3);font-weight:800;margin:8px 0 2px">来源平台分布</div>
        ${refRows || '<div style="font-size:10px;color:var(--text3);margin-top:5px">暂无引用来源</div>'}
      </div>`;
    }).join('') : '<div style="color:var(--text3);font-size:12px">暂无平台数据</div>';
  }

  const entityEl = document.getElementById('dailyEntityMentions');
  if (entityEl) {
    entityEl.innerHTML = entities.length ? entities.slice(0, 12).map((e, i) => `
      <div style="display:flex;align-items:flex-start;gap:8px;padding:7px 0;border-bottom:1px solid var(--border2)">
        <span style="width:20px;height:20px;border-radius:6px;background:var(--pink-l);color:var(--pink);font-size:10px;font-weight:900;display:flex;align-items:center;justify-content:center;flex-shrink:0">${i+1}</span>
        <div style="flex:1;min-width:0">
          <div style="font-size:12px;font-weight:900;color:#312e81">${escHtml(e.name)} <span class="badge badge-p" style="font-size:9px">${escHtml(e.type || '实体')}</span></div>
          <div style="font-size:10px;color:var(--text3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escHtml((e.evidence_samples || [])[0] || '')}</div>
        </div>
        <span style="font-size:12px;font-weight:900;color:var(--pink);flex-shrink:0">×${escHtml(e.count)}</span>
        ${renderDailyEntityDeleteButton(e.name)}
      </div>`).join('') : '<div style="color:var(--text3);font-size:12px">暂无竞品/门店提及数据。可先运行实体抽取 dry-run，确认后再入库。</div>';
  }
}

function renderDailyTopArticleRows(articles, totalRecords) {
  return (articles || []).map((a,i) => {
    const mentionRate = totalRecords > 0 ? Math.round(a.count / totalRecords * 100) : 0;
    const aiLabels = (a.ai_platforms || []).map(pid => CRAWL_PLATFORM_NAMES[pid] || pid).join(' / ');
    const compStatus = a.competitor_match_status || '';
    const compEntities = (a.competitor_matched_entities || []).join('、');
    const compLabel = a.competitor_match_label || (
      compStatus === 'matched' ? '提到目标竞品' :
      compStatus === 'not_matched' ? '未提到目标竞品' :
      compStatus === 'unconfirmed' ? '正文未确认' : ''
    );
    const compBadgeClass = compStatus === 'matched' ? 'badge-g' : compStatus === 'not_matched' ? 'badge-r' : 'badge-a';
    const compBadge = compLabel ? `<span class="badge ${compBadgeClass}" style="font-size:9px">${escHtml(compLabel)}${compEntities ? `：${escHtml(compEntities)}` : ''}</span>` : '';
    const rateColor = mentionRate >= 50 ? 'var(--teal)' : mentionRate >= 25 ? 'var(--amber)' : 'var(--text3)';
    return `
      <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border2)">
        <span style="width:20px;height:20px;border-radius:6px;background:var(--pri-ll);color:var(--pri);font-size:10px;font-weight:900;display:flex;align-items:center;justify-content:center;flex-shrink:0">${i+1}</span>
        <div style="flex:1;min-width:0">
          <a href="${escHtml(a.url||'#')}" target="_blank" style="font-size:11px;font-weight:700;color:#312e81;text-decoration:none;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(a.title)}">${escHtml(a.title)}</a>
          <div style="display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin-top:3px">
            <span class="badge badge-p" style="font-size:9px">${escHtml(a.platform)}</span>
            ${aiLabels ? `<span class="badge badge-g" style="font-size:9px">AI：${escHtml(aiLabels)}</span>` : ''}
            ${compBadge}
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:5px;flex-shrink:0">
          <span style="font-size:10px;font-weight:700;color:${rateColor};min-width:34px;text-align:right">${mentionRate}%</span>
          <span style="font-size:11px;font-weight:800;color:var(--pri)">×${a.count}</span>
        </div>
      </div>`;
  }).join('');
}

async function loadDailyTopArticles(date, groupId, taskId='') {
  try {
    const gParam = groupId ? `&group_id=${groupId}` : '';
    const taskParam = taskId ? `&task_id=${encodeURIComponent(taskId)}` : '';
    const stats = await api(`/api/daily/ref_stats?client_id=${currentClientId}&date=${date}&platform=${currentPlatform}${gParam}${taskParam}`);
    const totalRecords = stats.total_records || 0;

    // 高频文章（含提及率）
    const ta = document.getElementById('dailyTopArticles');
    if (stats.top_articles_by_ai?.length) {
      const groupsHtml = stats.top_articles_by_ai.map(group => {
        const articles = (group.top_articles || []).slice(0, 12);
        if (!articles.length) return '';
        const groupTotal = group.total_records || totalRecords;
        return `
          <div style="padding:8px 0 12px;border-bottom:1.5px solid var(--border2);margin-bottom:8px">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
              <span style="font-size:12px;font-weight:900;color:#312e81">${escHtml(group.platform_name || group.source_platform)} 高频引用文章 Top12</span>
              <span style="font-size:10px;color:var(--text3);font-weight:800">记录 ${escHtml(groupTotal)}</span>
            </div>
            ${renderDailyTopArticleRows(articles, groupTotal)}
          </div>`;
      }).join('');
      ta.innerHTML = groupsHtml || '<div style="color:var(--text3);font-size:12px">暂无数据</div>';
    } else if (stats.top_articles?.length) {
      ta.innerHTML = renderDailyTopArticleRows(stats.top_articles.slice(0,20), totalRecords);
    } else {
      ta.innerHTML = '<div style="color:var(--text3);font-size:12px">暂无数据</div>';
    }
  } catch(e) {
    document.getElementById('dailyTopArticles').innerHTML = '<div style="color:var(--text3);font-size:12px">加载失败，请刷新重试</div>';
  }
}

function toggleDailySelect(id, checked) {
  if (checked) dailySelectedIds.add(id);
  else dailySelectedIds.delete(id);
  updateBatchDeleteBtn();
}

function updateBatchDeleteBtn() {
  const btn = document.getElementById('btnBatchDelete');
  const cnt = document.getElementById('selectedCount');
  if (dailySelectedIds.size > 0) {
    btn.style.display = 'inline-flex';
    cnt.textContent = dailySelectedIds.size;
  } else {
    btn.style.display = 'none';
  }
}

function selectAllDailyRecords() {
  const checkboxes = document.querySelectorAll('[id^="chk-"]');
  const allSelected = dailySelectedIds.size === checkboxes.length;
  checkboxes.forEach(cb => {
    const id = cb.id.replace('chk-', '');
    cb.checked = !allSelected;
    if (!allSelected) dailySelectedIds.add(id);
    else dailySelectedIds.delete(id);
  });
  updateBatchDeleteBtn();
}

async function clearDailyData() {
  if (!currentClientId) { toast('请先选择客户', 'err'); return; }
  const date = document.getElementById('dailyDate').value || new Date().toISOString().slice(0,10);
  const count = document.getElementById('dk-total').textContent;
  const platformLabel = currentPlatform === 'all' ? '全部平台' : (CRAWL_PLATFORM_NAMES[currentPlatform] || currentPlatform);
  if (!confirm(`确认清空 ${date}（${platformLabel}）的 ${count} 条数据？\n此操作不可恢复！`)) return;
  const r = await api('/api/daily/records/clear', 'POST', {
    client_id: currentClientId, date, platform: currentPlatform
  });
  if (r.ok) {
    toast(`已清空 ${r.deleted} 条当日数据 喵～`);
    loadDailyData();
  } else {
    toast(r.error || '清空失败', 'err');
  }
}

async function deleteDailyRecord(id) {
  if (!confirm('确认删除这条记录？')) return;
  await api(`/api/daily/records/${id}?client_id=${encodeURIComponent(currentClientId)}`, 'DELETE');
  toast('已删除 喵～');
  loadDailyData();
}

async function batchDeleteDailyRecords() {
  if (!dailySelectedIds.size) return;
  if (!confirm(`确认删除选中的 ${dailySelectedIds.size} 条记录？`)) return;
  await api('/api/daily/records/batch_delete', 'POST', { client_id: currentClientId, ids: [...dailySelectedIds] });
  toast(`已删除 ${dailySelectedIds.size} 条 喵～`);
  dailySelectedIds.clear();
  loadDailyData();
}

// ── Init ──────────────────────────────────────────────
refreshApiStatus();
loadClientsDropdown();
renderContractPlatformChoices('cl-platforms', ['deepseek'], 'new-client');
loadGroups();
// 设置当日数据整理的默认日期
const _dailyDateEl = document.getElementById('dailyDate');
if (_dailyDateEl) _dailyDateEl.value = new Date().toISOString().slice(0,10);
// 监听客户切换时刷新问题组
document.getElementById('globalClient').addEventListener('change', () => {
  loadGroups();
});
