function navTo(page, el) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('on'));
  document.querySelectorAll('.s-nav').forEach(n => n.classList.remove('on'));
  document.querySelectorAll('.t-ni').forEach(n => n.classList.remove('on'));
  document.getElementById('page-' + page)?.classList.add('on');
  if (el) el.classList.add('on');
  // page-specific load
  if (page === 'content') loadContent();
  if (page === 'daily') loadDailyPage();
  if (page === 'reference') loadReferenceIntelligence();
  if (page === 'clients') loadClients();
  if (page === 'settings') loadSettings();
}
// ── State ─────────────────────────────────────────────
let currentClientId = '';
let currentBrand = '';
let currentClientName = '';
let currentIndustry = '';
let currentGoal = '';
let currentPlatform = 'all';  // 数据页固定汇总全部平台
let currentClientPlatforms = [];
let groupPlatformMode = 'contract';
const loginPollTimers = {};
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
  return res.json();
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
  // 如果当前在内容生产页面，自动刷新资料+模板
  if (document.getElementById('page-content')?.classList.contains('on')) {
    loadContent();
  }
  if (document.getElementById('page-reference')?.classList.contains('on')) {
    loadReferenceIntelligence();
  }
  // 全局刷新模板提示条（当日整理顶部）和内容生产模板列表
  loadTemplates();
  loadTemplatesForContent();
  loadMaterials();
}
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
      </div>
      <span class="badge badge-p">${c.created}</span>
      <button class="btn btn-danger" onclick="delClient('${c.id}')">删除</button>
    </div>`).join('');
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

// ── 平台登录状态 ──────────────────────────────────────
async function platformLogin(platform) {
  const names = {doubao:'豆包', deepseek:'DeepSeek', yuanbao:'元宝', qwen:'千问', kimi:'Kimi'};
  const pName = platform.charAt(0).toUpperCase() + platform.slice(1);
  const btnId = `btnLogin${pName}`;
  const btn = document.getElementById(btnId);
  if (loginPollTimers[platform]) {
    clearInterval(loginPollTimers[platform]);
    delete loginPollTimers[platform];
  }
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

async function checkAllLoginStatus() {
  const platforms = CRAWL_PLATFORM_ORDER;
  const names = {doubao:'豆包', deepseek:'DeepSeek', yuanbao:'元宝', qwen:'千问', kimi:'Kimi'};
  const statusDiv = document.getElementById('platformLoginStatus');
  const legacyEl = document.getElementById('loginStatus');
  let html = '';
  for (const p of platforms) {
    try {
      const s = await api(`/api/platform/check_login?platform=${p}`);
      const statusMap = {
        ok: {color:'var(--teal)', icon:'✅', label:'已登录'},
        expired: {color:'var(--amber)', icon:'⚠', label:'已过期'},
        unknown: {color:'var(--amber)', icon:'?', label:'需重新登录'},
        missing: {color:'var(--text3)', icon:'○', label:'未登录'}
      };
      const meta = statusMap[s.status] || statusMap.missing;
      html += `<span title="${s.message||''}" style="font-size:11px;color:${meta.color};font-weight:600">${meta.icon} ${names[p]} ${meta.label}</span>`;
      if (p === 'doubao' && legacyEl) {
        legacyEl.innerHTML = s.logged_in
          ? '<div style="width:8px;height:8px;border-radius:50%;background:#4ade80"></div><span style="color:var(--teal)">已登录</span>'
          : `<div style="width:8px;height:8px;border-radius:50%;background:#f59e0b"></div><span style="color:var(--amber)">${meta.label}</span>`;
      }
    } catch {}
  }
  if (statusDiv) statusDiv.innerHTML = html;
}
function checkLoginStatus() { checkAllLoginStatus(); }

// ── Content ───────────────────────────────────────────
let contentTop20Articles = [];
let contentReferencePlugins = [];
let selectedContentArticleSubtype = '攻略对比型';
let selectedContentReferencePluginIndex = -1;

async function loadContent() {
  ensureContentHistoryDate();
  loadMaterials();
  loadContentTop20Samples();
  loadContentSubtypePlugins();
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

function getContentSampleLinks() {
  const raw = document.getElementById('contentSampleLinks')?.value || '';
  return raw.split(/\n|,|，|\s+/).map(x => x.trim()).filter(Boolean);
}

function getSelectedContentTopArticles() {
  return Array.from(document.querySelectorAll('#contentTop20Samples input[type="checkbox"]:checked'))
    .map(cb => contentTop20Articles[parseInt(cb.value, 10)])
    .filter(Boolean)
    .map(a => ({
      title: a.title || '',
      url: a.url || '',
      platform: a.platform || '',
      count: a.count || 0
    }));
}

function getLocalDateString() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

async function loadContentTop20Samples() {
  const el = document.getElementById('contentTop20Samples');
  if (!el) return;
  contentTop20Articles = [];
  if (!currentClientId) {
    el.innerHTML = '<div style="font-size:11px;color:var(--text3)">请先选择客户</div>';
    return;
  }
  el.innerHTML = '<div style="font-size:11px;color:var(--text3)">加载中...</div>';
  try {
    const date = document.getElementById('dailyDate')?.value || getLocalDateString();
    const stats = await api(`/api/daily/ref_stats?client_id=${currentClientId}&date=${date}&platform=all`);
    contentTop20Articles = (stats.top_articles || []).slice(0, 20);
    if (!contentTop20Articles.length) {
      el.innerHTML = '<div style="font-size:11px;color:var(--text3)">当天暂无高频引用文章</div>';
      return;
    }
    el.innerHTML = contentTop20Articles.map((a, i) => `
      <label style="display:grid;grid-template-columns:20px 24px 1fr auto;gap:8px;align-items:center;padding:7px 0;border-bottom:1px solid var(--border2);cursor:pointer">
        <input type="checkbox" value="${i}" style="width:auto;accent-color:var(--pri)">
        <span style="width:22px;height:22px;border-radius:7px;background:var(--pri-ll);color:var(--pri);font-size:10px;font-weight:900;display:flex;align-items:center;justify-content:center">${i+1}</span>
        <span style="min-width:0">
          <span style="font-size:11px;font-weight:700;color:#312e81;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(a.title || '')}">${escHtml(a.title || '未命名文章')}</span>
          <span style="font-size:10px;color:var(--text3)">${escHtml(a.platform || '未知平台')}${a.url ? ` · ${escHtml(a.url)}` : ''}</span>
        </span>
        <span style="font-size:11px;font-weight:800;color:var(--pri)">×${escHtml(a.count || 0)}</span>
      </label>`).join('');
  } catch(e) {
    el.innerHTML = '<div style="font-size:11px;color:var(--red)">Top20 加载失败</div>';
  }
}

let selectedContentArticleType = '对比型';
function selectContentArticleType(type) {
  selectedContentArticleType = type === '介绍型' ? '介绍型' : '对比型';
  if (selectedContentArticleType === '对比型' && !selectedContentArticleSubtype) {
    selectedContentArticleSubtype = '攻略对比型';
    selectedContentReferencePluginIndex = -1;
  }
  const compareBtn = document.getElementById('contentArticleTypeCompare');
  const introBtn = document.getElementById('contentArticleTypeIntro');
  if (compareBtn && introBtn) {
    compareBtn.className = selectedContentArticleType === '对比型' ? 'btn btn-p btn-sm' : 'btn btn-o btn-sm';
    introBtn.className = selectedContentArticleType === '介绍型' ? 'btn btn-p btn-sm' : 'btn btn-o btn-sm';
  }
  renderContentArticleSubtypes();
}

function selectContentArticleSubtype(name, pluginIndex = -1) {
  selectedContentArticleSubtype = name || '攻略对比型';
  selectedContentReferencePluginIndex = pluginIndex;
  renderContentArticleSubtypes();
}

function selectContentArticleSubtypeByIndex(pluginIndex) {
  if (pluginIndex < 0) {
    selectContentArticleSubtype('攻略对比型', -1);
    return;
  }
  const plugin = contentReferencePlugins[pluginIndex] || {};
  selectContentArticleSubtype(plugin.subtype_name || `引用情报子类型 ${pluginIndex + 1}`, pluginIndex);
}

function renderContentArticleSubtypes() {
  const wrap = document.getElementById('contentArticleSubtypeWrap');
  const list = document.getElementById('contentArticleSubtypes');
  const meta = document.getElementById('contentArticleSubtypeMeta');
  if (!wrap || !list) return;
  wrap.style.display = '';
  if (!selectedContentArticleSubtype) {
    selectedContentArticleSubtype = selectedContentArticleType === '对比型' ? '攻略对比型' : '';
    selectedContentReferencePluginIndex = -1;
  }
  const currentPlugins = contentReferencePlugins.filter(p => (p.parent_type || '对比型') === selectedContentArticleType);
  const buttons = [
    ...(selectedContentArticleType === '对比型' ? [{name: '攻略对比型', pluginIndex: -1}] : []),
    ...currentPlugins.map((p) => {
      const i = contentReferencePlugins.indexOf(p);
      return {name: p.subtype_name || `引用情报子类型 ${i + 1}`, pluginIndex: i};
    })
  ];
  if (!buttons.some(b => b.name === selectedContentArticleSubtype && b.pluginIndex === selectedContentReferencePluginIndex)) {
    selectedContentArticleSubtype = buttons[0]?.name || '';
    selectedContentReferencePluginIndex = -1;
  }
  if (!buttons.length) {
    list.innerHTML = `<span style="font-size:11px;color:var(--text3)">暂无${escHtml(selectedContentArticleType)}引用情报子类型</span>`;
    if (meta) meta.textContent = '可先到引用情报分析生成插件';
    return;
  }
  list.innerHTML = buttons.map(b => {
    const active = b.name === selectedContentArticleSubtype && b.pluginIndex === selectedContentReferencePluginIndex;
    return `<button type="button" class="${active ? 'btn btn-p btn-sm' : 'btn btn-o btn-sm'}" onclick="selectContentArticleSubtypeByIndex(${b.pluginIndex})">${escHtml(b.name)}</button>`;
  }).join('');
  if (meta) meta.textContent = currentPlugins.length
    ? `已加载 ${currentPlugins.length} 个${selectedContentArticleType}引用情报子类型`
    : '对比型默认使用攻略对比型；引用情报插件会按父类型显示在这里';
}

async function loadContentSubtypePlugins() {
  contentReferencePlugins = [];
  if (!currentClientId) {
    renderContentArticleSubtypes();
    return;
  }
  try {
    const data = await api(`/api/reference_intelligence/plugins?client_id=${currentClientId}&date=${getContentHistoryDate()}`);
    contentReferencePlugins = (data.plugins || []).filter(p => (p.subtype_name || p.prompt_text || p.few_shot));
  } catch(e) {
    contentReferencePlugins = [];
  }
  renderContentArticleSubtypes();
}

function getSelectedContentSubtypePlugin() {
  if (selectedContentReferencePluginIndex < 0) return null;
  const p = contentReferencePlugins[selectedContentReferencePluginIndex];
  if (!p) return null;
  return {
    parent_type: p.parent_type || '对比型',
    subtype_name: p.subtype_name || '',
    prompt_text: p.prompt_text || '',
    few_shot: p.few_shot || ''
  };
}

async function generateContentArticle() {
  if (!currentClientId) { toast('请先选择客户','err'); return; }
  const opinionEl = document.getElementById('contentOpinion');
  const opinion = opinionEl.value.trim();
  if (!opinion) { toast('请先填写运营意见','err'); return; }
  spin('spContentGenerate', true);
  disableBtn('btnContentGenerate', true);
  const statusEl = document.getElementById('contentGenerateStatus');
  statusEl.textContent = '当前模型生成中，请稍候...';
  try {
    const r = await api('/api/content/generate', 'POST', {
      client_id: currentClientId,
      opinion,
      history_date: getContentHistoryDate(),
      article_type: selectedContentArticleType,
      article_subtype: selectedContentArticleSubtype,
      article_subtype_plugin: getSelectedContentSubtypePlugin(),
      sample_links: getContentSampleLinks(),
      selected_articles: getSelectedContentTopArticles()
    });
    if (r.error) { toast(r.error, 'err'); return; }
    opinionEl.value = '';
    renderContentGenerations(r.articles || []);
    statusEl.textContent = `已生成：${r.article?.title || '新文章'}`;
    toast('文章生成成功 ✦');
  } finally {
    spin('spContentGenerate', false);
    disableBtn('btnContentGenerate', false);
  }
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
function contentGenerationSubtypeLabel(a) {
  return String(a?.article_subtype || '').trim();
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
    const subtypeLabel = contentGenerationSubtypeLabel(a);
    return `
    <div class="article-card">
      <div class="article-title">${a.title || '未命名文章'}</div>
      <div class="article-meta">
        <span class="badge badge-p">调用模型：${a.model || '未知模型'}</span>
        <span class="badge badge-g">${a.article_type || '未标记类型'}</span>
        ${subtypeLabel ? `<span class="badge badge-a">子类型：${escHtml(subtypeLabel)}</span>` : ''}
        <span class="badge badge-g">资料 ${a.material_count || 0} 份</span>
        <span class="badge badge-a">样例 ${((a.sample_link_count || 0) + (a.selected_article_count || 0))} 个</span>
        <span style="font-size:10px;color:var(--text3)">${a.created_at || ''}</span>
      </div>
      <div class="article-summary">${(a.content || '').slice(0, 160)}${(a.content || '').length > 160 ? '...' : ''}</div>
      <div class="article-acts">
        <button class="btn btn-o btn-sm" onclick="viewContentGeneration('${a.id}')">查看全文</button>
        <button class="btn btn-o btn-sm" onclick="copyContentGeneration('${a.id}')">复制</button>
        <button class="btn btn-danger btn-sm" onclick="deleteContentGeneration('${a.id}')">删除</button>
      </div>
    </div>`;
  }).join('');
}
function viewContentGeneration(id) {
  const a = (window._contentGenerationCache || []).find(x => x.id === id);
  if (!a) return;
  const subtypeLabel = contentGenerationSubtypeLabel(a);
  const subtypeHtml = subtypeLabel ? `<div class="content-generation-subtype">文章子类型：${escHtml(subtypeLabel)}</div>` : '';
  const win = window.open('','_blank','width=760,height=680');
  win.document.write(`<html><head><title>${a.title || '生成文章'}</title><link href="{{ url_for('static', filename='css/app.css') }}" rel="stylesheet"></head><body>${subtypeHtml}<h1>${a.title || '生成文章'}</h1><pre>${a.content || ''}</pre></body></html>`);
}
function copyContentGeneration(id) {
  const a = (window._contentGenerationCache || []).find(x => x.id === id);
  if (!a) return;
  navigator.clipboard.writeText(a.content || '').then(() => toast('文章已复制 ✦'));
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
  const url = document.getElementById('set-url').value.trim();
  const model = document.getElementById('set-model').value.trim();
  if (!url||!model) { toast('请填写接口地址和模型名称','err'); return; }
  await api('/api/settings','POST',{api_key:key||'***',base_url:url,model,preset:selectedPreset});
  updateApiStatus({has_key:true, model});
  document.getElementById('set-key').value = '';
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
  // 更新记录库筛选下拉
  const filter = document.getElementById('rec-group-filter');
  if (filter) {
    filter.innerHTML = '<option value="">全部问题组</option>' +
      groups.map(g => `<option value="${g.id}">${g.name}（${g.questions.length}题）</option>`).join('');
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
  checkAllLoginStatus();
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
    for (const platform of platforms) {
      const resp = await fetch('/api/crawl_jobs', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          client_id: currentClientId,
          brand: currentBrand,
          group_id: currentGroupId,
          platform: platform.id,
          repeat_count: repeat
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

async function loadDeepAnalysis() {
  if (!currentClientId) { toast('请先选择客户','err'); return; }
  spin('spDeep', true);
  const group_id = document.getElementById('rec-group-filter')?.value || '';
  const date = document.getElementById('rec-date-filter')?.value || '';
  const question = document.getElementById('rec-question-filter')?.value || '';
  const mentioned = document.getElementById('rec-mentioned-filter')?.value || '';
  const taskId = document.getElementById('rec-task-filter')?.value || '';
  try {
    const r = await api('/api/raw_records/deep_analyze', 'POST', {
      client_id: currentClientId,
      platform: currentPlatform, group_id, date, question,
      mentioned_only: mentioned,
      task_id: taskId
    });
    if (r.error) { toast(r.error,'err'); return; }
    const card = document.getElementById('deepAnalysisCard');
    card.style.display = 'block';
    card.scrollIntoView({behavior:'smooth'});
    const s = r.stats;
    document.getElementById('deepStats').innerHTML = [
      ['记录数', s.total, '条', 'var(--pri)'],
      ['品牌提及', s.mentioned, '次', 'var(--teal)'],
      ['提及率', s.mention_rate, '%', 'var(--pink)'],
      ['平均GEO', s.avg_score, '分', 'var(--amber)'],
    ].map(([l,v,u,c]) => `
      <div style="padding:12px;background:rgba(255,255,255,.85);border-radius:var(--r-sm);border:1.5px solid var(--border2);text-align:center">
        <div style="font-size:20px;font-weight:900;color:${c}">${v}<span style="font-size:10px;color:var(--text3)">${u}</span></div>
        <div style="font-size:10px;color:var(--text2);font-weight:700;margin-top:3px">${l}</div>
      </div>`).join('');
    document.getElementById('deepReportContent').innerHTML = marked.parse(r.report);

    // 处理内容生产指令
    if (r.content_instruction) {
      window._lastContentInstruction = r.content_instruction;
      window._lastDeepStats = r.stats;
      document.getElementById('btnImportContent').style.display = 'inline-flex';
      document.getElementById('contentInstructionBox').style.display = 'block';
      document.getElementById('contentInstructionText').textContent = r.content_instruction;
    }

    toast('深度分析完成 ✦');
  } finally { spin('spDeep', false); }
}

function copyDeepReport() {
  navigator.clipboard.writeText(document.getElementById('deepReportContent').innerText)
    .then(() => toast('报告已复制 ✦'));
}

function importToContent() {
  if (!window._lastContentInstruction) { toast('暂无内容指令', 'err'); return; }
  navTo('content', document.querySelector('.s-nav[onclick*="content"]'));
  setTimeout(() => {
    appendContentOpinion(window._lastContentInstruction, '深度分析指令');
    toast('内容生产指令已导入 ✦');
    const opinionEl = document.getElementById('contentOpinion');
    if (opinionEl) {
      opinionEl.style.borderColor = 'var(--pri)';
      opinionEl.style.background = 'var(--pri-ll)';
      setTimeout(() => {
        opinionEl.style.borderColor = '';
        opinionEl.style.background = '';
      }, 3000);
    }
  }, 400);
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

async function loadMaterials() {
  if (!currentClientId) return;
  const files = await api('/api/materials/' + currentClientId);
  const el = document.getElementById('materialList');
  if (!files.length) {
    el.innerHTML = '<div style="font-size:11px;color:var(--text3)">暂无资料，支持 txt / md / pdf / docx</div>';
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

async function loadLocalMaterials() {
  const box = document.getElementById('localMaterialList');
  box.style.display = 'block';
  box.innerHTML = '<div style="font-size:11px;color:var(--text3)">读取本地 pdf/ 文件夹中...</div>';
  try {
    const r = await api('/api/materials/local');
    const files = r.files || [];
    if (!files.length) {
      box.innerHTML = '<div style="font-size:11px;color:var(--text3)">本地 pdf/ 文件夹暂无可导入资料</div>';
      return;
    }
    box.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <div style="font-size:11px;font-weight:800;color:var(--text2)">本地 pdf/ 文件夹资料</div>
        <button class="btn btn-p btn-sm" onclick="importSelectedLocalMaterials()">导入选中</button>
      </div>
      ${files.map(f => `
        <label style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border2);font-size:11px;color:var(--text2)">
          <input type="checkbox" class="local-material-choice" value="${escHtml(f.name)}" style="width:auto">
          <span style="flex:1;font-weight:700;color:var(--text)">${escHtml(f.name)}</span>
          <span style="color:var(--text3)">${(f.size/1024).toFixed(1)}KB</span>
        </label>`).join('')}
    `;
  } catch(e) {
    box.innerHTML = `<div style="font-size:11px;color:var(--red)">读取失败：${escHtml(e.message)}</div>`;
  }
}

