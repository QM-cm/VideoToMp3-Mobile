/* 手机端「视频转 MP3 助手」前端逻辑（零依赖，PWA） */
"use strict";

const $ = (s) => document.querySelector(s);
// API 地址：同源部署留空；前端挂 GitHub Pages、后端独立部署时，
// 在「设置-服务地址」里填写，例如 https://xxx.onrender.com
const API = (localStorage.getItem("vmp3_api") || "").replace(/\/+$/, "");

/* ── 工具 ─────────────────────────────────────────── */
function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(t._tm);
  t._tm = setTimeout(() => { t.hidden = true; }, ms);
}

async function api(path, opts) {
  const r = await fetch(API + path, opts);
  let d;
  try { d = await r.json(); } catch { d = {}; }
  if (!r.ok && !d.ok) throw new Error(d.error || "请求失败");
  return d;
}

/* 链接提取：与桌面版同规则 */
const URL_RE = /https?:\/\/[^\s\u4e00-\u9fff，。；：！？、（）【】《》「」“”‘’"'<>]+/g;
function extractUrls(text) {
  const seen = new Set(), out = [];
  for (const m of (text || "").match(URL_RE) || []) {
    const u = m.trim().replace(/[.,;:)\]]+$/, "");
    if (u && !seen.has(u)) { seen.add(u); out.push(u); }
  }
  return out;
}

/* ── 全局状态 ─────────────────────────────────────── */
let jobs = {};        // jid -> 前端任务对象（含 status/progress/title/...）
let pollTimer = null;
let settings = { quality: "high", concurrency: 1, name_template: "{artist} - {title}.mp3", embed_cover: true, sample_rate: 44100, normalize_loudness: false };

/* ── 渲染：任务列表 ────────────────────────────────── */
const STATUS_LABEL = {
  queued: "排队中", pending: "等待中", parsing: "解析中",
  downloading: "下载中", converting: "转码中", canceling: "取消中",
  done: "完成", failed: "失败", canceled: "已取消",
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtDur(sec) {
  sec = Math.round(Number(sec) || 0);
  if (sec <= 0) return "";
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
           : `${m}:${String(s).padStart(2, "0")}`;
}

function renderTasks() {
  const list = $("#task-list");
  const ids = Object.keys(jobs);
  if (!ids.length) {
    list.innerHTML = `<div class="empty">🎵<br>粘贴链接，一键带走好听的歌</div>`;
    return;
  }
  const html = ids.map((jid) => {
    const t = jobs[jid];
    const chip = `<span class="chip ${t.status}">${STATUS_LABEL[t.status] || t.status}</span>`;
    const cover = t.thumbnail
      ? `<img src="${esc(t.thumbnail)}" alt="" loading="lazy" onerror="this.style.display='none'">`
      : "🎵";
    let actions = "";
    if (t.status === "done" && t.output_path) {
      actions += `<button class="btn btn-primary btn-sm" onclick="downloadTask('${jid}')">⬇ 下载</button>`;
    }
    if (["queued", "pending", "parsing", "downloading", "converting", "canceling"].includes(t.status)) {
      actions += `<button class="btn btn-ghost btn-sm danger" onclick="cancelTask('${jid}')">停止</button>`;
    }
    if (["failed", "canceled"].includes(t.status)) {
      actions += `<button class="btn btn-ghost btn-sm" onclick="retryTask('${jid}')">重试</button>`;
    }
    if (["done", "failed", "canceled"].includes(t.status)) {
      actions += `<button class="btn btn-ghost btn-sm danger" onclick="deleteTask('${jid}')">删除</button>`;
    }
    const err = t.error ? `<div class="task-err">${esc(t.error)}</div>` : "";
    const dur = fmtDur(t.duration);
    return `<div class="task-item">
      <div class="task-cover">${cover}</div>
      <div class="task-main">
        <div class="task-title">${esc(t.title || t.url)}</div>
        <div class="task-meta">${esc(t.artist || "")}${dur ? " · " + dur : ""} · ${chip}</div>
        <div class="progress"><div style="width:${t.progress || 0}%"></div></div>
        ${err}
        <div class="task-actions">${actions}</div>
      </div>
    </div>`;
  }).join("");
  list.innerHTML = html;
}

/* ── 任务操作 ─────────────────────────────────────── */
function addJobs(urls, opts) {
  // 前端去重：已在列表且未终态的同链接不再提交
  const running = new Set(
    Object.values(jobs)
      .filter((t) => ["queued", "pending", "parsing", "downloading", "converting", "canceling"].includes(t.status))
      .map((t) => t.url));
  const fresh = urls.filter((u) => !running.has(u));
  if (!fresh.length) { toast("这些链接已在任务列表中"); return Promise.resolve({ jobs: [] }); }
  return api("/api/convert", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls: fresh, ...opts }),
  }).then((d) => {
    for (const j of d.jobs) {
      jobs[j.jid] = { jid: j.jid, url: j.url, status: "queued", progress: 0, title: "", artist: "", error: "" };
    }
    renderTasks();
    ensurePoll();
    toast(`已添加 ${d.jobs.length} 个任务` + (fresh.length < urls.length ? "，重复的已跳过" : ""));
    return d;
  });
}

