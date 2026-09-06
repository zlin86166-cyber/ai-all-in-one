"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

const state = {
  data: null,
  projectId: localStorage.getItem("aihub.project") || null,
  conversationId: localStorage.getItem("aihub.conversation") || null,
  conversation: null,
  messages: [],
  tasks: [],
  selectedProviders: JSON.parse(localStorage.getItem("aihub.providers") || "[]"),
  selectedFiles: new Set(),
  drawerFiles: new Set(),
  filePath: null,
  fileParent: null,
  feasibility: null,
  currentView: "chat",
  pollBusy: false,
  lastProviderRefresh: 0,
  taskModalId: null,
  taskEventCursor: 0,
  terminalTaskIds: new Set(),
  terminalEventCursor: new Map(),
  pendingApproval: null,
  approvalRetry: null,
  imageStatus: null,
  modelSyncTaskId: null,
};

async function api(path, options = {}) {
  const init = { ...options, headers: { ...(options.headers || {}) } };
  if (init.body && typeof init.body !== "string") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(init.body);
  }
  const response = await fetch(path, init);
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof data === "object" ? data.error || `HTTP ${response.status}` : data;
    throw new ApiError(message, response.status, data);
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function inlineMarkdown(text) {
  let safe = escapeHtml(text);
  safe = safe.replace(/`([^`]+)`/g, "<code>$1</code>");
  safe = safe.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  safe = safe.replace(/(https?:\/\/[^\s<]+)/g, (url) => `<a href="${url}" target="_blank" rel="noreferrer">${url}</a>`);
  return safe;
}

function markdown(text) {
  const parts = String(text ?? "").split(/```/);
  return parts.map((part, index) => {
    if (index % 2) {
      const body = part.replace(/^[a-zA-Z0-9_+.-]+\n/, "");
      return `<pre><code>${escapeHtml(body)}</code></pre>`;
    }
    const lines = part.split(/\r?\n/);
    const output = [];
    let listType = null;
    for (const line of lines) {
      const bullet = line.match(/^\s*[-*]\s+(.+)/);
      const numbered = line.match(/^\s*\d+[.)]\s+(.+)/);
      if (bullet || numbered) {
        const nextType = bullet ? "ul" : "ol";
        if (listType !== nextType) {
          if (listType) output.push(`</${listType}>`);
          output.push(`<${nextType}>`);
          listType = nextType;
        }
        output.push(`<li>${inlineMarkdown((bullet || numbered)[1])}</li>`);
        continue;
      }
      if (listType) {
        output.push(`</${listType}>`);
        listType = null;
      }
      if (!line.trim()) {
        output.push("");
      } else if (/^#{1,3}\s/.test(line)) {
        output.push(`<p><strong>${inlineMarkdown(line.replace(/^#{1,3}\s+/, ""))}</strong></p>`);
      } else {
        output.push(`<p>${inlineMarkdown(line)}</p>`);
      }
    }
    if (listType) output.push(`</${listType}>`);
    return output.join("");
  }).join("");
}

function providerClass(provider) {
  if (!provider) return "compatible";
  if (provider.kind === "local" || provider.id?.startsWith("ollama:")) return "local";
  return provider.id === "collaboration" ? "collaboration" : provider.id;
}

function providerInitial(provider) {
  const id = provider?.id || "AI";
  if (id === "codex") return "CX";
  if (id === "gemini") return "GM";
  if (id === "collaboration") return "TEAM";
  if (id === "terminal") return ">_";
  if (id === "comfyui-image") return "IMG";
  if (id.startsWith("ollama:")) return "LLM";
  return "AI";
}

function findProvider(id) {
  return state.data?.providers.find((item) => item.id === id) || {
    id,
    label: id === "collaboration" ? "AI 團隊" : id === "comfyui-image" ? "ComfyUI 繪圖" : id,
    kind: id?.startsWith("ollama:") ? "local" : "api",
    available: true,
    detail: "",
  };
}

function toast(message, type = "normal", duration = 3800) {
  const element = document.createElement("div");
  element.className = `toast ${type}`;
  element.textContent = message;
  $("#toast-region").append(element);
  setTimeout(() => element.remove(), duration);
}