async function importSelectedLocalMaterials() {
  if (!currentClientId) { toast('请先选择客户','err'); return; }
  const filenames = Array.from(document.querySelectorAll('.local-material-choice:checked')).map(el => el.value);
  if (!filenames.length) { toast('请选择要导入的本地资料','err'); return; }
  const r = await api('/api/materials/' + currentClientId + '/import-local', 'POST', {filenames});
  toast(`已导入 ${r.materials?.length || filenames.length} 份资料 ✦`);
  loadMaterials();
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
  const hint = document.getElementById('dailyTemplateHint');
  const tname = document.getElementById('dailyTemplateName');
  if (hint && active) {
    hint.style.display = 'flex';
    if (tname) tname.textContent = active.original || active.name;
  }

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
      renderReferenceProgress('生成中...');
    }
  }, 200);
}

function renderReferencePlugins(data) {
  const list = document.getElementById('referencePluginList');
  const meta = document.getElementById('referencePluginMeta');
  if (!list) return;
  const plugins = data?.plugins || [];
  if (meta) meta.textContent = plugins.length ? `${plugins.length} 个插件 · ${data.updated_at || ''}` : '';
  if (!plugins.length) {
    list.innerHTML = '<div class="empty"><i class="ti ti-bulb"></i><p>暂无引用情报插件，可先点击“生成引用情报”</p></div>';
    return;
  }
  list.innerHTML = plugins.map((p, i) => `
    <div style="padding:12px 0;border-bottom:1px solid var(--border2)">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <span style="width:24px;height:24px;border-radius:8px;background:var(--pri-ll);color:var(--pri);font-size:11px;font-weight:900;display:flex;align-items:center;justify-content:center">${i+1}</span>
        <span style="font-size:13px;font-weight:900;color:#312e81">${escHtml(p.subtype_name || '未命名插件')}</span>
        <span class="badge badge-g">${escHtml(p.parent_type || '对比型')}</span>
      </div>
      <div style="font-size:11px;font-weight:900;color:var(--text3);margin:8px 0 4px">prompt_text</div>
      <div style="font-size:12px;line-height:1.7;color:var(--text2);white-space:pre-wrap;background:rgba(109,92,247,.04);border:1px solid var(--border2);border-radius:var(--r-sm);padding:10px">${escHtml(p.prompt_text || '')}</div>
      <div style="font-size:11px;font-weight:900;color:var(--text3);margin:10px 0 4px">few_shot</div>
      <div style="font-size:12px;line-height:1.7;color:var(--text2);white-space:pre-wrap;background:rgba(52,211,153,.05);border:1px solid rgba(52,211,153,.14);border-radius:var(--r-sm);padding:10px">${escHtml(p.few_shot || '')}</div>
      ${(p.source_articles || []).length ? `
        <div style="font-size:11px;font-weight:900;color:var(--text3);margin:10px 0 4px">基于 ${(p.source_articles || []).length} 篇文章合并</div>
        <div style="display:flex;flex-direction:column;gap:4px">
          ${(p.source_articles || []).map((a, j) => `
            <div style="font-size:11px;line-height:1.5;color:var(--text2);overflow-wrap:anywhere">
              <span style="font-weight:800;color:#312e81">${j + 1}. ${escHtml(a.title || a.url || '未命名文章')}</span>
              ${a.url ? `<a href="${escHtml(a.url)}" target="_blank" rel="noopener noreferrer" style="color:var(--pri);margin-left:6px">${escHtml(a.url)}</a>` : ''}
            </div>
          `).join('')}
        </div>
      ` : ''}
    </div>`).join('');
}

