"use strict";

const $ = (id) => document.getElementById(id);
const state = { selected: null, project: null, status: null, editors: new Map(), historyKey: "", busy: false, modeTouched: false, pollRunning: false };
const statusNames = { draft: "待生成", queued: "排队中", running: "生成中", interrupted: "已中断", cancelled: "已停止", failed: "生成失败", completed: "已完成", pending: "待处理" };
const stageNames = { planning: "编写故事与分镜", narration: "生成中文旁白", narrating: "生成中文旁白", tts: "生成中文旁白", video: "生成镜头画面", rendering: "生成镜头画面", assembling: "剪辑与字幕合成", completed: "成片已就绪", queued: "等待开始", cancelled: "任务已停止", failed: "处理失败" };
const activeStatuses = new Set(["running", "queued"]);
let toastTimer;

function notify(message, error = false) {
  $("toast").textContent = message; $("toast").className = error ? "error" : ""; $("toast").hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 9000 : 3500);
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...options.headers } });
  let body;
  try { body = await response.json(); } catch { throw new Error(`服务返回异常（${response.status}），请查看启动窗口。`); }
  if (!response.ok) throw new Error(body.error || `请求失败（${response.status}）`);
  return body;
}

function fileURL(project, relativePath) {
  return `/files/${encodeURIComponent(project)}/${relativePath.split(/[\\/]/).map(encodeURIComponent).join("/")}`;
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function projectURL(suffix = "") { return `/api/projects/${encodeURIComponent(state.selected)}${suffix}`; }

function renderStatus(status) {
  state.status = status;
  $("connection-dot").className = "dot online";
  $("connection-text").textContent = status.busy ? "本地任务运行中" : "本地服务已连接";
  $("version").textContent = status.version ? `v${status.version}` : "";
  if (!state.modeTouched && status.mode) {
    const radio = document.querySelector(`input[name="mode"][value="${status.mode === "real" ? "real" : "demo"}"]`);
    radio.checked = true; renderModeNote();
  }
  const diagnostics = status.diagnostics || { ready: false, checks: [] };
  $("readiness").className = `readiness ${diagnostics.ready ? "ready" : "unready"}`;
  const diagnosticMode = diagnostics.mode === "demo" ? "演示流程" : "真实生成环境";
  $("readiness").textContent = `${diagnostics.ready ? "✓" : "◌"} ${diagnosticMode}${diagnostics.ready ? "已就绪" : "待就绪"}`;
  $("checks").replaceChildren(...(diagnostics.checks || []).map(check => {
    const item = node("li");
    item.append(node("span", `check-icon${check.ok ? "" : " bad"}`, check.ok ? "✓" : "!"), node("strong", "", check.name), node("p", "", check.detail || ""));
    return item;
  }));
  if (!state.busy) $("create-button").textContent = status.busy ? "加入生成队列 ↗" : "创建并生成 ↗";
}

function renderModeNote() {
  const mode = document.querySelector('input[name="mode"]:checked').value;
  $("mode-note").textContent = mode === "demo" ? "演示模式不会生成 AI 画面，也不会调用配音模型。" : "真实模式调用本地模型；镜头生成可能需要较长时间，可在下方查看进度。";
}

function renderHistory(projects) {
  const key = JSON.stringify([state.selected, projects]);
  if (key === state.historyKey) return;
  state.historyKey = key;
  $("project-count").textContent = projects.length;
  if (!projects.length) { $("history").replaceChildren(node("p", "muted", "还没有项目。写下你的第一个故事吧。")); return; }
  $("history").replaceChildren(...projects.map(project => {
    const item = node("button", `history-item${project.id === state.selected ? " active" : ""}`);
    item.type = "button";
    item.append(node("span", "history-title", project.title || project.id));
    const meta = node("span", "history-meta");
    meta.append(node("span", "", `${project.mode === "demo" ? "演示 · " : ""}${statusNames[project.status] || project.status}`), node("span", "", project.updated_at ? new Date(project.updated_at).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" }) : ""));
    item.append(meta); item.addEventListener("click", () => openProject(project.id));
    return item;
  }));
}

async function openProject(id) {
  if (id !== state.selected && [...state.editors.values()].some(editor => editor.dirty)) {
    notify("当前镜头有未保存修改，请先保存后再切换项目。", true); return;
  }
  state.selected = id; state.historyKey = "";
  try { const project = await api(projectURL()); if (state.selected === id) renderProject(project); } catch (error) { notify(error.message, true); }
}

function renderProject(project) {
  const changedProject = state.project?.id !== project.id;
  state.project = project;
  $("empty-state").hidden = true; $("project-panel").hidden = false;
  $("project-title").textContent = project.title || "新的故事";
  $("project-prompt").textContent = project.prompt || "";
  $("project-status").className = `badge ${project.status}`;
  $("project-status").textContent = statusNames[project.status] || project.status;
  $("project-stage").textContent = stageNames[project.stage] || project.stage || statusNames[project.status] || "准备中";
  const progress = Math.max(0, Math.min(100, Number(project.progress) || 0));
  $("progress").value = progress; $("progress-text").textContent = `${Math.round(progress)}%`;
  $("project-error").hidden = !project.error; $("project-error").textContent = project.error || "";
  $("project-mode").textContent = project.mode === "demo" ? "流程演示 · 色块视频 / 静音旁白" : "真实生成 · 本地模型";
  const running = activeStatuses.has(project.status);
  $("resume-button").hidden = !["draft", "failed", "interrupted", "cancelled"].includes(project.status);
  $("cancel-button").hidden = !running;
  $("reassemble-button").disabled = running;
  $("output-panel").hidden = !project.output;
  const output = project.output ? fileURL(project.id, project.output) : "";
  if ($("output-video").dataset.file !== output) {
    $("output-video").dataset.file = output;
    if (output) $("output-video").src = output;
    else { $("output-video").removeAttribute("src"); $("output-video").load(); }
  }
  $("download-output").href = output;
  if (changedProject) { state.editors.clear(); $("shots").replaceChildren(); }
  $("shots-section").hidden = !(project.shots || []).length;
  const ids = new Set((project.shots || []).map(shot => shot.id));
  for (const [id, editor] of state.editors) if (!ids.has(id)) { editor.card.remove(); state.editors.delete(id); }
  for (const shot of project.shots || []) renderShot(shot, running);
  const events = project.events || [];
  $("event-count").textContent = `${events.length} 条`;
  $("events").replaceChildren(...events.slice(-30).reverse().map(event => {
    const item = node("li");
    item.append(node("time", "", event.at ? new Date(event.at).toLocaleTimeString("zh-CN", { hour12: false }) : ""), node("span", "", event.message || ""));
    return item;
  }));
}

function renderShot(shot, running) {
  let editor = state.editors.get(shot.id);
  if (!editor) {
    const card = node("article", "shot-card");
    const heading = node("div", "section-heading");
    const name = node("span", "shot-name", shot.id);
    const status = node("span", "shot-status");
    const lockLabel = node("label", "lock-label"), locked = node("input");
    locked.type = "checkbox"; lockLabel.append(locked, document.createTextNode("锁定镜头"));
    heading.append(name, status, lockLabel);
    const fields = node("div", "shot-fields");
    const prompt = node("textarea"), narration = node("textarea");
    for (const [labelText, field, fieldName] of [["画面提示词", prompt, "prompt"], ["旁白与字幕", narration, "narration"]]) {
      field.id = `${shot.id}-${fieldName}`; field.rows = 3;
      const label = node("label", "field-label", labelText); label.htmlFor = field.id;
      const wrap = node("div"); wrap.append(label, field); fields.append(wrap);
    }
    const footer = node("div", "shot-footer"), versions = node("select"), controls = node("div", "shot-buttons");
    versions.setAttribute("aria-label", `${shot.id} 镜头版本`);
    const dirtyNote = node("span", "dirty-note"), save = node("button", "button secondary", "保存"), retry = node("button", "button subtle", "重做镜头"), preview = node("a", "shot-preview", "查看画面 ↗");
    save.type = retry.type = "button"; preview.target = "_blank"; preview.rel = "noopener";
    controls.append(dirtyNote, save, retry); footer.append(versions, preview, controls);
    card.append(heading, fields, footer); $("shots").append(card);
    editor = { card, prompt, narration, locked, status, versions, save, retry, preview, dirtyNote, dirty: false, requestBusy: false, versionKey: "" };
    state.editors.set(shot.id, editor);
    const markDirty = () => { editor.dirty = true; editor.dirtyNote.textContent = "未保存"; editor.save.disabled = activeStatuses.has(state.project?.status) || editor.requestBusy; };
    prompt.addEventListener("input", markDirty); narration.addEventListener("input", markDirty); locked.addEventListener("change", markDirty);
    save.addEventListener("click", () => shotAction(shot.id, "save"));
    retry.addEventListener("click", () => shotAction(shot.id, "retry"));
    versions.addEventListener("change", () => shotAction(shot.id, "select"));
  }
  if (!editor.dirty && !editor.card.contains(document.activeElement)) {
    editor.prompt.value = shot.prompt || ""; editor.narration.value = shot.narration || ""; editor.locked.checked = Boolean(shot.locked);
  }
  editor.status.textContent = statusNames[shot.status] || shot.status || "";
  const versionKey = JSON.stringify([shot.versions, shot.selected_version]);
  if (editor.versionKey !== versionKey && document.activeElement !== editor.versions) {
    const versions = shot.versions || [];
    editor.versions.replaceChildren(...(versions.length ? versions.map(version => {
      const option = node("option", "", version.id); option.value = version.id; return option;
    }) : [node("option", "", "暂无版本")]));
    if (shot.selected_version) editor.versions.value = shot.selected_version;
    editor.versionKey = versionKey;
  }
  const disabled = running || editor.requestBusy;
  editor.prompt.disabled = editor.narration.disabled = disabled || Boolean(shot.locked);
  editor.locked.disabled = disabled;
  editor.retry.disabled = disabled || Boolean(shot.locked);
  editor.save.disabled = disabled || !editor.dirty;
  editor.versions.disabled = disabled || !(shot.versions || []).length;
  editor.preview.hidden = !shot.video;
  if (shot.video) editor.preview.href = fileURL(state.selected, shot.video);
}

async function shotAction(id, action) {
  const editor = state.editors.get(id), projectId = state.selected;
  if (action === "select" && editor.dirty) {
    editor.versions.value = state.project.shots.find(shot => shot.id === id).selected_version || "";
    notify("请先保存镜头修改，再选择版本。", true); return;
  }
  editor.requestBusy = true; renderShot(state.project.shots.find(shot => shot.id === id), false);
  try {
    const endpoint = `/api/projects/${encodeURIComponent(projectId)}/shots/${encodeURIComponent(id)}`;
    if (editor.dirty && action !== "select") {
      const current = state.project.shots.find(shot => shot.id === id), changes = {};
      for (const [key, value] of [["prompt", editor.prompt.value], ["narration", editor.narration.value], ["locked", editor.locked.checked]]) {
        if (value !== current[key]) changes[key] = value;
      }
      if (Object.keys(changes).length) await api(endpoint, { method: "PATCH", body: JSON.stringify(changes) });
      editor.dirty = false; editor.dirtyNote.textContent = "";
    }
    if (action === "retry") await api(`${endpoint}/retry`, { method: "POST", body: "{}" });
    if (action === "select") await api(`${endpoint}/select`, { method: "POST", body: JSON.stringify({ version: editor.versions.value }) });
    notify(action === "retry" ? "镜头重做已提交。" : action === "select" ? "已选择镜头版本，正在更新成片。" : "镜头内容已保存。");
    if (state.selected === projectId) renderProject(await api(projectURL()));
  } catch (error) { notify(error.message, true); editor.versionKey = ""; }
  finally { editor.requestBusy = false; if (state.selected === projectId) renderProject(state.project); }
}

async function projectAction(action, button) {
  if (action === "run" && [...state.editors.values()].some(editor => editor.dirty)) { notify("请先保存镜头修改，再继续生成。", true); return; }
  button.disabled = true;
  try { await api(projectURL(`/${action}`), { method: "POST", body: "{}" }); renderProject(await api(projectURL())); }
  catch (error) { notify(error.message, true); }
  finally { button.disabled = false; }
}

$("create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = $("prompt").value.trim(); if (!prompt) return;
  if ([...state.editors.values()].some(editor => editor.dirty)) { notify("当前项目有未保存的镜头修改，请先保存。", true); return; }
  state.busy = true; $("create-button").disabled = true; $("create-button").textContent = "正在创建…";
  try {
    const project = await api("/api/projects", { method: "POST", body: JSON.stringify({ prompt, mode: document.querySelector('input[name="mode"]:checked').value, shot_count: Number($("shot-count").value) }) });
    state.selected = project.id; renderProject(project); state.historyKey = "";
    $("project-panel").scrollIntoView({ behavior: "smooth", block: "start" }); await refresh();
  } catch (error) { notify(error.message, true); }
  finally { state.busy = false; $("create-button").disabled = false; $("create-button").textContent = state.status?.busy ? "加入生成队列 ↗" : "创建并生成 ↗"; }
});
document.querySelectorAll('input[name="mode"]').forEach(input => input.addEventListener("change", () => { state.modeTouched = true; renderModeNote(); }));
$("resume-button").addEventListener("click", () => projectAction("run", $("resume-button")));
$("reassemble-button").addEventListener("click", () => projectAction("run", $("reassemble-button")));
$("cancel-button").addEventListener("click", () => projectAction("cancel", $("cancel-button")));
$("refresh-status").addEventListener("click", async () => { try { await api("/api/diagnostics", { method: "POST", body: "{}" }); renderStatus(await api("/api/status")); notify("部署状态已更新。"); } catch (error) { notify(error.message, true); } });

async function refresh() {
  if (state.pollRunning) return;
  state.pollRunning = true;
  try {
    const results = await Promise.allSettled([api("/api/status"), api("/api/projects")]);
    if (results[0].status === "fulfilled") renderStatus(results[0].value);
    else { $("connection-dot").className = "dot offline"; $("connection-text").textContent = "本地服务暂未连接"; }
    if (results[1].status === "fulfilled") renderHistory(results[1].value.projects || []);
    if (state.selected) {
      const selected = state.selected;
      try { const project = await api(projectURL()); if (selected === state.selected) renderProject(project); }
      catch (error) { $("connection-text").textContent = "项目更新失败，正在重试"; }
    }
  } finally { state.pollRunning = false; }
}
refresh();
setInterval(refresh, 2000);