function formatTime(value, includeDate = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-TW", {
    ...(includeDate ? { month: "numeric", day: "numeric" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatRelative(value) {
  if (!value) return "—";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return "剛剛";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分鐘前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小時前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function durationLabel(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return "—";
  const total = Math.max(0, Math.round(Number(seconds)));
  if (total < 60) return `${total} 秒`;
  if (total < 3600) return `${Math.floor(total / 60)} 分 ${total % 60} 秒`;
  return `${Math.floor(total / 3600)} 小時 ${Math.floor((total % 3600) / 60)} 分`;
}

function taskDisplayProgress(task) {
  if (task.status === "completed") return 100;
  const actual = Number(task.progress || 0);
  return actual > 1 ? Math.max(0, Math.min(99, actual)) : null;
}

function progressLabel(progress) {
  return progress == null ? "進度依事件" : `${Math.round(progress)}%`;
}

function taskRemaining(task) {
  if (!["running", "queued", "cancelling"].includes(task.status)) return 0;
  if (!task.predicted_end_at) return null;
  return Math.max(0, (new Date(task.predicted_end_at).getTime() - Date.now()) / 1000);
}

function fileSize(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(1)} GB`;
}

async function initialize() {
  try {
    state.data = await api("/api/bootstrap");
    chooseValidProjectAndChat();
    chooseValidProviders();
    bindEvents();
    fillSettingsForm();
    renderAll();
    await loadConversation(false);
    renderAll();
    setInterval(refreshLive, 1600);
    setInterval(refreshTerminalEvents, 850);
  } catch (error) {
    console.error(error);
    document.body.innerHTML = `<main style="padding:40px;font-family:Segoe UI"><h1>AI Hub 無法啟動</h1><p>${escapeHtml(error.message)}</p></main>`;
  }
}

function chooseValidProjectAndChat() {
  const projects = state.data.projects || [];
  if (!projects.some((item) => item.id === state.projectId)) state.projectId = projects[0]?.id || null;
  let conversations = state.data.conversations || [];
  const matching = conversations.filter((item) => item.project_id === state.projectId);
  if (!matching.some((item) => item.id === state.conversationId)) {
    state.conversationId = matching[0]?.id || conversations[0]?.id || null;
  }
  localStorage.setItem("aihub.project", state.projectId || "");
  localStorage.setItem("aihub.conversation", state.conversationId || "");
}

function chooseValidProviders() {
  const available = state.data.providers.filter((item) => item.available && item.id !== "ollama:empty");
  state.selectedProviders = state.selectedProviders.filter((id) => available.some((item) => item.id === id));
  if (!state.selectedProviders.length && available.length) {
    const preferred = available.find((item) => item.id === "codex") || available.find((item) => item.kind === "local") || available[0];
    state.selectedProviders = [preferred.id];
  }
  localStorage.setItem("aihub.providers", JSON.stringify(state.selectedProviders));
}

async function loadConversation(scroll = true) {
  if (!state.conversationId) return;
  try {
    const payload = await api(`/api/conversations/${encodeURIComponent(state.conversationId)}`);
    state.conversation = payload.conversation;
    state.messages = payload.messages;
    state.tasks = payload.tasks;
    const recent = [...state.messages].reverse().find((item) => item.metadata?.feasibility);
    if (!state.feasibility && recent) state.feasibility = recent.metadata.feasibility;
    renderConversation();
    renderTasks();
    renderCurrentRun();
    if (scroll) scrollChat();
  } catch (error) {
    if (error.status === 404) {
      state.conversationId = state.data.conversations[0]?.id || null;
      return;
    }
    toast(error.message, "error");
  }
}

async function refreshLive() {
  if (state.pollBusy || !state.data) return;
  state.pollBusy = true;
  try {
    const requests = [api("/api/system")];
    if (state.conversationId) requests.push(api(`/api/conversations/${encodeURIComponent(state.conversationId)}`));
    const refreshProviders = Date.now() - state.lastProviderRefresh > 12000;
    if (refreshProviders) requests.push(api("/api/providers"));
    const results = await Promise.all(requests);
    state.data.system = results[0];
    if (state.conversationId) {
      const payload = results[1];
      const messageChanged = payload.messages.length !== state.messages.length || payload.messages.at(-1)?.id !== state.messages.at(-1)?.id;
      state.conversation = payload.conversation;
      state.messages = payload.messages;
      state.tasks = payload.tasks;
      if (messageChanged) renderConversation();
    }
    if (refreshProviders) {
      state.data.providers = results.at(-1);
      state.lastProviderRefresh = Date.now();
      chooseValidProviders();
      renderProviderMenu();
      renderSelectedProviders();
      renderConnections();
    }
    renderSystem();
    if (state.currentView === "integrations") renderIntegrations();
    if (state.modelSyncTaskId) {
      const syncTask = state.tasks.find((item) => item.id === state.modelSyncTaskId);
      if (syncTask && ["completed", "failed", "cancelled"].includes(syncTask.status)) {
        state.modelSyncTaskId = null;
        if (syncTask.status === "completed") refreshModels();
      }
    }
    renderLiveTasks();
    renderCurrentRun();
    if (state.currentView === "tasks") renderTasks();
    if (state.currentView === "images") renderImages();
    if (state.taskModalId) refreshTaskModal();
    const active = state.tasks.filter((task) => ["queued", "running", "cancelling"].includes(task.status));
    $("#active-task-count").textContent = active.length;
    $("#active-task-count").classList.toggle("hidden", !active.length);
  } catch (error) {
    console.warn("Live refresh failed", error);
  } finally {
    state.pollBusy = false;
  }
}

function renderAll() {
  renderProjects();
  renderConversations();
  renderProviderMenu();
  renderSelectedProviders();
  renderConversation();
  renderTasks();
  renderSystem();
  renderCurrentRun();
  renderTeam();
  renderConnections();
  renderModels();
  renderImages();
  renderSchedules();
  renderResearch();
  renderIntegrations();
  renderPermissions();
  renderSelectedFileChips();
}

function renderProjects() {
  const select = $("#project-select");
  select.innerHTML = (state.data.projects || []).map((project) =>
    `<option value="${escapeHtml(project.id)}" ${project.id === state.projectId ? "selected" : ""}>${escapeHtml(project.name)}</option>`
  ).join("");
  const project = state.data.projects.find((item) => item.id === state.projectId);
  $("#terminal-project").textContent = project?.name || "project";
}

function renderConversations() {
  const list = $("#conversation-list");
  const conversations = (state.data.conversations || []).filter((item) => item.project_id === state.projectId);
  list.innerHTML = conversations.length ? conversations.map((conversation) => `
    <button class="conversation-item ${conversation.id === state.conversationId ? "active" : ""}" data-conversation-id="${escapeHtml(conversation.id)}" title="${escapeHtml(conversation.title)}">
      <svg viewBox="0 0 24 24"><path d="M20 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h9a4 4 0 0 1 4 4v8Z"/></svg>
      <span>${escapeHtml(conversation.title)}</span>
    </button>`).join("") : `<div class="empty-list" style="padding:18px 8px">尚無對話</div>`;
  $$(".conversation-item", list).forEach((button) => button.addEventListener("click", async () => {
    state.conversationId = button.dataset.conversationId;
    localStorage.setItem("aihub.conversation", state.conversationId);
    await loadConversation();
    renderConversations();
    switchView("chat");
  }));
}

function renderConversation() {
  const empty = $("#empty-state");
  const messages = $("#messages");
  empty.classList.toggle("hidden", state.messages.length > 0);
  messages.classList.toggle("hidden", state.messages.length === 0);
  $("#current-title").textContent = state.conversation?.title || "新對話";
  messages.innerHTML = state.messages.map((message) => {
    const isUser = message.role === "user";
    const provider = findProvider(message.provider_id || (isUser ? "user" : "compatible"));
    const files = message.metadata?.selected_files || [];
    const images = message.metadata?.images || [];
    const imageHtml = images.length ? `<div class="message-images">${images.map((image) => `<a href="${escapeHtml(image.url)}" target="_blank" rel="noreferrer"><img src="${escapeHtml(image.url)}" alt="生成圖片"></a>`).join("")}</div>` : "";
    const taskId = message.metadata?.task_id;
    const feedbackHtml = taskId && !message.metadata?.error ? `<div class="message-feedback"><span>這次完成你的要求嗎？</span><button data-task-feedback="${escapeHtml(taskId)}" data-success="true">完成</button><button data-task-feedback="${escapeHtml(taskId)}" data-success="false">未完成</button></div>` : "";
    if (isUser) {
      return `<article class="message user" data-message-id="${escapeHtml(message.id)}"><div class="message-content">${markdown(message.content)}${files.length ? `<div class="message-files">${files.map((file) => `<span class="message-file">${escapeHtml(file.split(/[\\/]/).pop())}</span>`).join("")}</div>` : ""}</div></article>`;
    }
    return `<article class="message assistant" data-message-id="${escapeHtml(message.id)}">
      <div class="message-avatar ${providerClass(provider)}">${escapeHtml(providerInitial(provider))}</div>
      <div class="message-body"><div class="message-meta"><strong>${escapeHtml(provider.label)}</strong><span>${formatTime(message.created_at)}</span></div><div class="message-content">${markdown(message.content)}${imageHtml}${feedbackHtml}</div></div>
    </article>`;
  }).join("");
  $$('[data-task-feedback]', messages).forEach((button) => button.addEventListener("click", () => submitTaskFeedback(button)));
  renderLiveTasks();
}

async function submitTaskFeedback(button) {
  try {
    await api(`/api/tasks/${encodeURIComponent(button.dataset.taskFeedback)}/feedback`, {
      method: "POST",
      body: { success: button.dataset.success === "true" },
    });
    const group = button.closest(".message-feedback");
    if (group) group.innerHTML = `<span>已記錄，之後的成功率判定會用這筆結果校準。</span>`;
  } catch (error) {
    toast(error.message, "error");
  }
}

function scrollChat() {
  requestAnimationFrame(() => {
    const container = $("#chat-scroll");
    container.scrollTop = container.scrollHeight;
  });
}

function renderLiveTasks() {
  const container = $("#live-tasks");
  const active = state.tasks.filter((task) => ["queued", "running", "cancelling"].includes(task.status));
  container.innerHTML = active.map((task) => {
    const progress = taskDisplayProgress(task);
    return `<button class="live-task-card" data-task-id="${escapeHtml(task.id)}" style="display:block;width:calc(100% - 41px);text-align:left;cursor:pointer">
      <div class="live-task-head"><i class="task-spinner"></i><strong>${escapeHtml(task.title)}</strong><span>${escapeHtml(task.stage)} · ${progressLabel(progress)}</span></div>
      <div class="thin-progress"><i style="width:${progress ?? 0}%"></i></div>
    </button>`;
  }).join("");
  $$('[data-task-id]', container).forEach((element) => element.addEventListener("click", () => openTaskModal(element.dataset.taskId)));
}

function renderProviderMenu() {
  const menu = $("#provider-menu");
  const providers = state.data.providers || [];
  menu.innerHTML = providers.map((provider) => {
    const selected = state.selectedProviders.includes(provider.id);
    const klass = providerClass(provider);
    return `<button class="provider-option ${selected ? "selected" : ""} ${provider.available ? "" : "unavailable"}" data-provider-id="${escapeHtml(provider.id)}" ${provider.available ? "" : "aria-disabled=\"true\""}>
      <span class="provider-logo ${klass}">${escapeHtml(providerInitial(provider))}</span>
      <span class="provider-option-copy"><strong>${escapeHtml(provider.label)}</strong><small>${escapeHtml(provider.detail)}</small></span>
      <span class="provider-check"><svg viewBox="0 0 24 24"><path d="m6 12 4 4 8-8"/></svg></span>
    </button>`;
  }).join("");
  $$(".provider-option", menu).forEach((button) => button.addEventListener("click", () => {
    const provider = findProvider(button.dataset.providerId);
    if (!provider.available) {
      toast(`${provider.label} 尚未就緒`, "error");
      switchView("models");
      menu.classList.add("hidden");
      return;
    }
    const id = provider.id;
    if (state.selectedProviders.includes(id)) {
      if (state.selectedProviders.length === 1) {
        toast("至少保留一個 AI", "error");
        return;
      }
      state.selectedProviders = state.selectedProviders.filter((item) => item !== id);
    } else {
      state.selectedProviders.push(id);
    }
    localStorage.setItem("aihub.providers", JSON.stringify(state.selectedProviders));
    renderProviderMenu();
    renderSelectedProviders();
    renderTeam();
  }));
}

function renderSelectedProviders() {
  const selected = state.selectedProviders.map(findProvider);
  $("#provider-dots").innerHTML = selected.slice(0, 4).map((provider) => `<i class="provider-dot ${providerClass(provider)}"></i>`).join("");
  $("#provider-picker-label").textContent = selected.length === 1 ? selected[0].label : `${selected.length} 個 AI`;
  $("#selected-agents").innerHTML = selected.length ? selected.map((provider) => `
    <div class="selected-agent"><span class="provider-logo ${providerClass(provider)}">${escapeHtml(providerInitial(provider))}</span><span class="selected-agent-copy"><strong>${escapeHtml(provider.label)}</strong><small>${escapeHtml(provider.kind === "local" ? "本機模型" : provider.kind === "cli" ? "CLI 已連線" : "API 連線")}</small></span><i class="online-dot"></i></div>`).join("") : `<div class="run-empty">尚未選取 AI</div>`;
  const ready = (state.data.providers || []).filter((item) => item.available).length;
  $("#sidebar-status").textContent = `${ready} 個 AI 可用`;
}

function renderSystem() {
  const system = state.data.system || {};
  const memory = system.memory?.percent ?? 0;
  const cpu = system.cpu_percent ?? 0;
  $("#memory-value").textContent = `${memory}%`;
  $("#memory-meter").style.width = `${memory}%`;
  $("#memory-meter").classList.toggle("high", memory >= 90);
  $("#cpu-value").textContent = `${Math.round(cpu)}%`;
  $("#cpu-meter").style.width = `${cpu}%`;
  $("#cpu-meter").classList.toggle("high", cpu >= 90);
  const power = system.power || {};
  $("#power-state").textContent = power.ac_connected ? `已接電${system.performance_boost_active ? " · 效能增益" : ""}` : `電池 ${power.battery_percent ?? "—"}%`;
  $("#disk-state").textContent = `${system.disk?.free_gb ?? "—"} GB 可用`;
}

function renderFeasibility() {
  const result = state.feasibility;
  const ring = $("#score-ring");
  if (!result) {
    ring.style.setProperty("--score", 0);
    $("#score-value").textContent = "—";
    $("#score-label").textContent = "尚未評估";
    $("#score-confidence").textContent = "送出工作後顯示信心度";
    $("#factor-mini-list").innerHTML = "";
    return;
  }
  ring.style.setProperty("--score", result.score);
  $("#score-value").textContent = result.score;
  $("#score-label").textContent = result.label;
  const calibration = result.calibration || {};
  $("#score-confidence").textContent = `信心度 ${result.confidence}% · ${calibration.verified_samples || 0} 筆使用者驗證 / ${calibration.samples || result.history_samples} 筆執行資料`;
  $("#factor-mini-list").innerHTML = (result.factors || []).slice(0, 5).map((factor) => `
    <div class="factor-mini" title="${escapeHtml(factor.evidence)}"><span>${escapeHtml(factor.label)}</span><span class="mini-meter"><i style="width:${factor.score}%"></i></span><strong>${factor.score}</strong></div>`).join("");
}

function renderCurrentRun() {
  const active = state.tasks.filter((task) => ["queued", "running", "cancelling"].includes(task.status)).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  const task = active[0];
  $("#run-empty").classList.toggle("hidden", Boolean(task));
  $("#run-detail").classList.toggle("hidden", !task);
  $("#run-status").textContent = task ? task.status === "queued" ? "排隊中" : "執行中" : "待命";
  if (task) {
    const progress = taskDisplayProgress(task);
    $("#run-title").textContent = `${task.title} · ${task.stage}`;
    $("#run-progress").style.width = `${progress ?? 0}%`;
    $("#run-eta").textContent = durationLabel(taskRemaining(task));
    $("#run-end").textContent = formatTime(task.predicted_end_at);
    $("#run-detail").onclick = () => openTaskModal(task.id);
  }
  renderFeasibility();
}

function renderTeam() {
  const labels = [
    ["成功性判定", "檢查硬體、依賴與可測試性"],
    ["主 AI 規劃", "決定順序、分工與相依"],
    ["安全並行執行", "研究可並行，寫入依序完成"],
    ["交叉驗證", "另一個選取 AI 重跑測試"],
  ];
  $("#team-flow").innerHTML = labels.map((item, index) => `<div class="flow-step"><span class="flow-number">${index + 1}</span><strong>${item[0]}</strong><small>${item[1]}</small></div>`).join("");
  const providers = state.selectedProviders.map(findProvider);
  const html = providers.length ? providers.map((provider, index) => `
    <div class="team-provider"><span class="provider-logo ${providerClass(provider)}">${escapeHtml(providerInitial(provider))}</span><div><strong>${escapeHtml(provider.label)}</strong><small>${index === 0 ? "主協調與最後彙整" : "執行與交叉監看"}</small></div></div>`).join("") : `<div class="empty-list">尚未選取 AI</div>`;
  $("#team-provider-list").innerHTML = html;
  $("#schedule-providers").innerHTML = html;
}

function taskStatusIcon(task) {
  if (task.status === "completed") return `<span class="task-status-icon"><svg viewBox="0 0 24 24"><path d="m6 12 4 4 8-8"/></svg></span>`;
  if (["failed", "cancelled"].includes(task.status)) return `<span class="task-status-icon failed"><svg viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17"/></svg></span>`;
  return `<span class="task-status-icon running"><i class="task-spinner"></i></span>`;
}

function renderTasks() {
  const all = state.tasks || [];
  const active = all.filter((task) => ["queued", "running", "cancelling"].includes(task.status));
  const completed = all.filter((task) => task.status === "completed");
  const failed = all.filter((task) => ["failed", "cancelled"].includes(task.status));
  const average = completed.length ? Math.round(completed.reduce((sum, task) => {
    if (!task.started_at || !task.completed_at) return sum;
    return sum + (new Date(task.completed_at) - new Date(task.started_at)) / 1000;
  }, 0) / completed.length) : 0;
  $("#task-metrics").innerHTML = [
    ["執行中", active.length],
    ["已完成", completed.length],
    ["失敗 / 停止", failed.length],
    ["平均耗時", durationLabel(average)],
  ].map((item) => `<div class="metric-card"><span>${item[0]}</span><strong>${item[1]}</strong></div>`).join("");
  $("#task-list").innerHTML = all.length ? all.map((task) => {
    const provider = findProvider(task.provider_id);
    const progress = taskDisplayProgress(task);
    const remaining = taskRemaining(task);
    return `<article class="task-row" data-task-id="${escapeHtml(task.id)}">
      <div class="task-primary"><span class="provider-logo ${providerClass(provider)}">${escapeHtml(providerInitial(provider))}</span><div><strong>${escapeHtml(task.title)}</strong><small>${escapeHtml(provider.label)} · ${formatRelative(task.created_at)}</small></div></div>
      <div class="task-stage"><span>${escapeHtml(task.stage)}</span><small>${escapeHtml(task.status)}</small></div>
      <div class="task-progress-cell"><div class="thin-progress"><i style="width:${progress ?? 0}%"></i></div><strong>${progressLabel(progress)}</strong></div>
      <div class="task-times"><span>${remaining == null ? formatTime(task.completed_at) : durationLabel(remaining)}</span><small>${remaining == null ? "完成時間" : `預計 ${formatTime(task.predicted_end_at)}`}</small></div>
      ${taskStatusIcon(task)}
    </article>`;
  }).join("") : `<div class="empty-list">這個對話尚無執行紀錄</div>`;
  $$(".task-row", $("#task-list")).forEach((row) => row.addEventListener("click", () => openTaskModal(row.dataset.taskId)));
}

function renderConnections() {
  $("#connection-grid").innerHTML = (state.data.providers || []).filter((item) => !item.id.startsWith("ollama:") || item.available).slice(0, 8).map((provider) => `
    <article class="connection-card"><div class="connection-head"><span class="provider-logo ${providerClass(provider)}">${escapeHtml(providerInitial(provider))}</span><div><strong>${escapeHtml(provider.label)}</strong><small>${escapeHtml(provider.kind.toUpperCase())}</small></div></div><div class="connection-state ${provider.available ? "available" : ""}"><i></i><span>${escapeHtml(provider.available ? "已連線" : provider.detail)}</span></div></article>`).join("");
}

function renderModels() {
  const catalog = state.data.models || [];
  $("#model-grid").innerHTML = catalog.map((model) => {
    const status = model.compatibility?.state || "remote";
    const labels = { ready: "可使用", available: "可下載", remote: "需遠端節點", blocked: "空間不足" };
    const canPull = model.install && ["available", "ready"].includes(status) && !model.installed;
    return `<article class="model-card">
      <div class="model-card-top"><span class="model-family-mark ${escapeHtml(model.family)}">${escapeHtml(model.family === "DeepSeek" ? "DS" : model.family === "Kimi" ? "K" : "IMG")}</span><div class="model-title"><h3>${escapeHtml(model.label)}</h3><p>${escapeHtml(model.notes)}</p></div><span class="compatibility-tag ${status}">${labels[status] || status}</span></div>
      <div class="model-specs"><span><strong>${model.parameters_b ?? "—"}B</strong> 參數</span><span><strong>${model.ram_gb} GB</strong> RAM</span><span><strong>${model.disk_gb} GB</strong> 磁碟</span></div>
      <div class="model-card-footer"><span>${escapeHtml(model.compatibility?.reason || "")}</span>${canPull ? `<button class="primary-button model-pull" data-model-id="${escapeHtml(model.id)}">下載</button>` : model.source ? `<button class="soft-button model-source" data-source="${escapeHtml(model.source)}">官方頁面</button>` : ""}</div>
    </article>`;
  }).join("");
  $$(".model-pull").forEach((button) => button.addEventListener("click", () => pullModel(button.dataset.modelId)));
  $$(".model-source").forEach((button) => button.addEventListener("click", () => window.open(button.dataset.source, "_blank", "noopener")));
  const readiness = state.data.model_readiness || {};
  $("#training-readiness").innerHTML = `<span class="note-mark"><svg viewBox="0 0 24 24"><path d="M12 3 2.8 20h18.4L12 3Z"/><path d="M12 9v5M12 17.5v.1"/></svg></span><div><strong>${readiness.lora_training?.ready ? "這台電腦可進行 LoRA 訓練" : "這台電腦不符合 32B / 48B 訓練需求"}</strong><span>${escapeHtml(readiness.lora_training?.detected || "")}。${escapeHtml(readiness.lora_training?.requires || "")}。模型下載與真正權重訓練會分開顯示。</span></div>`;
}

function renderImages() {
  const status = state.imageStatus;
  const stateElement = $("#image-node-state");
  if (status) {
    stateElement.textContent = status.available && status.checkpoints?.length ? "可使用" : status.available ? "缺少模型" : "未連線";
    stateElement.classList.toggle("green", Boolean(status.available && status.checkpoints?.length));
    $("#image-node-detail").textContent = `${status.detail} · ${status.base_url}`;
    const checkpoint = $("#image-checkpoint");
    const previous = checkpoint.value;
    checkpoint.innerHTML = status.checkpoints?.length
      ? status.checkpoints.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("")
      : `<option value="">尚無可用 checkpoint</option>`;
    checkpoint.value = status.checkpoints?.includes(previous) ? previous : status.selected_checkpoint || status.checkpoints?.[0] || "";
    $("#generate-image").disabled = !(status.available && status.checkpoints?.length);
  } else {
    stateElement.textContent = "檢查中";
    $("#generate-image").disabled = true;
  }
  const generated = (state.tasks || [])
    .filter((task) => task.provider_id === "comfyui-image" && task.metadata?.images?.length)
    .flatMap((task) => task.metadata.images.map((image) => ({ task, image })));
  $("#image-gallery").innerHTML = generated.length ? generated.map(({ task, image }) => `
    <article class="image-card"><a class="image-card-preview" href="${escapeHtml(image.url)}" target="_blank" rel="noreferrer"><img src="${escapeHtml(image.url)}" alt="${escapeHtml(task.metadata?.prompt || "AI 生成圖片")}"></a><div class="image-card-copy"><strong>${escapeHtml(task.metadata?.prompt || task.title)}</strong><small>${task.metadata?.width || "—"} × ${task.metadata?.height || "—"} · seed ${task.metadata?.seed || "—"}</small></div></article>`).join("") : `<div class="image-placeholder">${status?.available ? "尚無生成圖片" : "連接 ComfyUI 後即可開始繪圖"}</div>`;
}

async function refreshImages() {
  try {
    state.imageStatus = await api("/api/images/status");
    renderImages();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function generateImage() {
  const prompt = $("#image-prompt").value.trim();
  if (!prompt) {
    toast("請先輸入繪圖提示", "error");
    return;
  }
  $("#generate-image").disabled = true;
  try {
    const task = await api("/api/images/generate", { method: "POST", body: {
      prompt,
      negative: $("#image-negative").value.trim(),
      checkpoint: $("#image-checkpoint").value,
      width: Number($("#image-width").value),
      height: Number($("#image-height").value),
      steps: Number($("#image-steps").value),
      project_id: state.projectId,
      conversation_id: state.conversationId,
    }});
    state.tasks.unshift(task);
    toast("繪圖工作已排入，可在執行進度查看");
    renderImages();
    renderTasks();
  } catch (error) {
    toast(error.message, "error", 6000);
  } finally {
    $("#generate-image").disabled = !(state.imageStatus?.available && state.imageStatus?.checkpoints?.length);
  }
}

function renderSchedules() {
  const schedules = state.data.schedules || [];
  $("#schedule-list").innerHTML = schedules.length ? schedules.map((schedule) => `
    <article class="schedule-row"><div class="schedule-primary"><span class="schedule-icon"><svg viewBox="0 0 24 24">${schedule.mode === "image" ? '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="m5 17 4-4 3 3 3-2 4 3"/>' : '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/>'}</svg></span><div><strong>${escapeHtml(schedule.name)}</strong><small>${schedule.mode === "image" ? "ComfyUI 繪圖" : escapeHtml((schedule.provider_ids || []).map((id) => findProvider(id).label).join(" · "))}</small></div></div><div class="schedule-cell"><span>${escapeHtml(schedule.start_time)}–${escapeHtml(schedule.end_time)}</span><small>允許時段</small></div><div class="schedule-cell"><span>每 ${schedule.interval_minutes || 1440} 分</span><small>單次上限 ${schedule.duration_minutes} 分</small></div><div class="schedule-actions"><button class="soft-button schedule-toggle" data-id="${escapeHtml(schedule.id)}">${schedule.enabled ? "暫停" : "啟用"}</button><button class="icon-button schedule-delete" data-id="${escapeHtml(schedule.id)}" title="刪除"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 3h6l1 4H8l1-4ZM7 7l1 14h8l1-14M10 11v6M14 11v6"/></svg></button></div></article>`).join("") : `<div class="schedule-empty">尚未建立排程。新增後，工作台開啟期間會在指定時段自動開始。</div>`;
  $$(".schedule-toggle").forEach((button) => button.addEventListener("click", () => updateSchedule(button.dataset.id, "toggle")));
  $$(".schedule-delete").forEach((button) => button.addEventListener("click", () => updateSchedule(button.dataset.id, "delete")));
}

function renderResearch() {
  const docs = state.data.research || [];
  $("#research-list").innerHTML = docs.length ? docs.map((document) => `
    <article class="research-card"><h3>${escapeHtml(document.title)}</h3><a href="${escapeHtml(document.url)}" target="_blank" rel="noreferrer">${escapeHtml(document.url)}</a><p>${escapeHtml(document.excerpt || "")}</p></article>`).join("") : `<div class="research-empty">尚未擷取任何來源。</div>`;
  $("#crawler-enabled").checked = Boolean(state.data.settings?.crawler_enabled);
}

function renderPermissions() {
  const settings = state.data.settings || {};
  const unlocked = Boolean(settings.full_access_unlocked);
  $("#permission-state").textContent = unlocked ? "完整權限已解鎖" : `預設：${permissionModeLabel(settings.permission_mode)}`;
  $("#permission-state").classList.toggle("unlocked", unlocked);
  $("#unlock-full-access").textContent = unlocked ? "立即鎖定" : "解鎖完整權限";
  $("#approval-count").textContent = (state.data.approvals || []).length;
  $("#approval-list").innerHTML = (state.data.approvals || []).length ? state.data.approvals.map((approval) => `
    <div class="approval-row"><strong>${escapeHtml(approval.kind.toUpperCase())}</strong><p>${escapeHtml(approval.summary)}</p><div class="approval-actions"><button class="primary-button inline-approval" data-id="${escapeHtml(approval.id)}" data-decision="approve">允許一次</button><button class="soft-button inline-approval" data-id="${escapeHtml(approval.id)}" data-decision="reject">拒絕</button></div></div>`).join("") : `<div class="empty-list" style="padding:20px">沒有待核准動作</div>`;
  $$(".inline-approval").forEach((button) => button.addEventListener("click", async () => {
    await resolveApproval(button.dataset.id, button.dataset.decision);
    await refreshPermissionsData();
  }));
  renderAudit();
}

function renderAudit() {
  const audit = state.data.audit || [];
  $("#audit-list").innerHTML = audit.length ? audit.slice(0, 30).map((item) => `
    <div class="audit-row"><strong>${escapeHtml(item.action)}</strong><small>${formatTime(item.created_at, true)}</small><small>${escapeHtml(item.resource)}</small></div>`).join("") : `<div class="empty-list" style="padding:20px">按「重新整理」載入紀錄</div>`;
}

function permissionModeLabel(mode) {
  return { observe: "僅查看", workspace: "專案可寫入", full: "完整系統權限" }[mode] || mode;
}

function renderSelectedFileChips() {
  const paths = [...state.selectedFiles];
  $("#selected-files").innerHTML = paths.map((path) => `<span class="selected-file-chip" title="${escapeHtml(path)}"><svg viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6V3Z"/><path d="M14 3v5h5"/></svg><span>${escapeHtml(path.split(/[\\/]/).pop())}</span><button data-remove-file="${escapeHtml(path)}"><svg viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18"/></svg></button></span>`).join("");
  $$('[data-remove-file]').forEach((button) => button.addEventListener("click", () => {
    state.selectedFiles.delete(button.dataset.removeFile);
    renderSelectedFileChips();
  }));
  $("#selection-count").textContent = paths.length;
  $("#selection-count").classList.toggle("hidden", !paths.length);
}

function switchView(view) {
  state.currentView = view;
  $$('[data-view-panel]').forEach((panel) => panel.classList.toggle("active", panel.dataset.viewPanel === view));
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  if (view === "tasks") renderTasks();
  if (view === "permissions") refreshPermissionsData();
  if (view === "models") refreshModels();
  if (view === "images") refreshImages();
  if (view === "automations") refreshSchedules();
  document.body.classList.remove("mobile-nav-open");
}

async function createNewChat() {
  try {
    const conversation = await api("/api/conversations", { method: "POST", body: { project_id: state.projectId } });
    state.data.conversations.unshift(conversation);
    state.conversationId = conversation.id;
    state.conversation = conversation;
    state.messages = [];
    state.tasks = [];
    state.feasibility = null;
    localStorage.setItem("aihub.conversation", conversation.id);
    renderConversations();
    renderConversation();
    renderFeasibility();
    switchView("chat");
    $("#prompt-input").focus();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function sendPrompt(approvalId = null) {
  const input = $("#prompt-input");
  const prompt = input.value.trim();
  if (!prompt || !state.selectedProviders.length) return;
  const permission = $("#permission-select").value;
  if (permission === "full" && !state.data.settings.full_access_unlocked) {
    openFullAccessModal();
    return;
  }
  const body = {
    prompt,
    conversation_id: state.conversationId,
    project_id: state.projectId,
    provider_ids: state.selectedProviders,
    selected_files: [...state.selectedFiles],
    collaboration: $("#collaboration-toggle").getAttribute("aria-pressed") === "true",
    peer_review: $("#peer-review-toggle").checked,
    permission_mode: permission,
    web_access: state.data.settings.web_access,
    ...(approvalId ? { approval_id: approvalId } : {}),
  };
  $("#send-message").disabled = true;
  $("#composer-status").textContent = "正在建立工作…";
  try {
    const result = await api("/api/run", { method: "POST", body });
    state.feasibility = result.feasibility;
    input.value = "";
    resizeComposer();
    state.selectedFiles.clear();
    renderSelectedFileChips();
    await refreshTopLevelLists();
    await loadConversation();
    renderFeasibility();
  } catch (error) {
    if (error.status === 409 && error.data?.approval) {
      showApproval(error.data.approval, (id) => sendPrompt(id));
    } else {
      toast(error.message, "error", 6500);
    }
  } finally {
    $("#send-message").disabled = false;
    $("#composer-status").textContent = "Enter 送出 · Shift Enter 換行";
  }
}

function resizeComposer() {
  const input = $("#prompt-input");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 190)}px`;
}

function showApproval(approval, retry) {
  state.pendingApproval = approval;
  state.approvalRetry = retry;
  $("#approval-summary").textContent = approval.summary;
  $("#approval-payload").textContent = JSON.stringify(approval.payload || {}, null, 2);
  $("#approval-modal").showModal();
}

async function resolveApproval(id, decision) {
  return api(`/api/approvals/${encodeURIComponent(id)}/${decision}`, { method: "POST", body: {} });
}

async function approvePending() {
  if (!state.pendingApproval) return;
  const approval = state.pendingApproval;
  const retry = state.approvalRetry;
  try {
    await resolveApproval(approval.id, "approve");
    $("#approval-modal").close();
    state.pendingApproval = null;
    state.approvalRetry = null;
    if (retry) await retry(approval.id);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function rejectPending() {
  if (state.pendingApproval) {
    try { await resolveApproval(state.pendingApproval.id, "reject"); } catch (_) { /* best effort */ }
  }
  state.pendingApproval = null;
  state.approvalRetry = null;
  $("#approval-modal").close();
  toast("已拒絕這次動作");
}

async function refreshTopLevelLists() {
  const [conversations, approvals] = await Promise.all([api("/api/conversations"), api("/api/approvals")]);
  state.data.conversations = conversations;
  state.data.approvals = approvals;
  renderConversations();
  renderPermissions();
}

async function openFiles() {
  state.drawerFiles = new Set(state.selectedFiles);
  $("#file-drawer").classList.remove("hidden");
  $("#drawer-backdrop").classList.remove("hidden");
  await loadFiles();
}

function closeFiles() {
  $("#file-drawer").classList.add("hidden");
  $("#drawer-backdrop").classList.add("hidden");
  $("#file-preview").classList.add("hidden");
}

async function loadFiles(path = null) {
  const query = new URLSearchParams({ project_id: state.projectId });
  if (path) query.set("path", path);
  try {
    const data = await api(`/api/files?${query}`);
    state.filePath = data.path;
    state.fileParent = data.parent;
    $("#file-path").textContent = data.path;
    $("#file-up").disabled = !data.parent;
    $("#file-list").innerHTML = data.entries.length ? data.entries.map((entry) => {
      const selected = state.drawerFiles.has(entry.path);
      return `<div class="file-row ${selected ? "selected" : ""}" data-path="${escapeHtml(entry.path)}" data-dir="${entry.is_dir}">
        <input type="checkbox" ${selected ? "checked" : ""} aria-label="選取 ${escapeHtml(entry.name)}">
        <div class="file-name"><svg viewBox="0 0 24 24">${entry.is_dir ? '<path d="M3 6.5h7l2 2h9v10H3v-12Z"/>' : '<path d="M6 3h8l4 4v14H6V3Z"/><path d="M14 3v5h5"/>'}</svg><span>${escapeHtml(entry.name)}</span></div>
        <span class="file-date">${formatTime(entry.modified_at, true)}</span><span class="file-size">${entry.is_dir ? "—" : fileSize(entry.size)}</span>
      </div>`;
    }).join("") : `<div class="empty-list" style="margin:15px">空資料夾</div>`;
    $$(".file-row").forEach((row) => {
      const checkbox = $("input", row);
      checkbox.addEventListener("change", () => toggleDrawerFile(row.dataset.path, checkbox.checked));
      $(".file-name", row).addEventListener("dblclick", () => {
        if (row.dataset.dir === "true") loadFiles(row.dataset.path);
        else previewFile(row.dataset.path);
      });
      $(".file-name", row).addEventListener("click", () => {
        if (row.dataset.dir === "true") return;
        previewFile(row.dataset.path);
      });
    });
    updateDrawerSelectionLabel();
  } catch (error) {
    toast(error.message, "error");
  }
}

function toggleDrawerFile(path, selected) {
  if (selected) state.drawerFiles.add(path);
  else state.drawerFiles.delete(path);
  updateDrawerSelectionLabel();
  const row = $(`.file-row[data-path="${CSS.escape(path)}"]`);
  if (row) row.classList.toggle("selected", selected);
}

function updateDrawerSelectionLabel() {
  const count = state.drawerFiles.size;
  $("#drawer-selection-label").textContent = count ? `已選取 ${count} 個項目` : "尚未選取檔案";
}

async function previewFile(path) {
  try {
    const query = new URLSearchParams({ project_id: state.projectId, path });
    const data = await api(`/api/file?${query}`);
    $("#preview-name").textContent = path.split(/[\\/]/).pop();
    $("#preview-content").textContent = data.binary ? `二進位檔案 · ${fileSize(data.size)}，無法文字預覽。` : data.content;
    $("#file-preview").classList.remove("hidden");
  } catch (error) {
    toast(error.message, "error");
  }
}

function useSelectedFiles() {
  state.selectedFiles = new Set(state.drawerFiles);
  renderSelectedFileChips();
  closeFiles();
  $("#prompt-input").focus();
}

function bytesToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunks = [];
  for (let index = 0; index < bytes.length; index += 0x8000) {
    chunks.push(String.fromCharCode(...bytes.subarray(index, index + 0x8000)));
  }
  return btoa(chunks.join(""));
}

async function importFiles(files, index = 0, approvalId = null) {
  if (index >= files.length) {
    $("#file-import-input").value = "";
    await loadFiles(state.filePath);
    toast(`已匯入 ${files.length} 個檔案`);
    return;
  }
  const file = files[index];
  if (file.size > 10_000_000) {
    toast(`${file.name} 超過 10 MB 匯入上限`, "error", 6000);
    return importFiles(files, index + 1);
  }
  const separator = state.filePath.includes("\\") ? "\\" : "/";
  const safeName = file.name.split(/[\\/]/).pop();
  const target = `${state.filePath.replace(/[\\/]$/, "")}${separator}${safeName}`;
  try {
    await api("/api/files/import", { method: "POST", body: {
      project_id: state.projectId,
      path: target,
      permission_mode: $("#permission-select").value,
      base64: bytesToBase64(await file.arrayBuffer()),
      ...(approvalId ? { approval_id: approvalId } : {}),
    }});
    await importFiles(files, index + 1);
  } catch (error) {
    if (error.status === 409 && error.data?.approval) {
      showApproval(error.data.approval, (id) => importFiles(files, index, id));
    } else {
      toast(`${file.name}：${error.message}`, "error", 6000);
    }
  }
}

async function openTaskModal(taskId) {
  state.taskModalId = taskId;
  state.taskEventCursor = 0;
  $("#event-stream").innerHTML = "";
  $("#task-modal").showModal();
  await refreshTaskModal();
}

async function refreshTaskModal() {
  const task = state.tasks.find((item) => item.id === state.taskModalId) || state.data.tasks?.find((item) => item.id === state.taskModalId);
  if (!task) return;
  const provider = findProvider(task.provider_id);
  const progress = taskDisplayProgress(task);
  $("#task-modal-provider").textContent = `${provider.label} · ${task.status}`;
  $("#task-modal-title").textContent = task.title;
  $("#task-modal-stage").textContent = task.stage;
  $("#task-modal-percent").textContent = progressLabel(progress);
  $("#task-modal-bar").style.width = `${progress ?? 0}%`;
  renderTaskOperatorDetails(task);
  $("#cancel-task").classList.toggle("hidden", !["queued", "running", "cancelling"].includes(task.status));
  try {
    const events = await api(`/api/tasks/${encodeURIComponent(task.id)}/events?after=${state.taskEventCursor}`);
    if (events.length) {
      const stream = $("#event-stream");
      for (const event of events) {
        state.taskEventCursor = Math.max(state.taskEventCursor, event.id);
        const row = document.createElement("div");
        row.className = `event-row ${event.level}`;
        row.innerHTML = `<time>${formatTime(event.created_at)}</time><span class="event-level">${escapeHtml(event.level)}</span><span class="event-message">${escapeHtml(event.message)}</span>`;
        stream.append(row);
      }
      stream.scrollTop = stream.scrollHeight;
    }
  } catch (_) { /* task may have just disappeared */ }
}

async function cancelCurrentTask() {
  if (!state.taskModalId) return;
  try {
    await api(`/api/tasks/${encodeURIComponent(state.taskModalId)}/cancel`, { method: "POST", body: {} });
    toast("已送出停止訊號");
  } catch (error) {
    toast(error.message, "error");
  }
}

function openTerminal(prefill = "") {
  $("#terminal-drawer").classList.remove("hidden");
  if (prefill) $("#terminal-input").value = prefill;
  $("#terminal-input").focus();
}

async function runTerminal(approvalId = null) {
  const input = $("#terminal-input");
  const command = input.value.trim();
  if (!command) return;
  const mode = $("#permission-select").value;
  if (mode === "full" && !state.data.settings.full_access_unlocked) {
    openFullAccessModal();
    return;
  }
  const body = {
    command,
    project_id: state.projectId,
    conversation_id: state.conversationId,
    permission_mode: mode,
    ...(approvalId ? { approval_id: approvalId } : {}),
  };
  try {
    const result = await api("/api/terminal", { method: "POST", body });
    appendTerminal(`PS> ${command}`, "command");
    input.value = "";
    state.terminalTaskIds.add(result.task.id);
    state.terminalEventCursor.set(result.task.id, 0);
    await loadConversation(false);
  } catch (error) {
    if (error.status === 409 && error.data?.approval) {
      showApproval(error.data.approval, (id) => runTerminal(id));
    } else {
      appendTerminal(error.message, "error");
      toast(error.message, "error");
    }
  }
}

function appendTerminal(text, className = "") {
  const line = document.createElement("div");
  line.className = `terminal-line ${className}`;
  line.textContent = text;
  $("#terminal-output").append(line);
  $("#terminal-output").scrollTop = $("#terminal-output").scrollHeight;
}

async function refreshTerminalEvents() {
  for (const taskId of [...state.terminalTaskIds]) {
    const after = state.terminalEventCursor.get(taskId) || 0;
    try {
      const events = await api(`/api/tasks/${encodeURIComponent(taskId)}/events?after=${after}`);
      for (const event of events) {
        state.terminalEventCursor.set(taskId, event.id);
        if (!["debug"].includes(event.level)) appendTerminal(event.message, event.level === "error" ? "error" : "");
      }
      const task = state.tasks.find((item) => item.id === taskId);
      if (task && ["completed", "failed", "cancelled"].includes(task.status)) {
        state.terminalTaskIds.delete(taskId);
        appendTerminal(task.status === "completed" ? "[完成]" : `[${task.status}] ${task.error || ""}`, task.status === "completed" ? "" : "error");
      }
    } catch (_) { /* poll again */ }
  }
}

async function pullModel(modelId, approvalId = null) {
  const model = state.data.models.find((item) => item.id === modelId);
  if (!model) return;
  if (!approvalId && !confirm(`下載 ${model.label}？\n預估使用 ${model.disk_gb} GB 磁碟空間。`)) return;
  try {
    const result = await api("/api/models/pull", { method: "POST", body: {
      model_id: modelId, project_id: state.projectId, conversation_id: state.conversationId,
      permission_mode: $("#permission-select").value, ...(approvalId ? { approval_id: approvalId } : {}),
    }});
    const task = result.task || result;
    state.tasks.unshift(task);
    toast("模型下載已開始，可在執行進度查看");
    switchView("tasks");
  } catch (error) {
    if (error.status === 409 && error.data?.approval) showApproval(error.data.approval, (id) => pullModel(modelId, id));
    else toast(error.message, "error", 6000);
  }
}


async function refreshModels() {
  try {
    const data = await api("/api/models");
    state.data.models = data.catalog;
    state.data.model_readiness = data.readiness;
    renderModels();
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderIntegrations() {
  const integrations = state.data.integrations || {};
  const systemPolicy = state.data.system?.resource_policy || state.data.resource_policy || {};
  const cards = [
    ["Google Play", integrations.google_play?.token_present ? "OAuth token ready" : "需要 GOOGLE_PLAY_ACCESS_TOKEN", integrations.google_play?.token_present],
    ["Google Sites", "Modern Sites · browser-assisted", true],
    ["官方模型同步", integrations.model_sync?.metadata_present ? "Metadata 已同步" : "尚未同步", integrations.model_sync?.metadata_present],
    ["本機控制面", "Loopback + Session + Same-Origin", true],
  ];
  const grid = $("#integration-status-grid");
  if (grid) grid.innerHTML = cards.map(([name, detail, ready]) => `<article class="integration-status-card"><span class="integration-light ${ready ? "ready" : "setup"}"></span><div><strong>${escapeHtml(name)}</strong><small>${escapeHtml(detail)}</small></div></article>`).join("");
  const policy = $("#resource-policy");
  if (policy) {
    const reasons = systemPolicy.reasons || ["資源狀態等待更新"];
    policy.innerHTML = `<div><span>允許並行</span><strong>${systemPolicy.max_parallel_agents ?? "—"}</strong></div><div><span>大型本機模型</span><strong>${systemPolicy.admit_large_local_model === false ? "暫停" : "可評估"}</strong></div><div><span>遠端優先</span><strong>${systemPolicy.prefer_remote_model ? "YES" : "NO"}</strong></div><p>${reasons.map(escapeHtml).join(" · ")}</p>`;
  }
}

function renderTaskOperatorDetails(task) {
  const target = $("#task-operator-details");
  if (!target) return;
  const meta = task.metadata || {};
  const checkpoint = meta.checkpoint || {};
  const plan = meta.plan || checkpoint.plan;
  const reviews = meta.reviews || checkpoint.reviews || [];
  const selected = meta.selected_files || meta.resume_payload?.selected_files || [];
  const rows = [];
  if (meta.retry_of || meta.recovered_after_crash) rows.push(`<span>Recovery<strong>${escapeHtml(meta.retry_of ? `retry ${meta.retry_of.slice(-8)}` : "crash resume")}</strong></span>`);
  if (selected.length) rows.push(`<span>Write scope<strong>${selected.length} selected item(s)</strong></span>`);
  if (plan?.steps?.length) rows.push(`<span>DAG<strong>${plan.steps.length} step(s)</strong></span>`);
  if (reviews.length) rows.push(`<span>Quality gate<strong>${escapeHtml(reviews.at(-1)?.verdict || "pending")}</strong></span>`);
  if (meta.acceptance_passed != null) rows.push(`<span>Acceptance<strong>${meta.acceptance_passed ? "PASS" : "FAIL"}</strong></span>`);
  target.innerHTML = rows.length ? `<div class="operator-detail-grid">${rows.join("")}</div>${plan?.summary ? `<p>${escapeHtml(plan.summary)}</p>` : ""}` : "";
  target.classList.toggle("hidden", !rows.length);
}

async function syncOfficialModels() {
  try {
    const result = await api("/api/models/sync", { method: "POST", body: { project_id: state.projectId, conversation_id: state.conversationId } });
    const task = result.task || result;
    state.modelSyncTaskId = task.id;
    state.tasks.unshift(task);
    toast("官方模型 metadata 同步已開始");
    switchView("tasks");
  } catch (error) { toast(error.message, "error", 6000); }
}

async function publishPlay(approvalId = null) {
  const artifact = $("#play-artifact").value.trim();
  const packageName = $("#play-package").value.trim();
  if (!artifact || !packageName) { toast("請填寫 Package name 與 APK/AAB 本機路徑", "error"); return; }
  try {
    const result = await api("/api/integrations/play", { method: "POST", body: {
      project_id: state.projectId, conversation_id: state.conversationId,
      permission_mode: $("#permission-select").value, package: packageName, artifact,
      track: $("#play-track").value, status: $("#play-status").value,
      commit: $("#play-commit").checked, ...(approvalId ? { approval_id: approvalId } : {}),
    }});
    const task = result.task || result; state.tasks.unshift(task);
    toast($("#play-commit").checked ? "Google Play COMMIT 工作已開始" : "Google Play 驗證工作已開始"); switchView("tasks");
  } catch (error) {
    if (error.status === 409 && error.data?.approval) showApproval(error.data.approval, (id) => publishPlay(id));
    else toast(error.message, "error", 7000);
  }
}

async function openSitesSession(approvalId = null) {
  const title = $("#sites-title").value.trim();
  if (!title) { toast("請輸入 Google Sites 標題", "error"); return; }
  try {
    const result = await api("/api/integrations/sites", { method: "POST", body: {
      project_id: state.projectId, conversation_id: state.conversationId, title,
      profile: $("#sites-profile").value.trim() || null,
      template_url: $("#sites-template").value.trim() || null,
      ...(approvalId ? { approval_id: approvalId } : {}),
    }});
    const task = result.task || result; state.tasks.unshift(task); toast("Google Sites 工作階段已開始"); switchView("tasks");
  } catch (error) {
    if (error.status === 409 && error.data?.approval) showApproval(error.data.approval, (id) => openSitesSession(id));
    else toast(error.message, "error", 7000);
  }
}

async function runMaintenanceNow() {
  try {
    const result = await api("/api/maintenance/run", { method: "POST", body: { permission_mode: $("#permission-select").value } });
    toast(`維護完成 · backup ${result.backup || "ok"}`, "normal", 6000);
  } catch (error) { toast(error.message, "error", 6000); }
}

async function refreshSchedules() {
  try {
    state.data.schedules = await api("/api/schedules");
    renderSchedules();
  } catch (error) { toast(error.message, "error"); }
}

async function updateSchedule(id, action) {
  if (action === "delete" && !confirm("刪除這個排程？")) return;
  try {
    await api(`/api/schedules/${encodeURIComponent(id)}/${action}`, { method: "POST", body: {} });
    await refreshSchedules();
  } catch (error) { toast(error.message, "error"); }
}

async function saveSchedule(event) {
  event.preventDefault();
  if (!$("#schedule-name").value.trim() || !$("#schedule-prompt").value.trim()) return;
  try {
    await api("/api/schedules", { method: "POST", body: {
      name: $("#schedule-name").value.trim(),
      prompt: $("#schedule-prompt").value.trim(),
      project_id: state.projectId,
      provider_ids: state.selectedProviders,
      start_time: $("#schedule-start").value,
      end_time: $("#schedule-end").value,
      duration_minutes: Number($("#schedule-duration").value),
      interval_minutes: Number($("#schedule-interval").value),
      weekdays: [0, 1, 2, 3, 4, 5, 6],
      mode: $("#schedule-mode").value,
      enabled: true,
    }});
    $("#schedule-modal").close();
    toast("排程已建立");
    await refreshSchedules();
  } catch (error) { toast(error.message, "error"); }
}

async function fetchResearch() {
  const input = $("#research-url");
  const url = input.value.trim();
  if (!url) return;
  $("#fetch-research").disabled = true;
  try {
    const document = await api("/api/research/fetch", { method: "POST", body: { url } });
    state.data.research.unshift({ ...document, excerpt: document.text?.slice(0, 500) });
    input.value = "";
    renderResearch();
    toast(`已索引：${document.title}`);
  } catch (error) { toast(error.message, "error", 6000); }
  finally { $("#fetch-research").disabled = false; }
}

async function refreshPermissionsData() {
  try {
    const [approvals, audit] = await Promise.all([api("/api/approvals"), api("/api/audit")]);
    state.data.approvals = approvals;
    state.data.audit = audit;
    renderPermissions();
  } catch (error) { toast(error.message, "error"); }
}

function openFullAccessModal() {
  if (state.data.settings.full_access_unlocked) {
    lockFullAccess();
    return;
  }
  $("#full-access-phrase").value = "";
  $("#confirm-full-access").disabled = true;
  $("#full-access-modal").showModal();
  $("#full-access-phrase").focus();
}

async function unlockFullAccess() {
  try {
    const settings = await api("/api/full-access/unlock", { method: "POST", body: { phrase: $("#full-access-phrase").value, minutes: 30 } });
    state.data.settings = settings;
    $("#permission-select").value = "full";
    $("#full-access-modal").close();
    renderPermissions();
    toast("完整系統權限已解鎖 30 分鐘");
  } catch (error) { toast(error.message, "error"); }
}

async function lockFullAccess() {
  try {
    state.data.settings = await api("/api/full-access/lock", { method: "POST", body: {} });
    if ($("#permission-select").value === "full") $("#permission-select").value = "workspace";
    renderPermissions();
    toast("完整系統權限已鎖定");
  } catch (error) { toast(error.message, "error"); }
}

function fillSettingsForm() {
  const settings = state.data.settings;
  const compatible = settings.provider_config?.compatible || {};
  const comfyui = settings.provider_config?.comfyui || {};
  $("#compatible-base-url").value = compatible.base_url || "";
  $("#compatible-model").value = compatible.model || "";
  $("#compatible-key-env").value = compatible.api_key_env || "AI_HUB_API_KEY";
  $("#comfyui-base-url").value = comfyui.base_url || "http://127.0.0.1:8188";
  $("#comfyui-checkpoint").value = comfyui.checkpoint || "";
  $("#setting-web").checked = Boolean(settings.web_access);
  $("#setting-peer-review").checked = Boolean(settings.auto_peer_review);
  $("#setting-parallel").value = settings.max_parallel_agents || 3;
  $("#setting-performance").checked = Boolean(settings.adaptive_performance);
  $("#setting-memory-threshold").value = settings.performance_memory_threshold || 90;
  $("#permission-select").value = settings.permission_mode || "workspace";
  $("#peer-review-toggle").checked = Boolean(settings.auto_peer_review);
}

async function saveSettings() {
  try {
    state.data.settings = await api("/api/settings", { method: "POST", body: {
      web_access: $("#setting-web").checked,
      auto_peer_review: $("#setting-peer-review").checked,
      max_parallel_agents: Number($("#setting-parallel").value),
      adaptive_performance: $("#setting-performance").checked,
      performance_memory_threshold: Number($("#setting-memory-threshold").value),
      permission_mode: $("#permission-select").value,
      provider_config: {
        compatible: { base_url: $("#compatible-base-url").value.trim(), model: $("#compatible-model").value.trim(), api_key_env: $("#compatible-key-env").value.trim() },
        comfyui: { base_url: $("#comfyui-base-url").value.trim(), checkpoint: $("#comfyui-checkpoint").value.trim() },
      },
    }});
    toast("設定已儲存");
    state.data.providers = await api("/api/providers");
    chooseValidProviders();
    renderAll();
  } catch (error) { toast(error.message, "error"); }
}

function updateScheduleMode() {
  const imageMode = $("#schedule-mode").value === "image";
  $("#schedule-provider-section").classList.toggle("hidden", imageMode);
  $("#schedule-name").placeholder = imageMode ? "夜間插畫生成" : "每日程式品質改善";
  $("#schedule-prompt").placeholder = imageMode
    ? "描述每輪要生成的畫面；每次排程會建立一張圖片。"
    : "檢查效能、可維護性與測試缺口，每次只完成一個小範圍改善。";
}

async function addProjectFromModal(event) {
  event.preventDefault();
  try {
    const project = await api("/api/projects", { method: "POST", body: { path: $("#project-path").value.trim(), name: $("#project-name").value.trim() || null } });
    if (!state.data.projects.some((item) => item.id === project.id)) state.data.projects.unshift(project);
    state.projectId = project.id;
    localStorage.setItem("aihub.project", project.id);
    $("#project-modal").close();
    renderProjects();
    await createNewChat();
  } catch (error) { toast(error.message, "error"); }
}

async function nativeFolderPicker() {
  $("#native-folder-picker").disabled = true;
  try {
    const result = await api("/api/dialog/folder", { method: "POST", body: {} });
    if (result.path) $("#project-path").value = result.path;
  } catch (error) { toast(error.message, "error"); }
  finally { $("#native-folder-picker").disabled = false; }
}

async function handleProjectChange() {
  state.projectId = $("#project-select").value;
  localStorage.setItem("aihub.project", state.projectId);
  state.filePath = null;
  state.selectedFiles.clear();
  const matching = state.data.conversations.find((item) => item.project_id === state.projectId);
  if (matching) {
    state.conversationId = matching.id;
    localStorage.setItem("aihub.conversation", matching.id);
    await loadConversation();
  } else {
    await createNewChat();
  }
  renderAll();
}

async function refreshEverything() {
  try {
    state.data = await api("/api/bootstrap");
    chooseValidProjectAndChat();
    chooseValidProviders();
    await loadConversation(false);
    renderAll();
  } catch (error) { toast(error.message, "error"); }
}

function bindEvents() {
  $$(".nav-item, .profile-row").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  $("#new-chat").addEventListener("click", createNewChat);
  $("#refresh-chats").addEventListener("click", refreshEverything);
  $("#project-select").addEventListener("change", handleProjectChange);
  $("#add-project").addEventListener("click", () => $("#project-modal").showModal());
  $("#project-form").addEventListener("submit", addProjectFromModal);
  $("#cancel-project").addEventListener("click", () => $("#project-modal").close());
  $("#native-folder-picker").addEventListener("click", nativeFolderPicker);
  $("#provider-picker").addEventListener("click", (event) => {
    event.stopPropagation();
    $("#provider-menu").classList.toggle("hidden");
  });
  document.addEventListener("click", (event) => {
    if (!$("#provider-menu").contains(event.target) && !$("#provider-picker").contains(event.target)) $("#provider-menu").classList.add("hidden");
  });
  $("#collaboration-toggle").addEventListener("click", () => {
    const value = $("#collaboration-toggle").getAttribute("aria-pressed") !== "true";
    $("#collaboration-toggle").setAttribute("aria-pressed", String(value));
  });
  $("#prompt-input").addEventListener("input", resizeComposer);
  $("#prompt-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      sendPrompt();
    }
    if (event.key === "@" && !event.ctrlKey) setTimeout(openFiles, 0);
  });
  $("#send-message").addEventListener("click", () => sendPrompt());
  $$(".starter").forEach((button) => button.addEventListener("click", () => {
    $("#prompt-input").value = button.dataset.prompt;
    if (button.dataset.collaboration) $("#collaboration-toggle").setAttribute("aria-pressed", "true");
    resizeComposer();
    $("#prompt-input").focus();
  }));
  $("#open-files").addEventListener("click", openFiles);
  $("#attach-file").addEventListener("click", openFiles);
  $("#close-files").addEventListener("click", closeFiles);
  $("#drawer-backdrop").addEventListener("click", closeFiles);
  $("#file-up").addEventListener("click", () => state.fileParent && loadFiles(state.fileParent));
  $("#file-refresh").addEventListener("click", () => loadFiles(state.filePath));
  $("#file-open-explorer").addEventListener("click", async () => {
    try { await api("/api/open-path", { method: "POST", body: { project_id: state.projectId, path: state.filePath } }); }
    catch (error) { toast(error.message, "error"); }
  });
  $("#file-import").addEventListener("click", () => $("#file-import-input").click());
  $("#file-import-input").addEventListener("change", (event) => importFiles([...event.target.files]));
  $("#close-preview").addEventListener("click", () => $("#file-preview").classList.add("hidden"));
  $("#use-selected-files").addEventListener("click", useSelectedFiles);
  $("#open-terminal").addEventListener("click", () => openTerminal());
  $("#close-terminal").addEventListener("click", () => $("#terminal-drawer").classList.add("hidden"));
  $("#terminal-form").addEventListener("submit", (event) => { event.preventDefault(); runTerminal(); });
  $("#approve-action").addEventListener("click", approvePending);
  $("#reject-approval").addEventListener("click", rejectPending);
  $("#done-task-modal").addEventListener("click", () => { state.taskModalId = null; $("#task-modal").close(); });
  $("#close-task-modal").addEventListener("click", () => { state.taskModalId = null; $("#task-modal").close(); });
  $("#cancel-task").addEventListener("click", cancelCurrentTask);
  $("#refresh-tasks").addEventListener("click", () => loadConversation(false));
  $("#team-open-chat").addEventListener("click", () => { $("#collaboration-toggle").setAttribute("aria-pressed", "true"); switchView("chat"); $("#prompt-input").focus(); });
  $("#team-edit-providers").addEventListener("click", () => { switchView("chat"); $("#provider-menu").classList.remove("hidden"); });
  $("#inspector-edit-ai").addEventListener("click", () => $("#provider-menu").classList.remove("hidden"));
  $("#install-clis").addEventListener("click", () => {
    const root = state.data.app_root || ".";
    openTerminal(`& '${root.replaceAll("'", "''")}\\setup.ps1' -InstallCli`);
    toast("已填入安裝命令；確認後按執行");
  });
  $("#refresh-integrations").addEventListener("click", refreshEverything);
  $("#sync-official-models").addEventListener("click", syncOfficialModels);
  $("#run-maintenance").addEventListener("click", runMaintenanceNow);
  $("#publish-play").addEventListener("click", () => publishPlay());
  $("#open-sites-session").addEventListener("click", () => openSitesSession());
  $("#play-use-selected").addEventListener("click", () => {
    const candidate = [...state.selectedFiles].find((path) => /\.(apk|aab)$/i.test(path));
    if (!candidate) toast("目前選取範圍沒有 APK/AAB", "error");
    else $("#play-artifact").value = candidate;
  });
  $("#refresh-images").addEventListener("click", refreshImages);
  $("#generate-image").addEventListener("click", generateImage);
  $("#image-settings-link").addEventListener("click", () => { switchView("settings"); $("#comfyui-base-url").focus(); });
  $("#new-schedule").addEventListener("click", () => { renderTeam(); updateScheduleMode(); $("#schedule-modal").showModal(); });
  $("#schedule-form").addEventListener("submit", saveSchedule);
  $("#cancel-schedule").addEventListener("click", () => $("#schedule-modal").close());
  $("#schedule-mode").addEventListener("change", updateScheduleMode);
  $("#startup-help").addEventListener("click", () => {
    openTerminal(`& '${state.data.app_root.replaceAll("'", "''")}\\install-startup.ps1'`);
    toast("已填入 Windows 登入啟動安裝命令");
  });
  $("#fetch-research").addEventListener("click", fetchResearch);
  $("#research-url").addEventListener("keydown", (event) => { if (event.key === "Enter") fetchResearch(); });
  $("#crawler-enabled").addEventListener("change", async (event) => {
    try {
      state.data.settings = await api("/api/settings", { method: "POST", body: { crawler_enabled: event.target.checked } });
      toast(event.target.checked ? "對話網址自動擷取已啟用" : "對話網址自動擷取已停用");
    } catch (error) {
      event.target.checked = !event.target.checked;
      toast(error.message, "error");
    }
  });
  $("#unlock-full-access").addEventListener("click", openFullAccessModal);
  $("#cancel-full-access").addEventListener("click", () => $("#full-access-modal").close());
  $("#full-access-phrase").addEventListener("input", () => { $("#confirm-full-access").disabled = $("#full-access-phrase").value.trim() !== "我同意完整系統權限"; });
  $("#confirm-full-access").addEventListener("click", unlockFullAccess);
  $$(".permission-use").forEach((button) => button.addEventListener("click", async () => {
    state.data.settings = await api("/api/settings", { method: "POST", body: { permission_mode: button.dataset.mode } });
    $("#permission-select").value = button.dataset.mode;
    renderPermissions();
    toast(`預設權限已改為${permissionModeLabel(button.dataset.mode)}`);
  }));
  $("#refresh-audit").addEventListener("click", refreshPermissionsData);
  $("#save-settings").addEventListener("click", saveSettings);
  $("#export-conversation").addEventListener("click", () => {
    if (!state.conversationId) return;
    const anchor = document.createElement("a");
    anchor.href = `/api/conversations/${encodeURIComponent(state.conversationId)}/export`;
    anchor.download = "";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
  });
  $("#sidebar-collapse").addEventListener("click", () => document.body.classList.toggle("sidebar-mini"));
  $("#collapse-inspector").addEventListener("click", () => document.body.classList.toggle("inspector-hidden"));
  $("#mobile-menu").addEventListener("click", () => document.body.classList.toggle("mobile-nav-open"));
  $("#more-menu").addEventListener("click", async () => {
    if (!state.conversationId || !confirm("封存目前對話？之後仍保留在本機資料庫。")) return;
    try {
      await api(`/api/conversations/${encodeURIComponent(state.conversationId)}`, { method: "PATCH", body: { archived: true } });
      await refreshEverything();
    } catch (error) { toast(error.message, "error"); }
  });
  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.key.toLowerCase() === "n") { event.preventDefault(); createNewChat(); }
    if (event.key === "Escape") {
      $("#provider-menu").classList.add("hidden");
      if (!$("#file-drawer").classList.contains("hidden")) closeFiles();
    }
  });
}

initialize();
