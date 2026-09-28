from __future__ import annotations

"""Premium native operator-console skin for AI Hub.

The functional implementation stays in desktop.py.  This entry point replaces the
native window class with a polished local-only desktop surface and adds convenient
launchers for the bundled Codex/Gemini CLIs.  PyInstaller builds this file as the
main AIHub.exe entry point.
"""

import os
import subprocess
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import desktop as native


# Dark graphite + restrained neon accents.  The base implementation resolves these
# module globals at runtime, so existing functional tabs inherit the same palette.
PALETTE = {
    "BG": "#070707",
    "PANEL": "#0B0B0D",
    "PANEL_2": "#111214",
    "EDGE": "#25272A",
    "CYAN": "#65D9E7",
    "GREEN": "#79DFA7",
    "PURPLE": "#B79CFF",
    "TEXT": "#ECEDEF",
    "MUTED": "#858A91",
    "WARN": "#E7B667",
    "DANGER": "#E87587",
    "INPUT_BG": "#090A0B",
    "SELECT_BG": "#1A3135",
}
for name, value in PALETTE.items():
    setattr(native, name, value)

BG = PALETTE["BG"]
PANEL = PALETTE["PANEL"]
PANEL_2 = PALETTE["PANEL_2"]
EDGE = PALETTE["EDGE"]
CYAN = PALETTE["CYAN"]
GREEN = PALETTE["GREEN"]
PURPLE = PALETTE["PURPLE"]
TEXT = PALETTE["TEXT"]
MUTED = PALETTE["MUTED"]
WARN = PALETTE["WARN"]
DANGER = PALETTE["DANGER"]
INPUT_BG = PALETTE["INPUT_BG"]
SELECT_BG = PALETTE["SELECT_BG"]
DEEP = "#040404"
SIDEBAR = "#080809"
HEADER = "#070708"
HOVER = "#17191C"

BaseDesktop = native.AIHubDesktop