async function cancelTask(jid) {
  try {
    await api(`/api/cancel/${jid}`, { method: "POST" });
    toast("已发送停止指令…");
  } catch (e) { toast(e.message); }
}

function deleteTask(jid) {
  delete jobs[jid];
  renderTasks();
}

function retryTask(jid) {
  const t = jobs[jid];
  if (!t) return;
  // 移除原任务，用相同参数重建
  const old = { ...t };
  delete jobs[jid];
  renderTasks();
  addJobs([old.url], {
    quality: $("#quality-sel").value,
    start_time: $("#start-t").value.trim(),
    end_time: $("#end-t").value.trim(),
    max_duration: $("#max-t").value.trim(),
    custom_title: $("#custom-title").value.trim(),
  }).catch((e) => toast(e.message));
}

function downloadTask(jid) {
  // 对应手机端：点击后手机浏览器直接下载 mp3/flac 文件到本机「下载」目录
  const a = document.createElement("a");
  a.href = API + `/api/download/${jid}`;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* ── 轮询 ─────────────────────────────────────────── */
async function pollOnce() {
  const active = Object.keys(jobs).filter((j) =>
    ["queued", "pending", "parsing", "downloading", "converting", "canceling"].includes(jobs[j].status));
  if (!active.length) { stopPoll(); return; }
  try {
    await Promise.all(active.map(async (jid) => {
      const d = await api(`/api/status/${jid}`);
      if (!d.ok) return;
      jobs[jid] = { ...jobs[jid], ...d, jid };
      if (d.status === "done" && d.output_path) {
        loadHistory(true); // 完成后刷新历史
      }
      renderTasks();
    }));
  } catch (e) {
    // 单次轮询失败不中断
  }
}

function ensurePoll() {
  if (pollTimer) return;
  pollTimer = setInterval(pollOnce, 1500);
}
function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

/* ── 添加链接 ─────────────────────────────────────── */
async function handleAdd() {
  const urls = extractUrls($("#url-input").value);
  if (!urls.length) { toast("未识别到 http/https 链接"); return; }
  const opts = {
    quality: $("#quality-sel").value,
    start_time: $("#start-t").value.trim(),
    end_time: $("#end-t").value.trim(),
    max_duration: $("#max-t").value.trim(),
    custom_title: $("#custom-title").value.trim(),
  };
  try {
    await addJobs(urls, opts);
    $("#url-input").value = "";
  } catch (e) { toast(e.message); }
}

async function pasteClipboard() {
  try {
    const text = await navigator.clipboard.readText();
    const urls = extractUrls(text);
    if (!urls.length) { toast("剪贴板里没有链接"); return; }
    $("#url-input").value = urls.join("\n");
    toast(`已提取 ${urls.length} 条链接`);
  } catch {
    toast("无法读取剪贴板，请长按输入框粘贴");
  }
}

/* ── 历史记录 ─────────────────────────────────────── */
async function loadHistory(silent = false) {
  try {
    const d = await api(`/api/history?q=${encodeURIComponent($("#history-search").value || "")}`);
    const list = $("#history-list");
    if (!d.records.length) {
      list.innerHTML = `<div class="empty">暂无历史记录</div>`;
      return;
    }
    list.innerHTML = d.records.map((r) => `
      <div class="task-item history-item">
        <div class="task-main">
          <div class="task-title">${esc(r.title || r.url)}</div>
          <div class="task-meta">${esc(r.artist || "")} · ${r.status === "done" ? "完成" : "失败"} · ${esc(r.quality)}</div>
          <div class="time">${esc(r.created_at || "")}</div>
          ${r.output_path ? `<div class="path">${esc(r.output_path)}</div>` : ""}
          <div class="task-actions">
            ${r.status === "done" ? `<button class="btn btn-primary btn-sm" onclick="redownloadHistory(${r.id}, '${esc(r.url)}')">重新下载</button>` : ""}
            <button class="btn btn-ghost btn-sm danger" onclick="deleteHistory(${r.id})">删除</button>
          </div>
        </div>
      </div>`).join("");
  } catch (e) { if (!silent) toast(e.message); }
}

function redownloadHistory(id, url) {
  addJobs([url], {
    quality: $("#quality-sel").value,
    custom_title: $("#custom-title").value.trim(),
  }).catch((e) => toast(e.message));
  switchPanel("tasks");
}

async function deleteHistory(id) {
  try { await api(`/api/history/${id}`, { method: "DELETE" }); loadHistory(); }
  catch (e) { toast(e.message); }
}

async function clearHistory() {
  try { await api("/api/history/clear", { method: "POST" }); loadHistory(); toast("已清空"); }
  catch (e) { toast(e.message); }
}

/* ── 设置 ─────────────────────────────────────────── */
async function loadSettings() {
  try {
    const d = await api("/api/settings");
    settings = { ...settings, ...d.settings };
    $("#set-quality").value = settings.quality;
    $("#set-concurrency").value = String(settings.concurrency);
    $("#set-rate").value = String(settings.sample_rate || 44100);
    $("#set-normalize").checked = !!settings.normalize_loudness;
    $("#set-template").value = settings.name_template;
    $("#set-cover").checked = !!settings.embed_cover;
    $("#set-api").value = localStorage.getItem("vmp3_api") || "";
    $("#quality-sel").value = settings.quality;
  } catch (e) { /* 后端离线时使用本地默认 */ }
}

async function saveSettings() {
  const body = {
    quality: $("#set-quality").value,
    concurrency: parseInt($("#set-concurrency").value, 10),
    sample_rate: parseInt($("#set-rate").value, 10),
    normalize_loudness: $("#set-normalize").checked,
    name_template: $("#set-template").value.trim() || "{artist} - {title}.mp3",
    embed_cover: $("#set-cover").checked,
  };
  // 服务地址保存在本机浏览器（前端静态托管时指向独立后端）
  const prevApi = (localStorage.getItem("vmp3_api") || "").replace(/\/+$/, "");
  const apiVal = $("#set-api").value.trim().replace(/\/+$/, "");
  localStorage.setItem("vmp3_api", apiVal);
  if (apiVal !== prevApi) { location.reload(); return; }
  try {
    const d = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    settings = { ...settings, ...d.settings };
    $("#quality-sel").value = settings.quality;
    toast(apiVal ? "设置已保存（服务地址：后端）" : "设置已保存");
  } catch (e) { toast(e.message); }
}

/* ── 面板切换 ─────────────────────────────────────── */
function switchPanel(name) {
  document.querySelectorAll("main > .panel").forEach((p) => { p.hidden = true; });
  $("#" + name + "-panel").hidden = false;
  document.querySelectorAll(".tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.panel === name);
  });
  if (name === "history") loadHistory();
}

