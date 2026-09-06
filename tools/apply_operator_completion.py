from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.rstrip() + "\n", encoding="utf-8")


def patch(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"anchor missing: {path}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


# ----------------------------- Web Operator UI -----------------------------
index = read("web/index.html")
nav_anchor = '''        <button class="nav-item" data-view="permissions">\n'''
nav = '''        <button class="nav-item" data-view="integrations">\n          <svg viewBox="0 0 24 24"><path d="M8 7h8M8 17h8M5 4v6M19 14v6M5 14v6M19 4v6"/><circle cx="5" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>\n          <span>整合與發布</span>\n        </button>\n'''
if nav not in index:
    if nav_anchor not in index: raise RuntimeError("web navigation anchor missing")
    index = index.replace(nav_anchor, nav + nav_anchor, 1)

view_anchor = '''          <div class="view page-view" id="view-permissions" data-view-panel="permissions">\n'''
integration_view = '''          <div class="view page-view" id="view-integrations" data-view-panel="integrations">\n            <div class="page-header"><div><span class="eyebrow">OPERATOR INTEGRATIONS</span><h1>整合、發布與資源治理</h1><p>正式後端能力直接進入 Task / Approval / Audit，不再只是獨立腳本。</p></div><button class="soft-button" id="refresh-integrations">重新整理狀態</button></div>\n            <div class="integration-status-grid" id="integration-status-grid"></div>\n            <article class="panel resource-policy-panel"><div class="panel-heading"><h2>Resource Governor</h2><span class="status-pill green">LIVE</span></div><div id="resource-policy" class="operator-policy"></div></article>\n            <div class="section-grid two operator-integrations">\n              <article class="panel"><div class="panel-heading"><h2>官方模型生命週期</h2><span class="status-pill">Kimi / DeepSeek ≤50B</span></div><p>同步官方 Hugging Face metadata，將 latest / largest eligible 直接合併到主模型目錄。</p><button class="primary-button wide" id="sync-official-models">同步官方模型目錄</button></article>\n              <article class="panel"><div class="panel-heading"><h2>本機資料維護</h2><span class="status-pill green">AUDITED</span></div><p>立即執行 SQLite backup、retention、research 去重、FTS 重建與圖片 quota 清理。</p><button class="soft-button wide" id="run-maintenance">立即維護</button></article>\n              <article class="panel integration-form-card"><div class="panel-heading"><h2>Google Play</h2><span class="status-pill warning">ACCOUNT APPROVAL</span></div><label>Package name<input id="play-package" placeholder="com.example.app"></label><label>APK / AAB 本機路徑<div class="input-with-button"><input id="play-artifact" placeholder="C:\\build\\app-release.aab"><button id="play-use-selected" type="button">用選取檔案</button></div></label><div class="form-grid"><label>Track<select id="play-track"><option>internal</option><option>alpha</option><option>beta</option><option>production</option></select></label><label>Status<select id="play-status"><option>draft</option><option>inProgress</option><option>halted</option><option>completed</option></select></label></div><label class="switch-row"><span><strong>正式 Commit</strong><small>關閉時只 upload + validate，不提交 edit。</small></span><input type="checkbox" id="play-commit"><i></i></label><button class="danger-button wide" id="publish-play">執行 Play 流程</button></article>\n              <article class="panel integration-form-card"><div class="panel-heading"><h2>Google Sites</h2><span class="status-pill">BROWSER ASSISTED</span></div><label>網站標題<input id="sites-title" placeholder="專案網站"></label><label>Chrome / Edge Profile（選填）<input id="sites-profile" placeholder="Default"></label><label>Template URL（選填）<input id="sites-template" type="url" placeholder="https://sites.new"></label><p class="form-note">Modern Google Sites 沒有受支援的一般寫入 API；AI Hub 會開啟經一次性核准的帳號工作階段，不偽造不存在的 API。</p><button class="primary-button wide" id="open-sites-session">開啟 Sites 工作階段</button></article>\n            </div>\n          </div>\n\n'''
if integration_view not in index:
    if view_anchor not in index: raise RuntimeError("permissions view anchor missing")
    index = index.replace(view_anchor, integration_view + view_anchor, 1)

modal_anchor = '<div class="event-stream" id="event-stream"></div>'
modal_new = '<div class="operator-task-details" id="task-operator-details"></div><div class="event-stream" id="event-stream"></div>'
if modal_new not in index:
    if modal_anchor not in index: raise RuntimeError("task modal anchor missing")
    index = index.replace(modal_anchor, modal_new, 1)
write("web/index.html", index)

app = read("web/app.js")
app = app.replace('  imageStatus: null,\n};', '  imageStatus: null,\n  modelSyncTaskId: null,\n};', 1) if 'modelSyncTaskId:' not in app else app
app = app.replace(
'''function taskDisplayProgress(task) {\n  const actual = Number(task.progress || 0);\n  if (task.status === "completed") return 100;\n  return Math.max(0, Math.min(100, actual));\n}\n''',
'''function taskDisplayProgress(task) {\n  if (task.status === "completed") return 100;\n  const actual = Number(task.progress || 0);\n  return actual > 1 ? Math.max(0, Math.min(99, actual)) : null;\n}\n\nfunction progressLabel(progress) {\n  return progress == null ? "進度依事件" : `${Math.round(progress)}%`;\n}\n''', 1)
app = app.replace('  renderResearch();\n  renderPermissions();', '  renderResearch();\n  renderIntegrations();\n  renderPermissions();', 1)
app = app.replace('    renderSystem();\n    renderLiveTasks();', '    renderSystem();\n    if (state.currentView === "integrations") renderIntegrations();\n    if (state.modelSyncTaskId) {\n      const syncTask = state.tasks.find((item) => item.id === state.modelSyncTaskId);\n      if (syncTask && ["completed", "failed", "cancelled"].includes(syncTask.status)) {\n        state.modelSyncTaskId = null;\n        if (syncTask.status === "completed") refreshModels();\n      }\n    }\n    renderLiveTasks();', 1)
app = app.replace('''      <div class="live-task-head"><i class="task-spinner"></i><strong>${escapeHtml(task.title)}</strong><span>${escapeHtml(task.stage)} · ${Math.round(progress)}%</span></div>\n      <div class="thin-progress"><i style="width:${progress}%"></i></div>\n''', '''      <div class="live-task-head"><i class="task-spinner"></i><strong>${escapeHtml(task.title)}</strong><span>${escapeHtml(task.stage)} · ${progressLabel(progress)}</span></div>\n      <div class="thin-progress"><i style="width:${progress ?? 0}%"></i></div>\n''', 1)
app = app.replace('    $("#run-progress").style.width = `${progress}%`;', '    $("#run-progress").style.width = `${progress ?? 0}%`;', 1)
app = app.replace('''      <div class="task-progress-cell"><div class="thin-progress"><i style="width:${progress}%"></i></div><strong>${Math.round(progress)}%</strong></div>\n''', '''      <div class="task-progress-cell"><div class="thin-progress"><i style="width:${progress ?? 0}%"></i></div><strong>${progressLabel(progress)}</strong></div>\n''', 1)
app = app.replace('''  $("#task-modal-percent").textContent = `${Math.round(progress)}%`;\n  $("#task-modal-bar").style.width = `${progress}%`;\n''', '''  $("#task-modal-percent").textContent = progressLabel(progress);\n  $("#task-modal-bar").style.width = `${progress ?? 0}%`;\n  renderTaskOperatorDetails(task);\n''', 1)

old_pull_start = 'async function pullModel(modelId) {'
old_pull_end = '\n\nasync function refreshModels() {'
if old_pull_start in app:
    start = app.index(old_pull_start)
    end = app.index(old_pull_end, start)
    replacement = '''async function pullModel(modelId, approvalId = null) {\n  const model = state.data.models.find((item) => item.id === modelId);\n  if (!model) return;\n  if (!approvalId && !confirm(`下載 ${model.label}？\\n預估使用 ${model.disk_gb} GB 磁碟空間。`)) return;\n  try {\n    const result = await api("/api/models/pull", { method: "POST", body: {\n      model_id: modelId, project_id: state.projectId, conversation_id: state.conversationId,\n      permission_mode: $("#permission-select").value, ...(approvalId ? { approval_id: approvalId } : {}),\n    }});\n    const task = result.task || result;\n    state.tasks.unshift(task);\n    toast("模型下載已開始，可在執行進度查看");\n    switchView("tasks");\n  } catch (error) {\n    if (error.status === 409 && error.data?.approval) showApproval(error.data.approval, (id) => pullModel(modelId, id));\n    else toast(error.message, "error", 6000);\n  }\n}\n'''
    app = app[:start] + replacement + app[end:]

integrations_code = r'''
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
'''
if 'function renderIntegrations() {' not in app:
    anchor = '\nasync function refreshSchedules() {'
    if anchor not in app: raise RuntimeError("web integration function anchor missing")
    app = app.replace(anchor, '\n' + integrations_code.strip() + '\n' + anchor, 1)

bind_anchor = '  $("#refresh-images").addEventListener("click", refreshImages);\n'
bind_code = '''  $("#refresh-integrations").addEventListener("click", refreshEverything);\n  $("#sync-official-models").addEventListener("click", syncOfficialModels);\n  $("#run-maintenance").addEventListener("click", runMaintenanceNow);\n  $("#publish-play").addEventListener("click", () => publishPlay());\n  $("#open-sites-session").addEventListener("click", () => openSitesSession());\n  $("#play-use-selected").addEventListener("click", () => {\n    const candidate = [...state.selectedFiles].find((path) => /\\.(apk|aab)$/i.test(path));\n    if (!candidate) toast("目前選取範圍沒有 APK/AAB", "error");\n    else $("#play-artifact").value = candidate;\n  });\n'''
if bind_code not in app:
    if bind_anchor not in app: raise RuntimeError("web bind anchor missing")
    app = app.replace(bind_anchor, bind_code + bind_anchor, 1)
write("web/app.js", app)

css = read("web/geek.css")
css_add = r'''
/* Operator integrations / production hardening */
.integration-status-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:12px}.integration-status-card{display:flex;gap:10px;align-items:center;padding:13px 14px;border:1px solid var(--border,#cfe0db);background:#fff;min-height:70px}.integration-status-card div{display:flex;flex-direction:column;gap:3px;min-width:0}.integration-status-card strong{font:700 12px Cascadia Mono,Consolas,monospace}.integration-status-card small{color:var(--muted,#60736d);overflow:hidden;text-overflow:ellipsis}.integration-light{width:10px;height:10px;border-radius:50%;background:#a96600;box-shadow:0 0 0 3px rgba(169,102,0,.12)}.integration-light.ready{background:#00a86b;box-shadow:0 0 0 3px rgba(0,168,107,.12)}.operator-policy{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.operator-policy>div{border:1px solid #dbe9e5;padding:12px;display:flex;justify-content:space-between;align-items:center}.operator-policy span{font:600 11px Cascadia Mono,Consolas,monospace;color:#60736d}.operator-policy strong{font:800 14px Cascadia Mono,Consolas,monospace;color:#007f92}.operator-policy p{grid-column:1/-1;margin:0;color:#60736d}.operator-integrations{margin-top:12px}.integration-form-card label{display:flex;flex-direction:column;gap:5px;margin:9px 0}.integration-form-card .switch-row{flex-direction:row}.form-note{font-size:12px;color:#60736d;line-height:1.6}.operator-task-details{margin:10px 0}.operator-detail-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:7px}.operator-detail-grid span{padding:8px;border:1px solid #dbe9e5;display:flex;flex-direction:column;font-size:11px;color:#60736d}.operator-detail-grid strong{font-family:Cascadia Mono,Consolas,monospace;color:#071410;margin-top:3px}.operator-task-details>p{font-size:12px;color:#60736d;margin:7px 0 0}@media(max-width:900px){.integration-status-grid,.operator-policy{grid-template-columns:1fr 1fr}}@media(max-width:620px){.integration-status-grid,.operator-policy{grid-template-columns:1fr}}
'''
if 'Operator integrations / production hardening' not in css:
    css += '\n' + css_add
write("web/geek.css", css)

# ----------------------------- Native Desktop UI -----------------------------
desktop = read("desktop.py")
desktop = desktop.replace('from tkinter import filedialog, messagebox, ttk', 'from tkinter import filedialog, messagebox, simpledialog, ttk', 1)
desktop = desktop.replace('Get-Command python,node,git,openai,codex,gemini,ollama', 'Get-Command python,node,git,codex,gemini,ollama', 1)
desktop = desktop.replace('        tab.grid_rowconfigure(1, weight=1)\n        status_frame = ttk.Frame(tab, style="Panel2.TFrame", padding=9)', '        tab.grid_rowconfigure(2, weight=1)\n        status_frame = ttk.Frame(tab, style="Panel2.TFrame", padding=9)', 1)
config_anchor = '        config = ttk.Frame(tab, style="Panel2.TFrame", padding=12)\n        config.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 10))\n'
ops = '''        ops = ttk.LabelFrame(tab, text="Operator 整合與發布", style="TLabelframe", padding=10)\n        ops.grid(row=1, column=0, sticky="ew", padx=10, pady=5)\n        ops.grid_columnconfigure(0, weight=1)\n        self.resource_policy_var = tk.StringVar(value="RESOURCE GOVERNOR // probing")\n        ttk.Label(ops, textvariable=self.resource_policy_var, style="PanelMuted.TLabel").grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 8))\n        ttk.Button(ops, text="同步 Kimi / DeepSeek", style="Accent.TButton", command=self.sync_official_models).grid(row=1, column=0, sticky="w")\n        ttk.Button(ops, text="Google Play", command=self.publish_google_play).grid(row=1, column=1, padx=5)\n        ttk.Button(ops, text="Google Sites", command=self.open_google_sites).grid(row=1, column=2, padx=5)\n        ttk.Button(ops, text="立即維護", command=self.run_maintenance_now).grid(row=1, column=3, padx=5)\n        ttk.Button(ops, text="重新檢查", command=lambda: self.refresh_providers(True)).grid(row=1, column=4, sticky="e")\n\n        config = ttk.Frame(tab, style="Panel2.TFrame", padding=12)\n        config.grid(row=2, column=0, sticky="nsew", padx=10, pady=(5, 10))\n'''
if ops not in desktop:
    if config_anchor not in desktop: raise RuntimeError("native integrations config anchor missing")
    desktop = desktop.replace(config_anchor, ops, 1)

populate_anchor = '        self.integration_tree.insert("", tk.END, iid="comfyui", values=values, tags=(tag,))\n\n    def save_integrations(self) -> None:\n'
populate_new = '''        self.integration_tree.insert("", tk.END, iid="comfyui", values=values, tags=(tag,))\n        integration_state = self.app.integrations.status()\n        play = integration_state.get("google_play", {})\n        self.integration_tree.insert("", tk.END, iid="google-play", values=("Google Play", "account", "READY" if play.get("token_present") else "TOKEN REQUIRED", play.get("mode")), tags=("online" if play.get("token_present") else "setup",))\n        self.integration_tree.insert("", tk.END, iid="google-sites", values=("Google Sites", "browser", "ASSISTED", "Modern Sites browser-assisted session"), tags=("online",))\n        sync = integration_state.get("model_sync", {})\n        self.integration_tree.insert("", tk.END, iid="model-sync", values=("Kimi / DeepSeek metadata", "models", "READY" if sync.get("metadata_present") else "SYNC REQUIRED", "official organization metadata"), tags=("online" if sync.get("metadata_present") else "setup",))\n        if hasattr(self, "resource_policy_var"):\n            policy = self.app.hardware.resource_policy(int(self.app.settings.get("max_parallel_agents", 3)))\n            reasons = " · ".join(policy.get("reasons") or [])\n            self.resource_policy_var.set(f"RESOURCE GOVERNOR // parallel={policy.get('max_parallel_agents')} // remote-first={policy.get('prefer_remote_model')} // {reasons}")\n\n    def save_integrations(self) -> None:\n'''
if populate_new not in desktop:
    if populate_anchor not in desktop: raise RuntimeError("native integration populate anchor missing")
    desktop = desktop.replace(populate_anchor, populate_new, 1)

method_anchor = '    def install_clis(self) -> None:\n'
native_methods = r'''    def sync_official_models(self) -> None:
        if not self.current_project_id:
            return
        self._set_status("MODEL SYNC // official metadata")
        self._async(
            lambda: self.app.sync_models({"project_id": self.current_project_id, "conversation_id": self.current_conversation_id}),
            lambda result: self._show_transfer_task(result, "官方模型同步"),
        )

    def publish_google_play(self) -> None:
        if not self.current_project_id:
            return
        artifact = filedialog.askopenfilename(parent=self.root, title="選擇 APK / AAB", filetypes=(("Android artifacts", "*.apk *.aab"), ("All files", "*.*")))
        if not artifact:
            return
        package = simpledialog.askstring("Google Play", "Package name", parent=self.root)
        if not package:
            return
        track = simpledialog.askstring("Google Play", "Track (internal / alpha / beta / production)", initialvalue="internal", parent=self.root) or "internal"
        status = simpledialog.askstring("Google Play", "Release status (draft / inProgress / halted / completed)", initialvalue="draft", parent=self.root) or "draft"
        commit = messagebox.askyesno("Google Play", "要正式 COMMIT 這個 edit 嗎？\n\n選「否」只會 upload + validate。", icon="warning", parent=self.root)
        payload = {"project_id": self.current_project_id, "conversation_id": self.current_conversation_id,
                   "permission_mode": self.permission_var.get(), "package": package.strip(), "artifact": artifact,
                   "track": track.strip(), "status": status.strip(), "commit": commit}
        def builder(approval_id: str | None) -> dict[str, Any]:
            return self.app.publish_play({**payload, "approval_id": approval_id})
        self._guarded(builder, lambda result: self._show_transfer_task(result, "Google Play"))

    def open_google_sites(self) -> None:
        if not self.current_project_id:
            return
        title = simpledialog.askstring("Google Sites", "網站標題", parent=self.root)
        if not title:
            return
        profile = simpledialog.askstring("Google Sites", "Chrome / Edge profile（選填，例如 Default）", parent=self.root)
        payload = {"project_id": self.current_project_id, "conversation_id": self.current_conversation_id,
                   "title": title.strip(), "profile": profile.strip() if profile else None}
        def builder(approval_id: str | None) -> dict[str, Any]:
            return self.app.open_sites({**payload, "approval_id": approval_id})
        self._guarded(builder, lambda result: self._show_transfer_task(result, "Google Sites"))

    def run_maintenance_now(self) -> None:
        self._async(
            lambda: self.app.run_maintenance({"permission_mode": self.permission_var.get()}),
            lambda result: self._set_status(f"MAINTENANCE // backup={result.get('backup', 'ok')}"),
        )

'''
if native_methods not in desktop:
    if method_anchor not in desktop: raise RuntimeError("native method anchor missing")
    desktop = desktop.replace(method_anchor, native_methods + method_anchor, 1)
write("desktop.py", desktop)

# ----------------------------- Truthful progress -----------------------------
tasks = read("ai_hub/task_manager_v2.py")
tasks = tasks.replace('status="running", stage="準備上下文", progress=1, started_at=utcnow()', 'status="running", stage="準備上下文", progress=0, started_at=utcnow()')
tasks = tasks.replace('self.database.add_task_event(task_id, "工作已開始", progress=1)', 'self.database.add_task_event(task_id, "工作已開始", progress=None)')
tasks = tasks.replace('status="running", stage="執行中", progress=2, started_at=utcnow()', 'status="running", stage="執行中", progress=0, started_at=utcnow()')
write("ai_hub/task_manager_v2.py", tasks)

providers = read("ai_hub/providers.py")
# CLI stages/events are real; percentages are not. Keep stage text and leave progress unknown.
for old, new in [
    ('emit("工作階段已建立", session_id or "Codex session", 8, "info")', 'emit("工作階段已建立", session_id or "Codex session", None, "info")'),
    ('emit("產生回覆", str(item["text"]), 88, "message")', 'emit("產生回覆", str(item["text"]), None, "message")'),
    ('emit("執行工具", str(label)[:500], min(82, 18 + tool_count * 6), "tool")', 'emit("執行工具", str(label)[:500], None, "tool")'),
    ('emit("收尾與驗證", "Codex 已完成本輪工作", 96, "info")', 'emit("收尾與驗證", "Codex 已完成本輪工作", None, "info")'),
    ('emit("啟動 Codex", "使用 JSONL 事件串流", 3, "info")', 'emit("啟動 Codex", "使用 JSONL 事件串流", None, "info")'),
    ('emit("啟動 Gemini", "等待 Gemini CLI 回傳結構化結果", 4, "info")', 'emit("啟動 Gemini", "等待 Gemini CLI 回傳結構化結果", None, "info")'),
    ('emit("Gemini 完成", "已解析回覆與使用統計", 96, "info")', 'emit("Gemini 完成", "已解析回覆與使用統計", None, "info")'),
    ('emit("啟動本機模型", f"載入 {self.model}", 3, "info")', 'emit("啟動本機模型", f"載入 {self.model}", None, "info")'),
    ('emit("本機模型完成", f"輸出 {event.get(\'eval_count\', 0)} tokens", 96, "info")', 'emit("本機模型完成", f"輸出 {event.get(\'eval_count\', 0)} tokens", None, "info")'),
    ('emit("下載模型", model, 2, "info")', 'emit("下載模型", model, None, "info")'),
    ('emit("下載官方模型權重", repository, 2, "info")', 'emit("下載官方模型權重", repository, None, "info")'),
    ('emit("啟動 QLoRA", f"{model} · {dataset.name}", 2, "info")', 'emit("啟動 QLoRA", f"{model} · {dataset.name}", None, "info")'),
]:
    providers = providers.replace(old, new)
# Remove line-count progress heuristics for model/HF/training providers.
providers = providers.replace('''        progress = 2.0\n\n        def parse(line: str) -> None:\n            nonlocal progress\n            progress = min(94, progress + 0.35)\n            emit("下載模型", line, progress, "output")\n''', '''        def parse(line: str) -> None:\n            emit("下載模型", line, None, "output")\n''')
providers = providers.replace('''        progress = 2.0\n\n        def parse(line: str) -> None:\n            nonlocal progress\n            progress = min(96, progress + 0.18)\n            if line.strip():\n                emit("Hugging Face 下載中", line[-1500:], progress, "output")\n''', '''        def parse(line: str) -> None:\n            if line.strip():\n                emit("Hugging Face 下載中", line[-1500:], None, "output")\n''')
providers = providers.replace('''        progress = 3.0\n\n        def parse(line: str) -> None:\n            nonlocal progress\n            progress = min(96, progress + 0.4)\n            if line.strip():\n                emit("QLoRA 訓練中", line[-1500:], progress, "output")\n''', '''        def parse(line: str) -> None:\n            if line.strip():\n                emit("QLoRA 訓練中", line[-1500:], None, "output")\n''')
# Unknown Content-Length is bytes/s only, not a made-up percent.
providers = providers.replace('''                    else:\n                        progress = min(90, 3 + elapsed / 8)\n                        detail = f"{downloaded / 1024**2:.1f} MB · {downloaded / elapsed / 1024**2:.1f} MB/s"\n                    emit("下載中", detail, progress, "output")\n''', '''                    else:\n                        progress = None\n                        detail = f"{downloaded / 1024**2:.1f} MB · {downloaded / elapsed / 1024**2:.1f} MB/s"\n                    emit("下載中", detail, progress, "output")\n''')
write("ai_hub/providers.py", providers)

images = read("ai_hub/images.py")
images = images.replace('stage="送往 ComfyUI",\n            progress=3,', 'stage="送往 ComfyUI",\n            progress=0,')
images = images.replace('self.database.add_task_event(task_id, "正在建立 ComfyUI 工作流。", progress=3)', 'self.database.add_task_event(task_id, "正在建立 ComfyUI 工作流。", progress=None)')
images = images.replace('self.database.update_task(task_id, stage="等待繪圖節點", progress=8)', 'self.database.update_task(task_id, stage="等待繪圖節點", progress=0)')
images = images.replace('self.database.add_task_event(task_id, f"已排入 ComfyUI：{prompt_id}", progress=8)', 'self.database.add_task_event(task_id, f"已排入 ComfyUI：{prompt_id}", progress=None)')
write("ai_hub/images.py", images)

# ----------------------------- QLoRA production workflow -----------------------------
training = r'''from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QLoRA trainer for an eligible <=50B model")
    parser.add_argument("--model", required=True)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--eval-dataset", type=Path)
    parser.add_argument("--output", default=Path("training/output"), type=Path)
    parser.add_argument("--max-seq-length", default=2048, type=int)
    parser.add_argument("--epochs", default=1.0, type=float)
    parser.add_argument("--learning-rate", default=2e-4, type=float)
    parser.add_argument("--lora-rank", default=16, type=int)
    parser.add_argument("--revision")
    parser.add_argument("--seed", default=42, type=int)
    parser.add_argument("--resume-from-checkpoint", type=Path)
    parser.add_argument("--trust-remote-code", action="store_true")
    parser.add_argument("--full-sequence-loss", action="store_true", help="Train on all tokens instead of masking prompt tokens")
    parser.add_argument("--early-stopping-patience", default=2, type=int)
    parser.add_argument("--smoke-prompt", default="請用一句話說明你能做什麼。")
    parser.add_argument("--merge-output", type=Path)
    return parser.parse_args()


def load_dependencies():
    try:
        import inspect
        import torch
        from datasets import load_dataset
        from peft import LoraConfig, prepare_model_for_kbit_training
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            DataCollatorForSeq2Seq,
            EarlyStoppingCallback,
            Trainer,
            TrainingArguments,
        )
    except ImportError as error:
        raise SystemExit("缺少訓練套件。請在 WSL2/Linux CUDA 環境安裝 torch transformers datasets peft accelerate bitsandbytes。") from error
    return locals()


def json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def main() -> int:
    args = arguments()
    if not args.dataset.is_file():
        raise SystemExit(f"找不到資料集：{args.dataset}")
    if args.eval_dataset and not args.eval_dataset.is_file():
        raise SystemExit(f"找不到驗證資料集：{args.eval_dataset}")
    d = load_dependencies(); torch=d["torch"]; load_dataset=d["load_dataset"]
    if not torch.cuda.is_available():
        raise SystemExit("真正 QLoRA 訓練需要 NVIDIA CUDA；目前沒有可用 CUDA GPU，因此拒絕假裝完成訓練。")
    torch.manual_seed(args.seed); torch.cuda.manual_seed_all(args.seed)
    available_vram=sum(torch.cuda.get_device_properties(i).total_memory for i in range(torch.cuda.device_count()))/1024**3
    name=args.model.lower(); required_vram=80 if "48b" in name or "49b" in name else 48 if "32b" in name or "33b" in name else 24 if "14b" in name else 16
    if available_vram < required_vram:
        raise SystemExit(f"偵測到 {available_vram:.1f} GB CUDA VRAM；{args.model} 的保守 QLoRA 前檢需要至少 {required_vram} GB。")

    quantization=d["BitsAndBytesConfig"](load_in_4bit=True,bnb_4bit_quant_type="nf4",bnb_4bit_compute_dtype=torch.bfloat16,bnb_4bit_use_double_quant=True)
    tokenizer=d["AutoTokenizer"].from_pretrained(args.model, revision=args.revision, trust_remote_code=args.trust_remote_code)
    if tokenizer.pad_token is None: tokenizer.pad_token=tokenizer.eos_token
    model=d["AutoModelForCausalLM"].from_pretrained(args.model,revision=args.revision,device_map="auto",trust_remote_code=args.trust_remote_code,quantization_config=quantization)
    model=d["prepare_model_for_kbit_training"](model)
    model.add_adapter(d["LoraConfig"](r=args.lora_rank,lora_alpha=args.lora_rank*2,lora_dropout=.05,bias="none",task_type="CAUSAL_LM",target_modules="all-linear"))

    raw=load_dataset("json",data_files=str(args.dataset),split="train")
    eval_raw=load_dataset("json",data_files=str(args.eval_dataset),split="train") if args.eval_dataset else None
    if eval_raw is None and len(raw)>=20:
        split=raw.train_test_split(test_size=max(1,round(len(raw)*.1)),seed=args.seed)
        raw,eval_raw=split["train"],split["test"]

    def tokenize(example):
        messages=example.get("messages")
        if not isinstance(messages,list) or not messages: raise ValueError("每筆 JSONL 必須有 messages 陣列。")
        full_text=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=False)
        result=tokenizer(full_text,truncation=True,max_length=args.max_seq_length,add_special_tokens=False)
        if args.full_sequence_loss:
            result["labels"]=list(result["input_ids"]); return result
        assistant_indexes=[i for i,m in enumerate(messages) if isinstance(m,dict) and m.get("role")=="assistant"]
        if not assistant_indexes: raise ValueError("Assistant-only loss 需要每筆至少一個 assistant 訊息。")
        last=assistant_indexes[-1]
        prefix=messages[:last]
        prefix_text=tokenizer.apply_chat_template(prefix,tokenize=False,add_generation_prompt=True)
        prefix_ids=tokenizer(prefix_text,truncation=True,max_length=args.max_seq_length,add_special_tokens=False)["input_ids"]
        mask=min(len(prefix_ids),len(result["input_ids"]))
        result["labels"]=[-100]*mask + list(result["input_ids"])[mask:]
        return result

    train_tokens=raw.map(tokenize,remove_columns=raw.column_names)
    eval_tokens=eval_raw.map(tokenize,remove_columns=eval_raw.column_names) if eval_raw is not None else None
    args.output.mkdir(parents=True,exist_ok=True)
    kwargs=dict(output_dir=str(args.output),num_train_epochs=args.epochs,learning_rate=args.learning_rate,per_device_train_batch_size=1,gradient_accumulation_steps=16,gradient_checkpointing=True,bf16=True,logging_steps=5,save_strategy="epoch",report_to="none",seed=args.seed,data_seed=args.seed)
    callbacks=[]
    if eval_tokens is not None:
        parameter="eval_strategy" if "eval_strategy" in d["inspect"].signature(d["TrainingArguments"].__init__).parameters else "evaluation_strategy"
        kwargs[parameter]="epoch"; kwargs.update(load_best_model_at_end=True,metric_for_best_model="eval_loss",greater_is_better=False)
        callbacks=[d["EarlyStoppingCallback"](early_stopping_patience=max(1,args.early_stopping_patience))]
    training_args=d["TrainingArguments"](**kwargs)
    trainer=d["Trainer"](model=model,args=training_args,train_dataset=train_tokens,eval_dataset=eval_tokens,data_collator=d["DataCollatorForSeq2Seq"](tokenizer,model=model,label_pad_token_id=-100,pad_to_multiple_of=8),callbacks=callbacks)
    resume=str(args.resume_from_checkpoint.resolve()) if args.resume_from_checkpoint else None
    train_result=trainer.train(resume_from_checkpoint=resume); trainer.save_state(); trainer.save_model(str(args.output)); tokenizer.save_pretrained(str(args.output))
    eval_metrics=trainer.evaluate() if eval_tokens is not None else None
    curve=json_safe(trainer.state.log_history); (args.output/"training-curve.json").write_text(json.dumps(curve,ensure_ascii=False,indent=2),encoding="utf-8")

    smoke={"prompt":args.smoke_prompt,"ok":False}
    try:
        model.eval(); encoded=tokenizer(args.smoke_prompt,return_tensors="pt")
        device=next(model.parameters()).device; encoded={k:v.to(device) for k,v in encoded.items()}
        with torch.no_grad(): output=model.generate(**encoded,max_new_tokens=48,do_sample=False)
        smoke.update(ok=True,response=tokenizer.decode(output[0][encoded["input_ids"].shape[1]:],skip_special_tokens=True).strip())
    except Exception as error:
        smoke["error"]=str(error)

    merged=None
    if args.merge_output:
        try:
            args.merge_output.mkdir(parents=True,exist_ok=True)
            merged_model=model.merge_and_unload(); merged_model.save_pretrained(str(args.merge_output),safe_serialization=True); tokenizer.save_pretrained(str(args.merge_output)); merged=str(args.merge_output.resolve())
        except Exception as error:
            raise SystemExit(f"Adapter 已訓練，但要求的 merge/export 失敗：{error}") from error

    metadata={"base_model":args.model,"revision":args.revision,"dataset":str(args.dataset.resolve()),"train_examples":len(raw),"eval_examples":len(eval_raw) if eval_raw is not None else 0,"epochs":args.epochs,"lora_rank":args.lora_rank,"seed":args.seed,"assistant_only_loss":not args.full_sequence_loss,"trust_remote_code":args.trust_remote_code,"resumed_from":resume,"vram_gb":round(available_vram,1),"train_metrics":json_safe(train_result.metrics),"eval_metrics":json_safe(eval_metrics),"smoke_test":smoke,"merged_output":merged}
    (args.output/"ai-hub-training.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(metadata,ensure_ascii=False)); return 0


if __name__ == "__main__": sys.exit(main())
'''
write("training/train_lora.py", training)

training_readme = read("training/README.md")
addition = '''\n## Production training workflow\n\n`train_lora.py` now defaults to assistant-only loss, pins an optional Hugging Face revision, uses a deterministic seed, creates a validation split when there are at least 20 examples (or accepts `--eval-dataset`), supports early stopping, checkpoint resume, saves `training-curve.json`, runs an adapter smoke test, and can optionally `--merge-output` to export merged safetensors. `trust_remote_code` is opt-in rather than automatic.\n'''
if '## Production training workflow' not in training_readme:
    training_readme += addition
write("training/README.md", training_readme)

# Tests lock in the truthful-progress/UI integration source contracts without needing external accounts/GPU.
tests = read("tests/test_hardening.py")
insert_anchor = '\n\nif __name__=="__main__": unittest.main()\n'
new_tests = r'''
    def test_operator_ui_and_truthful_progress_contracts(self):
        root = Path(__file__).resolve().parents[1]
        web = (root / "web" / "index.html").read_text(encoding="utf-8")
        app = (root / "web" / "app.js").read_text(encoding="utf-8")
        providers = (root / "ai_hub" / "providers.py").read_text(encoding="utf-8")
        self.assertIn('data-view="integrations"', web)
        self.assertIn('/api/integrations/play', app)
        self.assertIn('progressLabel(progress)', app)
        self.assertNotIn('min(94, progress + 0.35)', providers)
        self.assertNotIn('min(96, progress + 0.4)', providers)

    def test_training_source_has_validation_and_assistant_masking(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "training" / "train_lora.py").read_text(encoding="utf-8")
        self.assertIn('--eval-dataset', source)
        self.assertIn('[-100]*mask', source)
        self.assertIn('EarlyStoppingCallback', source)
        self.assertIn('training-curve.json', source)
        self.assertIn('smoke_test', source)
'''
if 'test_operator_ui_and_truthful_progress_contracts' not in tests:
    if insert_anchor not in tests: raise RuntimeError("test file ending anchor missing")
    tests = tests.replace(insert_anchor, '\n' + new_tests + insert_anchor, 1)
write("tests/test_hardening.py", tests)

# Coverage document should reflect verified mechanisms, not old implementation status.
coverage = read("docs/PROMPT_COVERAGE.md")
coverage += '''\n\n## Production completion pass (2026-09-06)\n\n- Permission model: hardened Observe / Workspace / Full, selected-file rollback guard, one-shot expiring approvals, loopback authenticated web control plane.\n- Reliability: crash recovery + collaboration checkpoint resume + watchdog normal-exit/crash-loop handling + scheduler overlap/cross-midnight handling.\n- Quality: structured peer-review gate with remediation; unverified task completion no longer trains feasibility calibration.\n- Progress: elapsed-time and output-line fake percentages removed; unknown progress is explicitly shown as event-driven/unknown.\n- Models: official dynamic Kimi/DeepSeek metadata is merged into the main catalog and exposed through the Operator UI.\n- Integrations: Google Play, Google Sites browser-assisted session, model sync, and maintenance are exposed in Web and Native Desktop and run through Task/Approval/Audit backends.\n- Training: revision pinning, deterministic seed, assistant-only loss, validation/eval loss, early stopping, resume, training curve, smoke test, optional merged export.\n- Production engineering: runtime data git hygiene, retention/backups, cross-platform CI, and Windows executable artifact build.\n\nPlatform limits remain explicit: Modern Google Sites has no supported generic modern Sites write API; external-account flows need real user credentials/OAuth; real QLoRA execution requires compatible NVIDIA CUDA hardware; selected-file enforcement is rollback/snapshot based rather than a Windows kernel sandbox.\n'''
write("docs/PROMPT_COVERAGE.md", coverage)

print("operator completion migration applied")