async function loadReferenceIntelligence() {
  getReferenceDate();
  if (!currentClientId) {
    renderReferencePlugins({plugins: []});
    return;
  }
  const date = getReferenceDate();
  try {
    const data = await api(`/api/reference_intelligence/plugins?client_id=${currentClientId}&date=${date}`);
    renderReferencePlugins(data);
  } catch(e) {
    document.getElementById('referencePluginList').innerHTML = `<div style="color:var(--red);font-size:12px">加载失败：${escHtml(e.message)}</div>`;
  }
}

async function analyzeReferenceIntelligence() {
  if (!currentClientId) { toast('请先选择客户', 'err'); return; }
  const date = getReferenceDate();
  stopReferenceAnalyzeTimers();
  referenceAnalyzeJobId = '';
  referenceBackendProgress = 3;
  referenceDisplayProgress = 0;
  setReferenceProgressVisible(true);
  renderReferenceProgress('生成中...');
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
let dailySelectedIds = new Set();
let dailyAnalysisData = null;


const DAILY_PAGE_SIZE = 20;

function renderDailyRecord(r) {
  const div = document.createElement('div');
  div.id = 'rec-' + r.id;
  div.style.cssText = 'display:flex;align-items:flex-start;gap:10px;padding:10px;background:rgba(255,255,255,.8);border:1.5px solid var(--border2);border-radius:var(--r-sm);margin-bottom:6px';
  div.innerHTML = `
    <input type="checkbox" style="margin-top:3px;width:auto;accent-color:var(--pri)" onchange="toggleDailySelect('${r.id}',this.checked)" id="chk-${r.id}">
    <div style="flex:1;min-width:0">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;flex-wrap:wrap">
        <span style="font-size:12px;font-weight:800;color:#312e81">${r.question}</span>
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
  loadTemplates();  // 每次进入页面刷新模板列表
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
  const analysisResult = document.getElementById('dailyAnalysisResult');
  if (analysisResult) analysisResult.style.display = 'none';
  dailyAnalysisData = null;

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
  await api(`/api/daily/records/${id}`, 'DELETE');
  toast('已删除 喵～');
  loadDailyData();
}

async function batchDeleteDailyRecords() {
  if (!dailySelectedIds.size) return;
  if (!confirm(`确认删除选中的 ${dailySelectedIds.size} 条记录？`)) return;
  await api('/api/daily/records/batch_delete', 'POST', { ids: [...dailySelectedIds] });
  toast(`已删除 ${dailySelectedIds.size} 条 喵～`);
  dailySelectedIds.clear();
  loadDailyData();
}

async function startDailyAnalyze() {
  if (!currentClientId) { toast('请先选择客户', 'err'); return; }
  const date = document.getElementById('dailyDate').value || new Date().toISOString().slice(0,10);
  const groupSel = document.getElementById('dailyGroupFilter');
  const groupId = groupSel?.value || '';
  const groupName = groupId ? (groupSel.options[groupSel.selectedIndex]?.text || '') : '';
  const taskId = document.getElementById('dailyTaskFilter')?.value || '';
  spin('spDailyAnalyze', true);
  disableBtn('btnDailyAnalyze', true);
  try {
    const r = await api('/api/daily/deep_analyze', 'POST', {
      client_id: currentClientId, date, brand: currentBrand,
      platform: currentPlatform, group_id: groupId, group_name: groupName,
      task_id: taskId
    });
    if (r.error) { toast(r.error, 'err'); return; }
    dailyAnalysisData = r;
    document.getElementById('dailyAnalysisResult').style.display = 'block';
    document.getElementById('dailyAnalysisResult').scrollIntoView({ behavior: 'smooth' });
    // 显示当前分析范围标签
    const scopeEl = document.getElementById('dailyAnalysisScope');
    if (scopeEl) {
      scopeEl.style.display = 'block';
      const taskScope = taskId ? ` &nbsp;·&nbsp; 批次 <span style="color:var(--pri)">#${escHtml(taskId.slice(-8))}</span>` : '';
      scopeEl.innerHTML = groupName
        ? `📂 当前分析范围：<span style="color:var(--pri)">${groupName}</span> 问题组${taskScope} &nbsp;·&nbsp; 共 ${r.stats.total_records} 条记录`
        : `📊 当前分析范围：<span style="color:var(--pri)">全部问题组</span>${taskScope} &nbsp;·&nbsp; 共 ${r.stats.total_records} 条记录`;
    }
    renderDailyAnalysis(r);
    toast('深度分析完成 喵～✦');
  } finally {
    spin('spDailyAnalyze', false);
    disableBtn('btnDailyAnalyze', false);
  }
}