/* ── 服务器状态 ───────────────────────────────────── */
async function checkHealth() {
  try {
    const d = await api("/api/health");
    $("#server-status").textContent = d.ok ? `服务正常 · ${d.time}` : "服务异常";
  } catch {
    $("#server-status").textContent = "服务离线，等待重连…";
  }
}

/* ── 初始化 ───────────────────────────────────────── */
function init() {
  // 事件绑定
  $("#btn-add").addEventListener("click", () => {
    const p = $("#add-panel");
    p.hidden = !p.hidden;
    if (!p.hidden) $("#url-input").focus();
  });
  $("#btn-paste").addEventListener("click", pasteClipboard);
  $("#btn-confirm-add").addEventListener("click", handleAdd);
  $("#btn-clear-done").addEventListener("click", () => {
    for (const jid of Object.keys(jobs)) {
      if (["done", "failed", "canceled"].includes(jobs[jid].status)) delete jobs[jid];
    }
    renderTasks();
  });
  $("#btn-clear-history").addEventListener("click", clearHistory);
  $("#history-search").addEventListener("input", () => loadHistory());
  $("#btn-save-settings").addEventListener("click", saveSettings);
  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => switchPanel(t.dataset.panel)));

  // 恢复暂停状态任务：页面刷新后所有旧任务对象丢失，服务端仍在跑——重新发现活动任务
  // （简化：不做持久化恢复，任务完成后自动刷新历史）

  loadSettings();
  checkHealth();
  setInterval(checkHealth, 20000);
  renderTasks();

  // PWA Service Worker（仅 https / localhost 生效）
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
}

document.addEventListener("DOMContentLoaded", init);