class GeekDesktop(BaseDesktop):
    """Refined native-only operator deck with first-class local CLI access."""

    def __init__(self, app: native.AIHubApplication, max_control: bool = False):
        self._cpu_history: deque[tuple[float, float]] = deque(maxlen=90)
        self._memory_history: deque[tuple[float, float]] = deque(maxlen=90)
        self._dashboard_tasks: list[dict[str, Any]] = []
        self._dashboard_task_signature: tuple[Any, ...] | None = None
        self._dashboard_canvases: dict[str, tk.Canvas] = {}
        self._dashboard_kpis: dict[str, tuple[tk.StringVar, tk.StringVar]] = {}
        self._dashboard_live_var: tk.StringVar | None = None
        self._dashboard_last_sample = 0.0
        super().__init__(app, max_control=max_control)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=("Microsoft JhengHei UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Header.TFrame", background=HEADER)
        style.configure("Sidebar.TFrame", background=SIDEBAR)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Panel2.TFrame", background=PANEL_2)
        style.configure("Card.TFrame", background=PANEL_2, bordercolor=EDGE, relief="flat")

        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Panel2.TLabel", background=PANEL_2, foreground=TEXT)
        style.configure("Sidebar.TLabel", background=SIDEBAR, foreground=TEXT)
        style.configure("SidebarMuted.TLabel", background=SIDEBAR, foreground=MUTED)
        style.configure("HeaderMuted.TLabel", background=HEADER, foreground=MUTED)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Muted.TLabel", background=PANEL_2, foreground=MUTED)
        style.configure("Section.TLabel", background=SIDEBAR, foreground=CYAN, font=("Cascadia Mono", 8, "bold"))
        style.configure("Title.TLabel", background=HEADER, foreground=TEXT, font=("Cascadia Mono", 19, "bold"))
        style.configure("BrandAccent.TLabel", background=HEADER, foreground=CYAN, font=("Cascadia Mono", 19, "bold"))
        style.configure("Metric.TLabel", background=PANEL_2, foreground=CYAN, font=("Cascadia Mono", 9, "bold"))
        style.configure("HeaderMetric.TLabel", background=HEADER, foreground=GREEN, font=("Cascadia Mono", 9, "bold"))
        style.configure("Hero.TLabel", background=PANEL_2, foreground=TEXT, font=("Cascadia Mono", 13, "bold"))
        style.configure("DashboardTitle.TLabel", background=BG, foreground=TEXT, font=("Microsoft JhengHei UI", 16, "bold"))
        style.configure("DashboardSub.TLabel", background=BG, foreground=MUTED, font=("Cascadia Mono", 8))
        style.configure("DashboardLive.TLabel", background=BG, foreground=GREEN, font=("Cascadia Mono", 8, "bold"))
        style.configure("ChartTitle.TLabel", background=PANEL, foreground=TEXT, font=("Cascadia Mono", 9, "bold"))
        style.configure("ChartMeta.TLabel", background=PANEL, foreground=MUTED, font=("Cascadia Mono", 7))
        style.configure("Kpi.TFrame", background=PANEL_2, bordercolor=EDGE, relief="flat")
        style.configure("KpiTitle.TLabel", background=PANEL_2, foreground=MUTED, font=("Cascadia Mono", 8, "bold"))
        style.configure("KpiValue.TLabel", background=PANEL_2, foreground=TEXT, font=("Cascadia Mono", 18, "bold"))
        style.configure("KpiMeta.TLabel", background=PANEL_2, foreground=MUTED, font=("Microsoft JhengHei UI", 8))

        style.configure(
            "TButton",
            background="#141518",
            foreground=TEXT,
            bordercolor=EDGE,
            focuscolor=CYAN,
            padding=(11, 7),
            font=("Microsoft JhengHei UI", 9),
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", HOVER), ("pressed", "#1A1C1F")],
            foreground=[("disabled", "#536570")],
            bordercolor=[("focus", CYAN), ("active", "#35383D")],
        )
        style.configure("Ghost.TButton", background=HEADER, foreground=MUTED, bordercolor=EDGE, padding=(10, 6))
        style.map("Ghost.TButton", background=[("active", HOVER)], foreground=[("active", TEXT)])
        style.configure("Accent.TButton", background="#12363B", foreground=CYAN, bordercolor="#25606A", padding=(12, 7))
        style.map("Accent.TButton", background=[("active", "#17454C"), ("pressed", "#102D31")])
        style.configure("Green.TButton", background="#153626", foreground=GREEN, bordercolor="#286141", padding=(12, 7))
        style.map("Green.TButton", background=[("active", "#1B4932"), ("pressed", "#10291D")])
        style.configure("Danger.TButton", background="#36161A", foreground=DANGER, bordercolor="#69303A", padding=(12, 7))
        style.map("Danger.TButton", background=[("active", "#4A1D24")])
        style.configure("Cli.TButton", background="#11191A", foreground=CYAN, bordercolor="#293638", padding=(12, 7), font=("Cascadia Mono", 9, "bold"))
        style.map("Cli.TButton", background=[("active", "#1A2425")], foreground=[("active", TEXT)])

        style.configure("TEntry", fieldbackground=INPUT_BG, foreground=TEXT, insertcolor=CYAN, bordercolor=EDGE, padding=8)
        style.map("TEntry", bordercolor=[("focus", CYAN)])
        style.configure("TCombobox", fieldbackground=INPUT_BG, background=INPUT_BG, foreground=TEXT, arrowcolor=CYAN, bordercolor=EDGE, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", INPUT_BG)], foreground=[("readonly", TEXT)], bordercolor=[("focus", CYAN)])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT, indicatorcolor="#1C1E21", padding=4)
        style.map("TCheckbutton", indicatorcolor=[("selected", GREEN)], foreground=[("disabled", MUTED)])
        style.configure("Sidebar.TCheckbutton", background=SIDEBAR, foreground=TEXT, indicatorcolor="#1C1E21", padding=4)
        style.map("Sidebar.TCheckbutton", indicatorcolor=[("selected", GREEN)], foreground=[("disabled", MUTED)])

        style.configure(
            "Treeview",
            background=PANEL,
            fieldbackground=PANEL,
            foreground=TEXT,
            bordercolor=EDGE,
            rowheight=31,
            font=("Microsoft JhengHei UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#151619",
            foreground=CYAN,
            bordercolor=EDGE,
            font=("Cascadia Mono", 8, "bold"),
            padding=(5, 7),
        )
        style.map("Treeview", background=[("selected", SELECT_BG)], foreground=[("selected", TEXT)])
        style.map("Treeview.Heading", background=[("active", HOVER)])

        style.configure("TNotebook", background=BG, bordercolor=BG, tabmargins=(8, 8, 8, 0))
        style.configure(
            "TNotebook.Tab",
            background="#0A0A0B",
            foreground=MUTED,
            bordercolor=EDGE,
            padding=(15, 9),
            font=("Cascadia Mono", 8, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL_2), ("active", "#181A1D")],
            foreground=[("selected", CYAN), ("active", TEXT)],
            bordercolor=[("selected", "#36393D")],
        )
        style.configure("TProgressbar", troughcolor="#191A1C", background=GREEN, bordercolor=EDGE, lightcolor=GREEN, darkcolor=GREEN)
        style.configure("TLabelframe", background=PANEL, foreground=CYAN, bordercolor=EDGE, relief="solid")
        style.configure("TLabelframe.Label", background=PANEL, foreground=CYAN, font=("Cascadia Mono", 8, "bold"))

        self.root.option_add("*TCombobox*Listbox.background", INPUT_BG)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", SELECT_BG)
        self.root.option_add("*TCombobox*Listbox.selectForeground", TEXT)

    def _build_shell(self) -> None:
        self.root.configure(bg=BG)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        self._build_header()

        content = tk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL,
            bg=EDGE,
            sashwidth=2,
            borderwidth=0,
            sashrelief=tk.FLAT,
            showhandle=False,
        )
        content.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 0))
        sidebar = ttk.Frame(content, style="Sidebar.TFrame", width=294)
        self.main = ttk.Frame(content, style="TFrame")
        content.add(sidebar, minsize=266, width=294)
        content.add(self.main, minsize=860)
        self._build_sidebar(sidebar)
        self._build_workspace(self.main)

        self.status_var = tk.StringVar(value="SYSTEM // 初始化本機 Operator Console…")
        status = tk.Label(
            self.root,
            textvariable=self.status_var,
            bg="#05090D",
            fg=MUTED,
            anchor="w",
            padx=16,
            pady=7,
            font=("Cascadia Mono", 8),
            highlightthickness=1,
            highlightbackground="#0F1A22",
        )
        status.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))

    def _build_header(self) -> None:
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(20, 13, 16, 12))
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        header.grid_columnconfigure(1, weight=1)

        brand = ttk.Frame(header, style="Header.TFrame")
        brand.grid(row=0, column=0, rowspan=2, sticky="w")
        ttk.Label(brand, text="AI", style="BrandAccent.TLabel").pack(side=tk.LEFT)
        ttk.Label(brand, text="//HUB", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(
            header,
            text="LOCAL OPERATOR CONSOLE  ·  NATIVE WINDOWS",
            style="HeaderMuted.TLabel",
            font=("Cascadia Mono", 8),
        ).grid(row=1, column=1, sticky="w", padx=(18, 0))

        actions = ttk.Frame(header, style="Header.TFrame")
        actions.grid(row=0, column=1, sticky="e", padx=(18, 0))
        ttk.Button(actions, text="CODEX CLI", style="Cli.TButton", command=lambda: self.open_cli_shell("codex")).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="GEMINI CLI", style="Cli.TButton", command=lambda: self.open_cli_shell("gemini")).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="TERMINAL", style="Ghost.TButton", command=self.focus_terminal).pack(side=tk.LEFT, padx=(6, 0))

        self.header_state = tk.StringVar(value="● LOCAL / SECURE")
        ttk.Label(header, textvariable=self.header_state, style="HeaderMetric.TLabel").grid(row=1, column=2, sticky="e", padx=(18, 0))

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(4, weight=1)

        identity = ttk.Frame(parent, style="Sidebar.TFrame", padding=(16, 15, 16, 8))
        identity.grid(row=0, column=0, sticky="ew")
        ttk.Label(identity, text="WORKSPACE", style="Section.TLabel").pack(anchor="w")
        ttk.Label(identity, text="本機專案與工作階段", style="SidebarMuted.TLabel", font=("Microsoft JhengHei UI", 9)).pack(anchor="w", pady=(3, 0))

        project_row = ttk.Frame(parent, style="Sidebar.TFrame", padding=(14, 3, 14, 8))
        project_row.grid(row=1, column=0, sticky="ew")
        project_row.grid_columnconfigure(0, weight=1)
        self.project_combo = ttk.Combobox(project_row, state="readonly")
        self.project_combo.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.project_combo.bind("<<ComboboxSelected>>", self._select_project)
        ttk.Button(project_row, text="＋", width=3, style="Ghost.TButton", command=self.add_project).grid(row=0, column=1)

        chat_bar = ttk.Frame(parent, style="Sidebar.TFrame", padding=(16, 8, 14, 6))
        chat_bar.grid(row=2, column=0, sticky="ew")
        chat_bar.grid_columnconfigure(0, weight=1)
        ttk.Label(chat_bar, text="SESSIONS", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(chat_bar, text="NEW", style="Ghost.TButton", command=self.new_conversation).grid(row=0, column=1)

        separator = tk.Frame(parent, bg=EDGE, height=1)
        separator.grid(row=3, column=0, sticky="ew", padx=14)

        tree_wrap = tk.Frame(parent, bg=SIDEBAR)
        tree_wrap.grid(row=4, column=0, sticky="nsew", padx=10, pady=(6, 4))
        tree_wrap.grid_columnconfigure(0, weight=1)
        tree_wrap.grid_rowconfigure(0, weight=1)
        self.conversation_tree = ttk.Treeview(tree_wrap, show="tree", selectmode="browse")
        self.conversation_tree.grid(row=0, column=0, sticky="nsew")
        self.conversation_tree.column("#0", width=248, stretch=True)
        self.conversation_tree.bind("<<TreeviewSelect>>", self._select_conversation)

        options = ttk.LabelFrame(parent, text="MISSION CONTROL", style="TLabelframe", padding=10)
        options.grid(row=5, column=0, sticky="ew", padx=10, pady=(6, 8))
        options.grid_columnconfigure(0, weight=1)
        self.provider_frame = ttk.Frame(options, style="Panel.TFrame")
        self.provider_frame.grid(row=0, column=0, sticky="ew", pady=(0, 3))
        self.collaboration_var = tk.BooleanVar(value=True)
        self.web_var = tk.BooleanVar(value=bool(self.app.settings.get("web_access", True)))
        self.crawler_var = tk.BooleanVar(value=bool(self.app.settings.get("crawler_enabled", True)))
        self.review_var = tk.BooleanVar(value=bool(self.app.settings.get("auto_peer_review", True)))
        self.adaptive_var = tk.BooleanVar(value=bool(self.app.settings.get("adaptive_performance", False)))
        ttk.Checkbutton(options, text="Multi-Agent 編排", variable=self.collaboration_var).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(options, text="外部搜尋 / 網路資料", variable=self.web_var).grid(row=2, column=0, sticky="w")
        ttk.Checkbutton(options, text="Peer Review 品質閘門", variable=self.review_var).grid(row=3, column=0, sticky="w")
        ttk.Checkbutton(options, text="研究網址自動索引", variable=self.crawler_var, command=self.toggle_crawler).grid(row=4, column=0, sticky="w")
        ttk.Checkbutton(options, text="自適應資源治理", variable=self.adaptive_var, command=self.toggle_adaptive).grid(row=5, column=0, sticky="w")

        permission_row = ttk.Frame(options, style="Panel.TFrame")
        permission_row.grid(row=6, column=0, sticky="ew", pady=(7, 0))
        permission_row.grid_columnconfigure(1, weight=1)
        ttk.Label(permission_row, text="ACCESS", style="PanelMuted.TLabel", font=("Cascadia Mono", 8, "bold")).grid(row=0, column=0, padx=(0, 8))
        self.permission_var = tk.StringVar(value="full" if self.app.full_access_unlocked() else "workspace")
        permission = ttk.Combobox(permission_row, textvariable=self.permission_var, values=("workspace", "observe", "full"), state="readonly", width=12)
        permission.grid(row=0, column=1, sticky="ew")

        footer = ttk.Frame(parent, style="Sidebar.TFrame", padding=(12, 2, 12, 12))
        footer.grid(row=6, column=0, sticky="ew")
        ttk.Button(footer, text="⌘  OPEN CLI DECK", style="Cli.TButton", command=self.focus_terminal).pack(fill=tk.X)

    def _build_workspace(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        self.tabs = ttk.Notebook(parent)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=(0, 0))

        self.overview_tab = ttk.Frame(self.tabs)
        self.chat_tab = ttk.Frame(self.tabs)
        self.agents_tab = ttk.Frame(self.tabs)
        self.files_tab = ttk.Frame(self.tabs)
        self.database_tab = ttk.Frame(self.tabs)
        self.terminal_tab = ttk.Frame(self.tabs)
        self.models_tab = ttk.Frame(self.tabs)
        self.integrations_tab = ttk.Frame(self.tabs)
        self.automation_tab = ttk.Frame(self.tabs)
        self.draw_tab = ttk.Frame(self.tabs)
        for frame, label in (
            (self.overview_tab, "00  OVERVIEW"),
            (self.chat_tab, "01  CHAT"),
            (self.agents_tab, "02  TASKS"),
            (self.files_tab, "03  FILES"),
            (self.database_tab, "04  SEARCH"),
            (self.terminal_tab, "05  CLI"),
            (self.models_tab, "06  MODELS"),
            (self.integrations_tab, "07  INTEGRATIONS"),
            (self.automation_tab, "08  AUTOMATION"),
            (self.draw_tab, "09  IMAGE"),
        ):
            self.tabs.add(frame, text=label)

        self._build_overview_tab()
        self._build_chat_tab()
        BaseDesktop._build_agents_tab(self)
        BaseDesktop._build_files_tab(self)
        BaseDesktop._build_database_tab(self)
        self._build_terminal_tab()
        BaseDesktop._build_models_tab(self)
        BaseDesktop._build_integrations_tab(self)
        BaseDesktop._build_automation_tab(self)
        BaseDesktop._build_draw_tab(self)

    def _build_overview_tab(self) -> None:
        tab = self.overview_tab
        tab.grid_columnconfigure(0, weight=3, uniform="overview_top")
        tab.grid_columnconfigure(1, weight=2, uniform="overview_top")
        tab.grid_rowconfigure(2, weight=3, minsize=210)
        tab.grid_rowconfigure(3, weight=2, minsize=165)

        heading = ttk.Frame(tab, style="TFrame", padding=(14, 12, 14, 7))
        heading.grid(row=0, column=0, columnspan=2, sticky="ew")
        heading.grid_columnconfigure(0, weight=1)
        ttk.Label(heading, text="SYSTEM OVERVIEW", style="DashboardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(heading, text="LOCAL TELEMETRY  /  LIVE WORKSPACE", style="DashboardSub.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 0))
        self._dashboard_live_var = tk.StringVar(value="LIVE  //  WAITING FOR SAMPLE")
        ttk.Label(heading, textvariable=self._dashboard_live_var, style="DashboardLive.TLabel").grid(row=0, column=1, rowspan=2, sticky="e")

        kpis = ttk.Frame(tab, style="TFrame")
        kpis.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(2, 9))
        for column in range(4):
            kpis.grid_columnconfigure(column, weight=1, uniform="overview_kpi")
        for column, (key, label) in enumerate((
            ("cpu", "CPU LOAD"),
            ("memory", "MEMORY"),
            ("disk", "DISK FREE"),
            ("tasks", "ACTIVE TASKS"),
        )):
            card = ttk.Frame(kpis, style="Kpi.TFrame", padding=(13, 9))
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 5 if column < 3 else 0))
            ttk.Label(card, text=label, style="KpiTitle.TLabel").pack(anchor="w")
            value = tk.StringVar(value="--")
            meta = tk.StringVar(value="WAITING FOR LIVE DATA")
            ttk.Label(card, textvariable=value, style="KpiValue.TLabel").pack(anchor="w", pady=(4, 0))
            ttk.Label(card, textvariable=meta, style="KpiMeta.TLabel").pack(anchor="w", pady=(1, 0))
            self._dashboard_kpis[key] = (value, meta)

        self._dashboard_canvases["trend"] = self._chart_card(
            tab, "CPU / MEMORY TREND", "LAST 2 MINUTES  ·  SAMPLED LOCALLY", row=2, column=0
        )
        self._dashboard_canvases["resources"] = self._chart_card(
            tab, "RESOURCE PROFILE", "CURRENT UTILIZATION", row=2, column=1
        )
        self._dashboard_canvases["tasks"] = self._chart_card(
            tab, "TASK DISTRIBUTION", "LATEST 160 TASKS", row=3, column=0
        )
        self._dashboard_canvases["durations"] = self._chart_card(
            tab, "RECENT RUNTIME", "COMPLETED TASKS  ·  ACTUAL ELAPSED TIME", row=3, column=1
        )

    def _chart_card(
        self, parent: ttk.Frame, title: str, meta: str, *, row: int, column: int
    ) -> tk.Canvas:
        frame = tk.Frame(parent, bg=EDGE, padx=1, pady=1)
        frame.grid(row=row, column=column, sticky="nsew", padx=(14 if column == 0 else 5, 5 if column == 0 else 14), pady=(0, 9 if row == 2 else 13))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        body = ttk.Frame(frame, style="Panel.TFrame")
        body.grid(row=0, column=0, rowspan=2, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)
        header = ttk.Frame(body, style="Panel.TFrame", padding=(12, 9, 12, 4))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ttk.Label(header, text=title, style="ChartTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=meta, style="ChartMeta.TLabel").grid(row=0, column=1, sticky="e")
        canvas = tk.Canvas(body, bg=PANEL, highlightthickness=0, bd=0, height=170)
        canvas.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 7))
        canvas.bind("<Configure>", lambda _event, chart=canvas: self._redraw_dashboard_chart(chart))
        return canvas

    def _set_dashboard_snapshot(self, snapshot: dict[str, Any]) -> None:
        now = time.monotonic()
        if now - self._dashboard_last_sample >= 1.0:
            self._dashboard_last_sample = now
            cpu = max(0.0, min(100.0, float(snapshot.get("cpu_percent") or 0)))
            memory = snapshot.get("memory") or {}
            self._cpu_history.append((now, cpu))
            self._memory_history.append((now, max(0.0, min(100.0, float(memory.get("percent") or 0)))))

        memory = snapshot.get("memory") or {}
        disk = snapshot.get("disk") or {}
        total_ram = memory.get("total_gb") or 0
        available_ram = memory.get("available_gb") or 0
        free_disk = disk.get("free_gb") or 0
        self._set_kpi("cpu", f"{float(snapshot.get('cpu_percent') or 0):.0f}%", "PROCESSOR UTILIZATION")
        self._set_kpi("memory", f"{int(memory.get('percent') or 0)}%", f"{available_ram:g} GB FREE / {total_ram:g} GB")
        self._set_kpi("disk", f"{free_disk:g} GB", f"{float(disk.get('percent') or 0):.0f}% USED")
        if self._dashboard_live_var:
            self._dashboard_live_var.set(f"● LIVE  //  {datetime.now().astimezone().strftime('%H:%M:%S')}")
        self._redraw_dashboard_chart(self._dashboard_canvases.get("trend"))
        self._redraw_dashboard_chart(self._dashboard_canvases.get("resources"), snapshot)

    def _set_dashboard_tasks(self, tasks: list[dict[str, Any]]) -> None:
        self._dashboard_tasks = tasks
        signature = tuple(
            (task.get("id"), task.get("status"), round(float(task.get("progress") or 0), 1), task.get("started_at"), task.get("completed_at"))
            for task in tasks
        )
        if signature == self._dashboard_task_signature:
            return
        self._dashboard_task_signature = signature
        active = sum(task.get("status") in {"queued", "running", "cancelling"} for task in tasks)
        queued = sum(task.get("status") == "queued" for task in tasks)
        self._set_kpi("tasks", str(active), f"{queued} QUEUED  /  {len(tasks)} RECENT")
        self._redraw_dashboard_chart(self._dashboard_canvases.get("tasks"))
        self._redraw_dashboard_chart(self._dashboard_canvases.get("durations"))

    def _set_kpi(self, key: str, value: str, meta: str) -> None:
        variables = self._dashboard_kpis.get(key)
        if variables:
            variables[0].set(value)
            variables[1].set(meta)

    def _redraw_dashboard_chart(
        self, canvas: tk.Canvas | None, snapshot: dict[str, Any] | None = None
    ) -> None:
        if canvas is None or not canvas.winfo_exists():
            return
        chart = next((name for name, item in self._dashboard_canvases.items() if item is canvas), "")
        if chart == "trend":
            self._draw_trend_chart(canvas)
        elif chart == "resources":
            self._draw_resource_chart(canvas, snapshot or {})
        elif chart == "tasks":
            self._draw_task_chart(canvas)
        elif chart == "durations":
            self._draw_duration_chart(canvas)

    def _draw_trend_chart(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 240), max(canvas.winfo_height(), 145)
        left, right, top, bottom = 39, width - 13, 18, height - 25
        plot_height = bottom - top
        now = time.monotonic()
        for value in (0, 50, 100):
            y = bottom - plot_height * value / 100
            canvas.create_line(left, y, right, y, fill=EDGE, dash=(2, 4))
            canvas.create_text(left - 8, y, text=str(value), fill=MUTED, anchor="e", font=("Cascadia Mono", 7))
        for age in (120, 60, 0):
            x = left + (right - left) * (120 - age) / 120
            canvas.create_line(x, top, x, bottom, fill="#1B1C1E", dash=(1, 5))
            canvas.create_text(x, height - 7, text=f"-{age}s" if age else "NOW", fill=MUTED, anchor="s", font=("Cascadia Mono", 7))

        for history, color in ((self._cpu_history, CYAN), (self._memory_history, GREEN)):
            points: list[float] = []
            for timestamp, value in history:
                age = max(0.0, now - timestamp)
                if age > 120:
                    continue
                x = right - (right - left) * age / 120
                y = bottom - plot_height * max(0.0, min(100.0, value)) / 100
                points.extend((x, y))
            if len(points) >= 4:
                canvas.create_line(*points, fill=color, width=2, smooth=True, splinesteps=12)

        canvas.create_line(width - 150, 10, width - 137, 10, fill=CYAN, width=2)
        canvas.create_text(width - 132, 10, text="CPU", fill=TEXT, anchor="w", font=("Cascadia Mono", 7, "bold"))
        canvas.create_line(width - 90, 10, width - 77, 10, fill=GREEN, width=2)
        canvas.create_text(width - 72, 10, text="RAM", fill=TEXT, anchor="w", font=("Cascadia Mono", 7, "bold"))
        if len(self._cpu_history) < 2:
            canvas.create_text((left + right) / 2, (top + bottom) / 2, text="Collecting live samples…", fill=MUTED, font=("Cascadia Mono", 8))

    def _draw_resource_chart(self, canvas: tk.Canvas, snapshot: dict[str, Any]) -> None:
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 220), max(canvas.winfo_height(), 145)
        memory = snapshot.get("memory") or {}
        disk = snapshot.get("disk") or {}
        rows = (
            ("CPU", float(snapshot.get("cpu_percent") or 0), CYAN),
            ("MEMORY", float(memory.get("percent") or 0), GREEN),
            ("DISK", float(disk.get("percent") or 0), PURPLE),
        )
        label_x, bar_left, bar_right = 13, 88, width - 48
        bar_width = max(20, bar_right - bar_left)
        row_gap = (height - 34) / len(rows)
        for index, (label, value, color) in enumerate(rows):
            y = 18 + index * row_gap
            clipped = max(0.0, min(100.0, value))
            canvas.create_text(label_x, y, text=label, fill=MUTED, anchor="w", font=("Cascadia Mono", 7, "bold"))
            canvas.create_text(width - 12, y, text=f"{clipped:.0f}%", fill=TEXT, anchor="e", font=("Cascadia Mono", 8, "bold"))
            canvas.create_rectangle(bar_left, y + 11, bar_right, y + 18, fill="#202124", outline="")
            canvas.create_rectangle(bar_left, y + 11, bar_left + bar_width * clipped / 100, y + 18, fill=color, outline="")
        if not snapshot:
            canvas.create_text(width / 2, height - 9, text="Waiting for hardware snapshot", fill=MUTED, anchor="s", font=("Cascadia Mono", 7))

    def _draw_task_chart(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 240), max(canvas.winfo_height(), 130)
        states = (
            ("RUNNING", {"running", "cancelling"}, CYAN),
            ("QUEUED", {"queued"}, WARN),
            ("DONE", {"completed"}, GREEN),
            ("FAILED", {"failed"}, DANGER),
            ("CANCELLED", {"cancelled"}, MUTED),
        )
        counts = [(label, sum(task.get("status") in statuses for task in self._dashboard_tasks), color) for label, statuses, color in states]
        total = sum(count for _label, count, _color in counts)
        diameter = min(height - 20, 112)
        x0, y0 = 16, max(8, (height - diameter) / 2)
        bbox = (x0, y0, x0 + diameter, y0 + diameter)
        canvas.create_oval(*bbox, outline="#202124", width=13)
        if total:
            angle = 90
            for _label, count, color in counts:
                if not count:
                    continue
                extent = 360 * count / total
                canvas.create_arc(*bbox, start=angle, extent=-extent, style=tk.ARC, outline=color, width=13)
                angle -= extent
        canvas.create_text(x0 + diameter / 2, y0 + diameter / 2 - 3, text=str(total), fill=TEXT, font=("Cascadia Mono", 18, "bold"))
        canvas.create_text(x0 + diameter / 2, y0 + diameter / 2 + 17, text="TASKS", fill=MUTED, font=("Cascadia Mono", 7, "bold"))
        legend_x = x0 + diameter + 25
        legend_y = max(12, (height - len(counts) * 19) / 2)
        for index, (label, count, color) in enumerate(counts):
            y = legend_y + index * 19
            canvas.create_oval(legend_x, y - 4, legend_x + 7, y + 3, fill=color, outline="")
            canvas.create_text(legend_x + 14, y, text=label, fill=MUTED, anchor="w", font=("Cascadia Mono", 7, "bold"))
            canvas.create_text(width - 13, y, text=str(count), fill=TEXT, anchor="e", font=("Cascadia Mono", 8, "bold"))

    @staticmethod
    def _task_duration(task: dict[str, Any]) -> float | None:
        try:
            start = datetime.fromisoformat(str(task.get("started_at") or "").replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(task.get("completed_at") or "").replace("Z", "+00:00"))
            return max(0.0, (end - start).total_seconds())
        except (TypeError, ValueError):
            return None

    def _draw_duration_chart(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 260), max(canvas.winfo_height(), 130)
        completed = [
            (task, self._task_duration(task))
            for task in self._dashboard_tasks
            if task.get("status") == "completed"
        ]
        rows = sorted(
            ((task, duration) for task, duration in completed if duration is not None),
            key=lambda item: str(item[0].get("completed_at") or ""),
            reverse=True,
        )[:6]
        if not rows:
            canvas.create_text(width / 2, height / 2, text="No completed task timings yet", fill=MUTED, font=("Cascadia Mono", 8))
            return
        left, right = 116, width - 55
        top = 14
        row_height = min(25, max(16, (height - 22) / len(rows)))
        max_duration = max(duration for _task, duration in rows) or 1.0
        for index, (task, duration) in enumerate(rows):
            y = top + index * row_height
            title = str(task.get("provider_id") or task.get("title") or "TASK")[:15]
            canvas.create_text(left - 8, y + 5, text=title, fill=MUTED, anchor="e", font=("Cascadia Mono", 7))
            canvas.create_rectangle(left, y, right, y + 9, fill="#202124", outline="")
            canvas.create_rectangle(left, y, left + max(2, (right - left) * duration / max_duration), y + 9, fill=GREEN, outline="")
            canvas.create_text(width - 7, y + 5, text=native.compact_seconds(duration), fill=TEXT, anchor="e", font=("Cascadia Mono", 7))
        canvas.create_text(left, height - 4, text="FAST", fill=MUTED, anchor="sw", font=("Cascadia Mono", 7))
        canvas.create_text(right, height - 4, text="SLOW", fill=MUTED, anchor="se", font=("Cascadia Mono", 7))

    def _mono_text(self, parent: tk.Misc, **kwargs: Any) -> ScrolledText:
        return ScrolledText(
            parent,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=CYAN,
            selectbackground=SELECT_BG,
            selectforeground=TEXT,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=EDGE,
            highlightcolor="#2E6078",
            font=("Cascadia Mono", 10),
            padx=14,
            pady=12,
            wrap=tk.WORD,
            undo=True,
            **kwargs,
        )

    def _build_chat_tab(self) -> None:
        tab = self.chat_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        summary = ttk.Frame(tab, style="Card.TFrame", padding=(16, 12))
        summary.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 7))
        summary.grid_columnconfigure(1, weight=1)
        self.feasibility_score = tk.StringVar(value="MISSION READINESS  //  WAITING")
        self.feasibility_detail = tk.StringVar(value="工作送出前會評估成功性、可信度與 ETA")
        ttk.Label(summary, textvariable=self.feasibility_score, style="Metric.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(summary, textvariable=self.feasibility_detail, style="Muted.TLabel").grid(row=0, column=1, sticky="e")

        chat_wrap = tk.Frame(tab, bg=EDGE, padx=1, pady=1)
        chat_wrap.grid(row=1, column=0, sticky="nsew", padx=12)
        chat_wrap.grid_columnconfigure(0, weight=1)
        chat_wrap.grid_rowconfigure(0, weight=1)
        self.chat_text = self._mono_text(chat_wrap)
        self.chat_text.grid(row=0, column=0, sticky="nsew")
        self.chat_text.configure(state=tk.DISABLED)
        self.chat_text.tag_configure("user_header", foreground=CYAN, font=("Cascadia Mono", 9, "bold"), spacing1=14, spacing3=3)
        self.chat_text.tag_configure("assistant_header", foreground=GREEN, font=("Cascadia Mono", 9, "bold"), spacing1=14, spacing3=3)
        self.chat_text.tag_configure("system_header", foreground=WARN, font=("Cascadia Mono", 9, "bold"), spacing1=14, spacing3=3)
        self.chat_text.tag_configure("body", foreground=TEXT, lmargin1=10, lmargin2=10, rmargin=16, spacing3=9)

        composer = ttk.Frame(tab, style="Card.TFrame", padding=(12, 10))
        composer.grid(row=2, column=0, sticky="ew", padx=12, pady=(7, 12))
        composer.grid_columnconfigure(0, weight=1)
        top = ttk.Frame(composer, style="Panel2.TFrame")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        top.grid_columnconfigure(0, weight=1)
        self.context_var = tk.StringVar(value="CONTEXT // 尚未選取檔案")
        ttk.Label(top, textvariable=self.context_var, style="Muted.TLabel", font=("Cascadia Mono", 8)).grid(row=0, column=0, sticky="w")
        ttk.Button(top, text="FILES", style="Ghost.TButton", command=lambda: self.tabs.select(self.files_tab)).grid(row=0, column=1)

        self.prompt_text = tk.Text(
            composer,
            height=5,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=CYAN,
            selectbackground=SELECT_BG,
            selectforeground=TEXT,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#244052",
            highlightcolor=CYAN,
            font=("Cascadia Mono", 10),
            padx=13,
            pady=10,
            wrap=tk.WORD,
            undo=True,
        )
        self.prompt_text.grid(row=1, column=0, sticky="ew", padx=(0, 9))
        action = ttk.Frame(composer, style="Panel2.TFrame")
        action.grid(row=1, column=1, sticky="ns")
        ttk.Button(action, text="RUN MISSION\nCtrl+Enter", style="Green.TButton", command=self.send_prompt).pack(fill=tk.BOTH, expand=True)
        ttk.Button(action, text="ABORT", style="Danger.TButton", command=self.stop_latest_task).pack(fill=tk.X, pady=(6, 0))
        self.prompt_text.bind("<Control-Return>", lambda _event: self.send_prompt() or "break")

    def _build_terminal_tab(self) -> None:
        tab = self.terminal_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        hero = ttk.Frame(tab, style="Card.TFrame", padding=(16, 13))
        hero.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        hero.grid_columnconfigure(0, weight=1)
        ttk.Label(hero, text="LOCAL CLI DECK", style="Hero.TLabel").grid(row=0, column=0, sticky="w")
        self.cli_status_var = tk.StringVar(value=self._cli_status_text())
        ttk.Label(hero, textvariable=self.cli_status_var, style="Metric.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))
        cli_actions = ttk.Frame(hero, style="Panel2.TFrame")
        cli_actions.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Button(cli_actions, text="CODEX CLI", style="Cli.TButton", command=lambda: self.open_cli_shell("codex")).pack(side=tk.LEFT, padx=3)
        ttk.Button(cli_actions, text="GEMINI CLI", style="Cli.TButton", command=lambda: self.open_cli_shell("gemini")).pack(side=tk.LEFT, padx=3)
        ttk.Button(cli_actions, text="POWERSHELL", command=lambda: self.open_cli_shell("powershell")).pack(side=tk.LEFT, padx=3)
        ttk.Button(cli_actions, text="SETUP CLI", style="Accent.TButton", command=self.install_cli).pack(side=tk.LEFT, padx=(8, 0))

        quick = ttk.Frame(tab, style="Panel2.TFrame", padding=(12, 9))
        quick.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        ttk.Label(quick, text="QUICK COMMANDS", style="Metric.TLabel").pack(side=tk.LEFT, padx=(0, 10))
        for label, command in (
            ("TEST", "python -m unittest discover -v"),
            ("FILES", "Get-ChildItem -Force"),
            ("GIT", "git status --short"),
            ("ENV", "Get-Command python,node,git,codex,gemini,ollama -ErrorAction SilentlyContinue | Select-Object Name,Source"),
        ):
            ttk.Button(quick, text=label, style="Ghost.TButton", command=lambda value=command: self.set_terminal_command(value)).pack(side=tk.LEFT, padx=3)
        ttk.Button(quick, text="VS CODE", style="Ghost.TButton", command=lambda: self.set_terminal_command("code .")).pack(side=tk.RIGHT, padx=3)
        ttk.Button(quick, text="OPEN APP", style="Ghost.TButton", command=self.launch_local_app).pack(side=tk.RIGHT, padx=3)

        command_box = ttk.Frame(tab, style="Card.TFrame", padding=10)
        command_box.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        command_box.grid_columnconfigure(0, weight=1)
        self.terminal_command = tk.Text(
            command_box,
            height=4,
            bg=DEEP,
            fg="#C8F7DF",
            insertbackground=GREEN,
            selectbackground=SELECT_BG,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#1A3A2D",
            highlightcolor=GREEN,
            font=("Cascadia Mono", 10),
            padx=12,
            pady=9,
        )
        self.terminal_command.insert("1.0", "# 輸入 PowerShell 指令，或直接使用上方 Codex / Gemini CLI")
        self.terminal_command.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.terminal_command.bind("<Control-Return>", lambda _event: self.run_terminal() or "break")
        ttk.Button(command_box, text="EXECUTE\nCtrl+Enter", style="Green.TButton", command=self.run_terminal).grid(row=0, column=1, sticky="ns")

        output_wrap = tk.Frame(tab, bg="#173125", padx=1, pady=1)
        output_wrap.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 12))
        output_wrap.grid_columnconfigure(0, weight=1)
        output_wrap.grid_rowconfigure(0, weight=1)
        self.terminal_output = ScrolledText(
            output_wrap,
            bg=DEEP,
            fg="#B9E8D0",
            insertbackground=GREEN,
            selectbackground="#184B3A",
            selectforeground="#F1FFF8",
            relief=tk.FLAT,
            borderwidth=0,
            font=("Cascadia Mono", 9),
            padx=14,
            pady=12,
            wrap=tk.WORD,
        )
        self.terminal_output.grid(row=0, column=0, sticky="nsew")
        self.terminal_output.insert("1.0", "AI HUB LOCAL SHELL // READY\n\n")
        self.terminal_output.configure(state=tk.DISABLED)

    def _bind_shortcuts(self) -> None:
        BaseDesktop._bind_shortcuts(self)
        self.root.bind("<Control-grave>", lambda _event: self.focus_terminal() or "break")

    def focus_terminal(self) -> None:
        if hasattr(self, "tabs") and hasattr(self, "terminal_tab"):
            self.tabs.select(self.terminal_tab)
            if hasattr(self, "terminal_command"):
                self.terminal_command.focus_set()

    def _current_workdir(self) -> Path:
        if self.current_project_id:
            try:
                return Path(self.app.get_project(self.current_project_id)["path"]).resolve()
            except Exception:
                pass
        return Path(self.app.paths.root).resolve()

    def _cli_bin(self) -> Path:
        return Path(self.app.paths.root) / ".runtime" / "cli" / "node_modules" / ".bin"

    def _cli_status_text(self) -> str:
        cli_bin = self._cli_bin()
        codex = (cli_bin / "codex.cmd").is_file()
        gemini = (cli_bin / "gemini.cmd").is_file()
        return f"CLI STATUS  //  CODEX {'READY' if codex else 'NOT INSTALLED'}  ·  GEMINI {'READY' if gemini else 'NOT INSTALLED'}"

    @staticmethod
    def _ps_quote(value: str) -> str:
        return value.replace("'", "''")

    def install_cli(self) -> None:
        if os.name != "nt":
            messagebox.showerror("AI Hub", "CLI 初始化目前只支援 Windows 發行版。", parent=self.root)
            return
        setup = Path(self.app.paths.root) / "setup.ps1"
        if not setup.is_file():
            messagebox.showerror("AI Hub", "找不到 setup.ps1，請重新下載完整 Windows 套件。", parent=self.root)
            return
        if not messagebox.askyesno(
            "初始化 AI CLI",
            "將安裝 AI Hub 測試過的 Codex CLI 與 Gemini CLI。\n需要網路連線，可能會下載 Node.js。\n\n繼續嗎？",
            parent=self.root,
        ):
            return
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoExit",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(setup),
                "-InstallCli",
            ],
            cwd=str(self._current_workdir()),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        self._set_status("CLI SETUP // 已開啟初始化視窗；完成後可直接按 CODEX CLI / GEMINI CLI")
        self.root.after(3000, self._refresh_cli_badge)

    def _refresh_cli_badge(self) -> None:
        if hasattr(self, "cli_status_var"):
            self.cli_status_var.set(self._cli_status_text())

    def open_cli_shell(self, provider: str) -> None:
        if os.name != "nt":
            messagebox.showerror("AI Hub", "本機 CLI Deck 目前只支援 Windows。", parent=self.root)
            return
        provider = provider.lower().strip()
        workdir = self._current_workdir()
        cli_bin = self._cli_bin()
        env = os.environ.copy()
        env["PATH"] = str(cli_bin) + os.pathsep + env.get("PATH", "")
        env["PYTHONUTF8"] = "1"

        if provider == "powershell":
            subprocess.Popen(
                ["powershell.exe", "-NoLogo", "-NoExit"],
                cwd=str(workdir),
                env=env,
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
            self._set_status(f"CLI // PowerShell // {workdir}")
            return

        names = {"codex": "codex.cmd", "gemini": "gemini.cmd"}
        launcher_name = names.get(provider)
        if not launcher_name:
            return
        launcher = cli_bin / launcher_name
        if not launcher.is_file():
            self._refresh_cli_badge()
            if messagebox.askyesno(
                "CLI 尚未安裝",
                f"找不到 {provider.upper()} CLI。\n\n要現在開啟 CLI 初始化嗎？",
                parent=self.root,
            ):
                self.install_cli()
            return

        command = f"& '{self._ps_quote(str(launcher))}'"
        subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-NoExit", "-Command", command],
            cwd=str(workdir),
            env=env,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        self._refresh_cli_badge()
        self._set_status(f"CLI // {provider.upper()} // {workdir}")


# desktop.main() performs argument parsing, self-test support and application setup.
# Replacing the class here keeps all of that logic intact while making the packaged
# executable use the refined native surface.
native.AIHubDesktop = GeekDesktop

if __name__ == "__main__":
    raise SystemExit(native.main())