function renderDailyAnalysis(r) {
  // KPI统计
  const s = r.stats;
  document.getElementById('dailyAnalysisStats').innerHTML = [
    ['监测问题', s.total_records, '条', 'var(--pri)'],
    ['品牌提及', s.mentioned, '次', 'var(--teal)'],
    ['提及率', s.mention_rate, '%', 'var(--pink)'],
    ['平均GEO', s.avg_score, '分', 'var(--amber)'],
  ].map(([l,v,u,c]) => `
    <div style="padding:12px;background:rgba(255,255,255,.85);border-radius:var(--r-sm);border:1.5px solid var(--border2);text-align:center">
      <div style="font-size:20px;font-weight:900;color:${c}">${v}<span style="font-size:10px;color:var(--text3)">${u}</span></div>
      <div style="font-size:10px;color:var(--text2);font-weight:700;margin-top:3px">${l}</div>
    </div>`).join('');

  // 平台标签页
  const tabs = document.getElementById('platformTabs');
  tabs.innerHTML = r.top8_platforms.map((p,i) => `
    <div onclick="showPlatformDetail('${p.platform}', ${i})" id="ptab-${i}"
      style="padding:6px 12px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;border:1.5px solid var(--border2);background:${i===0?'var(--pri-ll)':'rgba(255,255,255,.8)'};color:${i===0?'var(--pri)':'var(--text2)'}">
      ${p.platform} <span style="font-size:10px;color:var(--text3)">${p.weight_pct}%</span>
      ${p.is_emerging ? '<span style="color:var(--teal);font-size:9px">★新兴</span>' : ''}
    </div>`).join('');

  // 显示第一个平台的数据
  if (r.top8_platforms.length) showPlatformDetail(r.top8_platforms[0].platform, 0);

  // 报告
  document.getElementById('dailyAnalysisReport').innerHTML = marked.parse(r.report);
}

function showPlatformDetail(platform, idx) {
  if (!dailyAnalysisData) return;
  const pData = dailyAnalysisData.top8_platforms.find(p => p.platform === platform);
  if (!pData) return;
  const prompt = dailyAnalysisData.platform_prompts?.[platform] || '';

  // 更新标签高亮
  document.querySelectorAll('[id^="ptab-"]').forEach((el, i) => {
    el.style.background = i === idx ? 'var(--pri-ll)' : 'rgba(255,255,255,.8)';
    el.style.color = i === idx ? 'var(--pri)' : 'var(--text2)';
    el.style.borderColor = i === idx ? 'var(--pri)' : 'var(--border2)';
  });

  const detail = document.getElementById('platformDetail');
  detail.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
      <div>
        <div style="font-size:12px;font-weight:800;color:#312e81;margin-bottom:10px">${platform} 数据概览</div>
        <div style="display:flex;flex-direction:column;gap:6px">
          ${[
            ['权重占比', pData.weight_pct + '%'],
            ['平均引用排名', '第' + pData.avg_position + '位'],
            ['品牌提及率', pData.mention_rate + '%'],
            ['引用次数', pData.count + '次'],
            ['GEO价值', pData.is_emerging ? '⭐ 新兴高价值' : '稳定来源'],
          ].map(([l,v]) => `
            <div style="display:flex;justify-content:space-between;padding:6px 8px;background:rgba(255,255,255,.7);border-radius:6px;font-size:11px">
              <span style="color:var(--text2);font-weight:700">${l}</span>
              <span style="color:#312e81;font-weight:800">${v}</span>
            </div>`).join('')}
        </div>
        <div style="margin-top:12px">
          <div style="font-size:11px;font-weight:800;color:#312e81;margin-bottom:6px">高频引用文章</div>
          ${pData.top_articles.map((a,i) => `
            <div style="display:flex;align-items:center;gap:6px;padding:5px 0;border-bottom:1px solid var(--border2)">
              <span style="font-size:10px;font-weight:900;color:var(--pri);width:16px">${i+1}</span>
              <a href="${a.url||'#'}" target="_blank" style="font-size:11px;font-weight:700;color:#312e81;text-decoration:none;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${a.title}</a>
              <span style="font-size:10px;color:var(--pri);font-weight:800;flex-shrink:0">×${a.count}</span>
            </div>`).join('')}
        </div>
      </div>
      <div>
        <div style="font-size:12px;font-weight:800;color:#312e81;margin-bottom:8px">📋 专属内容生产提示词</div>
        <div style="padding:12px;background:linear-gradient(135deg,rgba(109,92,247,.05),rgba(244,114,182,.05));border:1.5px solid rgba(109,92,247,.15);border-radius:var(--r-sm);font-size:11px;color:var(--text2);line-height:1.7;min-height:120px">${prompt || '生成中...'}</div>
        <div style="display:flex;gap:8px;margin-top:10px">
          <button class="btn btn-p btn-sm" onclick="importPlatformPrompt('${platform}')">导入内容生产</button>
          <button class="btn btn-o btn-sm" onclick="copyPlatformPrompt('${platform}')">复制提示词</button>
        </div>
      </div>
    </div>`;
}

async function refineAndFillPattern(rawText, sourceName) {
  const opinionEl = document.getElementById('contentOpinion');
  if (!opinionEl) return;
  const previous = opinionEl.value;
  opinionEl.value = previous ? `${previous}\n\n正在提炼「${sourceName}」内容规律...` : `正在提炼「${sourceName}」内容规律...`;
  opinionEl.disabled = true;
  try {
    const r = await api('/api/content/refine_pattern', 'POST', { text: rawText });
    if (r.error) {
      opinionEl.value = previous;
      appendContentOpinion(rawText.slice(0, 300), sourceName);
      toast('提炼失败，已截取前300字', 'err');
    } else {
      opinionEl.value = previous;
      appendContentOpinion(r.refined, sourceName);
      toast(`「${sourceName}」内容规律已提炼导入 ✦`);
    }
  } catch(e) {
    opinionEl.value = previous;
    appendContentOpinion(rawText.slice(0, 300), sourceName);
    toast('提炼失败，已截取前300字', 'err');
  } finally {
    opinionEl.disabled = false;
  }
}

function appendContentOpinion(text, sourceName) {
  const opinionEl = document.getElementById('contentOpinion');
  if (!opinionEl) return;
  const block = `【${sourceName}】\n${text}`;
  const existing = opinionEl.value.trim();
  opinionEl.value = existing ? `${existing}\n\n${block}` : block;
  opinionEl.focus();
}

async function importPlatformPrompt(platform) {
  if (!dailyAnalysisData?.platform_prompts?.[platform]) { toast('暂无该平台提示词', 'err'); return; }
  const prompt = dailyAnalysisData.platform_prompts[platform];
  navTo('content', null);
  const banner = document.getElementById('ct-import-banner');
  if (banner) { banner.style.display = 'block'; banner.textContent = `✦ 已导入「${platform}」平台内容生产指令`; }
  await refineAndFillPattern(prompt, platform);
}

function copyPlatformPrompt(platform) {
  const prompt = dailyAnalysisData?.platform_prompts?.[platform] || '';
  navigator.clipboard.writeText(prompt).then(() => toast('提示词已复制 喵～✦'));
}

function copyDailyReport() {
  navigator.clipboard.writeText(document.getElementById('dailyAnalysisReport').innerText)
    .then(() => toast('报告已复制 喵～✦'));
}

async function importDailyToContent() {
  if (!dailyAnalysisData) { toast('请先生成深度分析', 'err'); return; }
  navTo('content', null);
  const report = document.getElementById('dailyAnalysisReport').innerText;
  const banner = document.getElementById('ct-import-banner');
  if (banner) { banner.style.display = 'block'; banner.textContent = '✦ 已从今日深度分析导入内容生产指令'; }
  await refineAndFillPattern(report, '深度分析报告');
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
