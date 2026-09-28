from __future__ import annotations

"""Premium native operator-console skin for AI Hub.

The functional implementation stays in desktop.py.  This entry point replaces the
native window class with a polished local-only desktop surface and adds convenient
launchers for the bundled Codex/Gemini CLIs.  PyInstaller builds this file as the
main AIHub.exe entry point.
"""

import os
import queue
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import desktop as native
from ai_hub.cli_discovery import scan_local_ai_clis
from ai_hub.cli_usage import query_codex_usage


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
    "MUTED": "#A4AAB2",
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
        self._cli_usage_query_running = False
        self._cli_usage_timer: str | None = None
        self._cli_usage_refresh_button: ttk.Button | None = None
        self._cli_usage_checked_var: tk.StringVar | None = None
        self._gemini_usage_hint_var: tk.StringVar | None = None
        self._cli_usage_windows: dict[str, dict[str, Any]] = {}
        self._cli_scan_dialog: tk.Toplevel | None = None
        self._cli_scan_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._cli_scan_cancel: threading.Event | None = None
        self._cli_scan_running = False
        self._cli_scan_poll_after: str | None = None
        self._cli_scan_button: ttk.Button | None = None
        self._cli_scan_cancel_button: ttk.Button | None = None
        self._cli_scan_progress: ttk.Progressbar | None = None
        self._cli_scan_status: tk.StringVar | None = None
        self._cli_scan_summary: tk.StringVar | None = None
        self._cli_scan_tree: ttk.Treeview | None = None
        super().__init__(app, max_control=max_control)
        self.root.after(1500, self.refresh_cli_usage)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=("Microsoft JhengHei UI", 11))
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
        style.configure("Section.TLabel", background=SIDEBAR, foreground=CYAN, font=("Cascadia Mono", 9, "bold"))
        style.configure("Title.TLabel", background=HEADER, foreground=TEXT, font=("Cascadia Mono", 21, "bold"))
        style.configure("BrandAccent.TLabel", background=HEADER, foreground=CYAN, font=("Cascadia Mono", 21, "bold"))
        style.configure("Metric.TLabel", background=PANEL_2, foreground=CYAN, font=("Cascadia Mono", 11, "bold"))
        style.configure("HeaderMetric.TLabel", background=HEADER, foreground=GREEN, font=("Cascadia Mono", 10, "bold"))
        style.configure("Hero.TLabel", background=PANEL_2, foreground=TEXT, font=("Cascadia Mono", 14, "bold"))
        style.configure("DashboardTitle.TLabel", background=BG, foreground=TEXT, font=("Microsoft JhengHei UI", 19, "bold"))
        style.configure("DashboardSub.TLabel", background=BG, foreground=MUTED, font=("Cascadia Mono", 9))
        style.configure("DashboardLive.TLabel", background=BG, foreground=GREEN, font=("Cascadia Mono", 9, "bold"))
        style.configure("ChartTitle.TLabel", background=PANEL, foreground=TEXT, font=("Cascadia Mono", 11, "bold"))
        style.configure("ChartMeta.TLabel", background=PANEL, foreground=MUTED, font=("Cascadia Mono", 9))
        style.configure("Kpi.TFrame", background=PANEL_2, bordercolor=EDGE, relief="flat")
        style.configure("KpiTitle.TLabel", background=PANEL_2, foreground=MUTED, font=("Cascadia Mono", 9, "bold"))
        style.configure("KpiValue.TLabel", background=PANEL_2, foreground=TEXT, font=("Cascadia Mono", 21, "bold"))
        style.configure("KpiMeta.TLabel", background=PANEL_2, foreground=MUTED, font=("Microsoft JhengHei UI", 9))
        style.configure("Quota.Horizontal.TProgressbar", troughcolor="#1A1C1F", background=GREEN, bordercolor=EDGE, lightcolor=GREEN, darkcolor=GREEN)

        style.configure(
            "TButton",
            background="#141518",
            foreground=TEXT,
            bordercolor=EDGE,
            focuscolor=CYAN,
            padding=(13, 9),
            font=("Microsoft JhengHei UI", 10),
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
            rowheight=38,
            font=("Microsoft JhengHei UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background="#151619",
            foreground=CYAN,
            bordercolor=EDGE,
            font=("Cascadia Mono", 9, "bold"),
            padding=(7, 9),
        )
        style.map("Treeview", background=[("selected", SELECT_BG)], foreground=[("selected", TEXT)])
        style.map("Treeview.Heading", background=[("active", HOVER)])

        style.configure("TNotebook", background=BG, bordercolor=BG, tabmargins=(8, 8, 8, 0))
        style.configure(
            "TNotebook.Tab",
            background="#0A0A0B",
            foreground=MUTED,
            bordercolor=EDGE,
            padding=(10, 9),
            font=("Cascadia Mono", 9, "bold"),
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
        available_width = min(1540, max(600, self.root.winfo_screenwidth() - 24))
        sidebar_width = min(260, max(180, int(available_width * 0.27)))
        workspace_min_width = max(400, available_width - sidebar_width - 90)
        self._sidebar_width = sidebar_width
        sidebar = ttk.Frame(content, style="Sidebar.TFrame", width=sidebar_width)
        self.main = ttk.Frame(content, style="TFrame")
        content.add(sidebar, minsize=sidebar_width, width=sidebar_width)
        content.add(self.main, minsize=workspace_min_width)
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
        ttk.Button(actions, text="CODEX", style="Cli.TButton", command=lambda: self.open_cli_shell("codex")).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="GEMINI", style="Cli.TButton", command=lambda: self.open_cli_shell("gemini")).pack(side=tk.LEFT, padx=3)
        ttk.Button(actions, text="SCAN CLIs", style="Accent.TButton", command=self.open_cli_scanner).pack(side=tk.LEFT, padx=(6, 0))

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
        self.conversation_tree.column("#0", width=max(150, self._sidebar_width - 44), stretch=True)
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
            (self.overview_tab, "總覽"),
            (self.chat_tab, "對話"),
            (self.agents_tab, "任務"),
            (self.files_tab, "檔案"),
            (self.database_tab, "搜尋"),
            (self.terminal_tab, "CLI"),
            (self.models_tab, "模型"),
            (self.integrations_tab, "整合"),
            (self.automation_tab, "排程"),
            (self.draw_tab, "繪圖"),
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
        tab.grid_rowconfigure(2, weight=0, minsize=104)
        tab.grid_rowconfigure(3, weight=3, minsize=250)
        tab.grid_rowconfigure(4, weight=2, minsize=185)

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

        self._build_cli_usage_panel(tab)

        self._dashboard_canvases["trend"] = self._chart_card(
            tab, "CPU / MEMORY", "LIVE · LAST 2 MINUTES", row=3, column=0, columnspan=2
        )
        self._dashboard_canvases["tasks"] = self._chart_card(
            tab, "TASK STATUS", "RECENT ACTIVITY", row=4, column=0
        )
        self._dashboard_canvases["durations"] = self._chart_card(
            tab, "TASK DURATION", "LATEST COMPLETED", row=4, column=1
        )

    def _build_cli_usage_panel(self, parent: ttk.Frame) -> None:
        panel = tk.Frame(parent, bg=EDGE, padx=1, pady=1)
        panel.grid(row=2, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 9))
        body = ttk.Frame(panel, style="Panel.TFrame", padding=(12, 7))
        body.pack(fill=tk.BOTH, expand=True)
        for column in range(2):
            body.grid_columnconfigure(column, weight=1, uniform="cli_usage")

        codex = ttk.Frame(body, style="Panel.TFrame")
        codex.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        codex.grid_columnconfigure(0, weight=1)
        codex_header = ttk.Frame(codex, style="Panel.TFrame")
        codex_header.grid(row=0, column=0, sticky="ew")
        codex_header.grid_columnconfigure(0, weight=1)
        ttk.Label(codex_header, text="CODEX CLI  /  ACCOUNT LIMITS", style="ChartTitle.TLabel").grid(row=0, column=0, sticky="w")
        self._cli_usage_refresh_button = ttk.Button(
            codex_header, text="REFRESH", style="Ghost.TButton", command=self.refresh_cli_usage
        )
        self._cli_usage_refresh_button.grid(row=0, column=1, sticky="e")
        windows = ttk.Frame(codex, style="Panel.TFrame")
        windows.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        for column in range(2):
            windows.grid_columnconfigure(column, weight=1, uniform="codex_window")
        for column, key in enumerate(("primary", "secondary")):
            cell = ttk.Frame(windows, style="Panel.TFrame")
            cell.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 10, 4 if column == 0 else 0))
            cell.grid_columnconfigure(0, weight=1)
            title = tk.StringVar(value="5H  --" if column == 0 else "7D  --")
            value = tk.StringVar(value="--")
            reset = tk.StringVar(value="WAITING FOR CLI SNAPSHOT")
            ttk.Label(cell, textvariable=title, style="ChartMeta.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(cell, textvariable=value, style="Metric.TLabel").grid(row=0, column=1, sticky="e", padx=(5, 0))
            bar = ttk.Progressbar(cell, maximum=100, value=0, style="Quota.Horizontal.TProgressbar")
            bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 1))
            ttk.Label(cell, textvariable=reset, style="ChartMeta.TLabel").grid(row=2, column=0, columnspan=2, sticky="w")
            self._cli_usage_windows[key] = {"title": title, "value": value, "reset": reset, "bar": bar}
        self._cli_usage_checked_var = tk.StringVar(value="READ-ONLY · CODEX APP-SERVER")
        ttk.Label(codex, textvariable=self._cli_usage_checked_var, style="ChartMeta.TLabel").grid(row=2, column=0, sticky="w", pady=(2, 0))

        gemini = ttk.Frame(body, style="Panel.TFrame")
        gemini.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        gemini.grid_columnconfigure(0, weight=1)
        gemini.grid_columnconfigure(1, weight=0)
        ttk.Label(gemini, text="GEMINI CLI  /  MODEL QUOTA", style="ChartTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(
            gemini,
            text="OPEN  /stats model",
            style="Ghost.TButton",
            command=self.open_gemini_usage,
        ).grid(row=0, column=1, sticky="e")
        self._gemini_usage_hint_var = tk.StringVar(value="CLI 互動指令提供額度資料；請在視窗輸入 /stats model。")
        ttk.Label(
            gemini,
            textvariable=self._gemini_usage_hint_var,
            style="ChartMeta.TLabel",
            wraplength=440,
            justify=tk.LEFT,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(9, 0))

    def refresh_cli_usage(self) -> None:
        if self._cli_usage_query_running or self.closing:
            return
        if self._cli_usage_timer:
            try:
                self.root.after_cancel(self._cli_usage_timer)
            except tk.TclError:
                pass
            self._cli_usage_timer = None
        self._cli_usage_query_running = True
        if self._cli_usage_refresh_button and self._cli_usage_refresh_button.winfo_exists():
            self._cli_usage_refresh_button.configure(state=tk.DISABLED, text="QUERYING…")
        if self._cli_usage_checked_var:
            self._cli_usage_checked_var.set("QUERYING VIA CODEX APP-SERVER…")

        def work() -> dict[str, Any]:
            workdir = self._current_workdir()
            return query_codex_usage(self.app.paths, workdir)

        self._async(work, success=self._apply_cli_usage, failure=self._apply_cli_usage_error)

    def _apply_cli_usage(self, snapshot: dict[str, Any]) -> None:
        self._cli_usage_query_running = False
        for item in self._cli_usage_windows.values():
            item["title"].set("NO WINDOW DATA")
            item["value"].set("--")
            item["reset"].set("NOT RETURNED BY CODEX CLI")
            item["bar"].configure(value=0)
        for window in snapshot.get("windows", []):
            key = window.get("key")
            if key not in self._cli_usage_windows:
                continue
            item = self._cli_usage_windows[key]
            remaining = float(window["remaining_percent"])
            item["title"].set(f"{window['label']}  REMAINING")
            item["value"].set(f"{remaining:g}%")
            item["bar"].configure(value=remaining)
            reset_at = window.get("resets_at")
            if reset_at:
                reset_text = datetime.fromtimestamp(float(reset_at)).astimezone().strftime("%m/%d %H:%M")
                item["reset"].set(f"RESET  {reset_text}  ·  LOCAL TIME")
            else:
                item["reset"].set("RESET TIME NOT PROVIDED")
        if self._cli_usage_checked_var:
            self._cli_usage_checked_var.set(f"READ-ONLY · UPDATED {datetime.now().astimezone().strftime('%H:%M:%S')}")
        self._finish_cli_usage_refresh()

    def _apply_cli_usage_error(self, error: Exception) -> None:
        self._cli_usage_query_running = False
        for item in self._cli_usage_windows.values():
            item["title"].set("CODEX LIMITS")
            item["value"].set("--")
            item["reset"].set(str(error))
            item["bar"].configure(value=0)
        if self._cli_usage_checked_var:
            self._cli_usage_checked_var.set("NO VERIFIED CLI SNAPSHOT")
        self._finish_cli_usage_refresh()

    def _finish_cli_usage_refresh(self) -> None:
        if self._cli_usage_refresh_button and self._cli_usage_refresh_button.winfo_exists():
            self._cli_usage_refresh_button.configure(state=tk.NORMAL, text="REFRESH")
        if not self.closing:
            self._cli_usage_timer = self.root.after(300_000, self.refresh_cli_usage)

    def open_gemini_usage(self) -> None:
        self.open_cli_shell("gemini")
        self._set_status("GEMINI USAGE // 在新開啟的 Gemini CLI 輸入 /stats model 查詢剩餘額度")

    def open_cli_scanner(self) -> None:
        dialog = self._cli_scan_dialog
        if dialog and dialog.winfo_exists():
            dialog.deiconify()
            dialog.lift()
            return

        dialog = tk.Toplevel(self.root)
        self._cli_scan_dialog = dialog
        dialog.title("AI Hub · 本機 CLI 掃描")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        width = min(1180, max(820, screen_width - 100))
        height = min(700, max(520, screen_height - 120))
        dialog.geometry(f"{width}x{height}+{max(0, (screen_width-width)//2)}+{max(0, (screen_height-height)//2)}")
        dialog.minsize(760, 480)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(3, weight=1)
        dialog.protocol("WM_DELETE_WINDOW", self._close_cli_scanner)

        heading = ttk.Frame(dialog, style="TFrame", padding=(22, 18, 22, 8))
        heading.grid(row=0, column=0, sticky="ew")
        heading.grid_columnconfigure(0, weight=1)
        ttk.Label(heading, text="AI CLI INVENTORY", style="DashboardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(heading, text="掃描本機磁碟上的 CLI 啟動檔", style="DashboardSub.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

        actions = ttk.Frame(dialog, style="TFrame", padding=(22, 8, 22, 10))
        actions.grid(row=1, column=0, sticky="ew")
        self._cli_scan_button = ttk.Button(
            actions, text="掃描整台電腦", style="Accent.TButton", command=self._start_cli_scan
        )
        self._cli_scan_button.pack(side=tk.LEFT)
        self._cli_scan_cancel_button = ttk.Button(
            actions, text="取消掃描", style="Ghost.TButton", command=self._cancel_cli_scan, state=tk.DISABLED
        )
        self._cli_scan_cancel_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="關閉", style="Ghost.TButton", command=self._close_cli_scanner).pack(side=tk.RIGHT)

        scope = ttk.Label(
            dialog,
            text="掃描本機固定／卸除式磁碟及系統 PATH；略過網路磁碟、Windows 系統、暫存與大型套件快取。只讀啟動檔名稱和位置，不會執行找到的程式。",
            style="PanelMuted.TLabel",
            wraplength=1080,
            justify=tk.LEFT,
        )
        scope.configure(wraplength=max(680, width - 90))
        scope.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 12))

        results = tk.Frame(dialog, bg=EDGE, padx=1, pady=1)
        results.grid(row=3, column=0, sticky="nsew", padx=22, pady=(0, 10))
        results.grid_columnconfigure(0, weight=1)
        results.grid_rowconfigure(0, weight=1)
        columns = ("tool", "command", "path")
        self._cli_scan_tree = ttk.Treeview(results, columns=columns, show="headings", selectmode="browse")
        self._cli_scan_tree.heading("tool", text="AI CLI")
        self._cli_scan_tree.heading("command", text="COMMAND")
        self._cli_scan_tree.heading("path", text="LOCAL PATH")
        self._cli_scan_tree.column("tool", width=200, minwidth=140, stretch=False)
        self._cli_scan_tree.column("command", width=160, minwidth=120, stretch=False)
        self._cli_scan_tree.column("path", width=730, minwidth=360, stretch=True)
        self._cli_scan_tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(results, orient=tk.VERTICAL, command=self._cli_scan_tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(results, orient=tk.HORIZONTAL, command=self._cli_scan_tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self._cli_scan_tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)

        self._cli_scan_status = tk.StringVar(value="尚未開始 · 掃描會在背景執行，可隨時取消。")
        self._cli_scan_summary = tk.StringVar(value="尚無掃描結果")
        footer = ttk.Frame(dialog, style="TFrame", padding=(22, 0, 22, 16))
        footer.grid(row=4, column=0, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self._cli_scan_status, style="DashboardSub.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self._cli_scan_summary, style="DashboardLive.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._cli_scan_progress = ttk.Progressbar(footer, mode="indeterminate", length=190)
        self._cli_scan_progress.grid(row=0, column=1, rowspan=2, sticky="e", padx=(14, 0))

        if self._cli_scan_running:
            if self._cli_scan_button:
                self._cli_scan_button.configure(state=tk.DISABLED)
            if self._cli_scan_cancel_button:
                self._cli_scan_cancel_button.configure(state=tk.NORMAL)
            if self._cli_scan_progress:
                self._cli_scan_progress.start(12)

    def _start_cli_scan(self) -> None:
        if self._cli_scan_running or not self._cli_scan_dialog or not self._cli_scan_dialog.winfo_exists():
            return
        self._cli_scan_queue = queue.Queue()
        self._cli_scan_cancel = threading.Event()
        self._cli_scan_running = True
        if self._cli_scan_button:
            self._cli_scan_button.configure(state=tk.DISABLED, text="掃描中…")
        if self._cli_scan_cancel_button:
            self._cli_scan_cancel_button.configure(state=tk.NORMAL)
        if self._cli_scan_progress:
            self._cli_scan_progress.start(12)
        if self._cli_scan_status:
            self._cli_scan_status.set("正在列舉本機磁碟…")
        if self._cli_scan_summary:
            self._cli_scan_summary.set("掃描期間不會啟動 CLI 或連線網路")
        if self._cli_scan_tree:
            for item in self._cli_scan_tree.get_children():
                self._cli_scan_tree.delete(item)

        cancel_event = self._cli_scan_cancel

        def scan() -> None:
            try:
                snapshot = scan_local_ai_clis(
                    cancel_event=cancel_event,
                    progress=lambda update: self._cli_scan_queue.put(("progress", update)),
                )
            except Exception as error:
                self._cli_scan_queue.put(("error", error))
            else:
                self._cli_scan_queue.put(("done", snapshot))

        threading.Thread(target=scan, daemon=True, name="ai-hub-cli-discovery").start()
        self._schedule_cli_scan_poll()
        self._set_status("CLI SCAN // 本機磁碟只讀掃描已開始")

    def _schedule_cli_scan_poll(self) -> None:
        if self._cli_scan_poll_after or not self._cli_scan_running or self.closing:
            return
        try:
            self._cli_scan_poll_after = self.root.after(150, self._poll_cli_scan)
        except tk.TclError:
            self._cli_scan_poll_after = None
            if self._cli_scan_cancel:
                self._cli_scan_cancel.set()

    def _poll_cli_scan(self) -> None:
        self._cli_scan_poll_after = None
        while True:
            try:
                kind, payload = self._cli_scan_queue.get_nowait()
            except queue.Empty:
                break
            dialog_is_open = bool(self._cli_scan_dialog and self._cli_scan_dialog.winfo_exists())
            if kind == "progress" and dialog_is_open:
                elapsed = int(payload.get("elapsed", 0))
                drive = payload.get("drive") or "本機磁碟"
                if self._cli_scan_status:
                    self._cli_scan_status.set(
                        f"掃描 {drive}  ·  {payload.get('directories', 0):,} 個資料夾  ·  "
                        f"PATH {payload.get('path_directories', 0)}  ·  {elapsed}s"
                    )
                if self._cli_scan_summary:
                    self._cli_scan_summary.set(
                        f"已找到 {payload.get('found', 0)} 個啟動檔  ·  無法讀取 {payload.get('inaccessible', 0)} 處"
                    )
            elif kind == "done":
                self._finish_cli_scan(payload, dialog_is_open)
            elif kind == "error":
                self._finish_cli_scan_error(payload, dialog_is_open)
        self._schedule_cli_scan_poll()

    def _finish_cli_scan(self, snapshot: dict[str, Any], dialog_is_open: bool) -> None:
        self._cli_scan_running = False
        self._cli_scan_cancel = None
        if self._cli_scan_progress:
            self._cli_scan_progress.stop()
        if self._cli_scan_button:
            self._cli_scan_button.configure(state=tk.NORMAL, text="重新掃描")
        if self._cli_scan_cancel_button:
            self._cli_scan_cancel_button.configure(state=tk.DISABLED)

        results = snapshot.get("results", [])
        shown = results[:1000]
        if dialog_is_open and self._cli_scan_tree:
            for result in shown:
                self._cli_scan_tree.insert(
                    "",
                    tk.END,
                    values=(result["label"], result["command"], result["path"]),
                )
        drive_count = len(snapshot.get("roots", []))
        elapsed = int(snapshot.get("elapsed", 0))
        state = "已取消" if snapshot.get("cancelled") else "掃描完成"
        summary = (
            f"{state}  ·  {len(results)} 個 CLI 啟動檔  ·  {drive_count} 個磁碟  ·  "
            f"{snapshot.get('directories', 0):,} 個資料夾  ·  PATH {snapshot.get('path_directories', 0)}  ·  "
            f"無法讀取 {snapshot.get('inaccessible', 0)} 處  ·  {elapsed}s"
        )
        if len(results) > len(shown):
            summary += f"  ·  清單顯示前 {len(shown)} 筆"
        if dialog_is_open and self._cli_scan_summary:
            self._cli_scan_summary.set(summary)
            if self._cli_scan_status:
                self._cli_scan_status.set("掃描範圍：本機磁碟與系統 PATH；所有結果皆未執行。")
        self._set_status(f"CLI SCAN // {len(results)} 個啟動檔 · {drive_count} 個本機磁碟")

    def _finish_cli_scan_error(self, error: Exception, dialog_is_open: bool) -> None:
        self._cli_scan_running = False
        self._cli_scan_cancel = None
        if self._cli_scan_progress:
            self._cli_scan_progress.stop()
        if self._cli_scan_button:
            self._cli_scan_button.configure(state=tk.NORMAL, text="重新掃描")
        if self._cli_scan_cancel_button:
            self._cli_scan_cancel_button.configure(state=tk.DISABLED)
        if dialog_is_open and self._cli_scan_status:
            self._cli_scan_status.set(f"掃描失敗：{error}")
        self._set_status(f"CLI SCAN ERROR // {error}")

    def _cancel_cli_scan(self) -> None:
        if self._cli_scan_cancel:
            self._cli_scan_cancel.set()
            if self._cli_scan_cancel_button:
                self._cli_scan_cancel_button.configure(state=tk.DISABLED)
            if self._cli_scan_status:
                self._cli_scan_status.set("正在停止…目前磁碟資料夾處理完後會結束。")

    def _close_cli_scanner(self) -> None:
        if self._cli_scan_running:
            self._cancel_cli_scan()
        dialog, self._cli_scan_dialog = self._cli_scan_dialog, None
        if dialog and dialog.winfo_exists():
            dialog.destroy()

    def close(self) -> None:
        if self._cli_scan_cancel:
            self._cli_scan_cancel.set()
        super().close()

    def _chart_card(
        self, parent: ttk.Frame, title: str, meta: str, *, row: int, column: int, columnspan: int = 1
    ) -> tk.Canvas:
        frame = tk.Frame(parent, bg=EDGE, padx=1, pady=1)
        frame.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="nsew",
            padx=(14 if column == 0 else 5, 14 if columnspan > 1 or column == 1 else 5),
            pady=(0, 8 if row == 3 else 12),
        )
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        body = ttk.Frame(frame, style="Panel.TFrame")
        body.grid(row=0, column=0, rowspan=2, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)
        header = ttk.Frame(body, style="Panel.TFrame", padding=(16, 12, 16, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ttk.Label(header, text=title, style="ChartTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=meta, style="ChartMeta.TLabel").grid(row=0, column=1, sticky="e")
        canvas = tk.Canvas(body, bg=PANEL, highlightthickness=0, bd=0, height=230 if row == 3 else 190)
        canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))
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

    def _redraw_dashboard_chart(self, canvas: tk.Canvas | None) -> None:
        if canvas is None or not canvas.winfo_exists():
            return
        chart = next((name for name, item in self._dashboard_canvases.items() if item is canvas), "")
        if chart == "trend":
            self._draw_trend_chart(canvas)
        elif chart == "tasks":
            self._draw_task_chart(canvas)
        elif chart == "durations":
            self._draw_duration_chart(canvas)

    def _draw_trend_chart(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 240), max(canvas.winfo_height(), 145)
        left, right, top, bottom = 48, width - 18, 24, height - 32
        plot_height = bottom - top
        now = time.monotonic()
        for value in (0, 50, 100):
            y = bottom - plot_height * value / 100
            canvas.create_line(left, y, right, y, fill=EDGE, dash=(2, 4))
            canvas.create_text(left - 10, y, text=str(value), fill=MUTED, anchor="e", font=("Cascadia Mono", 9))
        for age in (120, 60, 0):
            x = left + (right - left) * (120 - age) / 120
            canvas.create_line(x, top, x, bottom, fill="#1B1C1E", dash=(1, 5))
            canvas.create_text(x, height - 8, text=f"-{age}s" if age else "NOW", fill=MUTED, anchor="s", font=("Cascadia Mono", 9))

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
                canvas.create_line(*points, fill=color, width=3, smooth=True, splinesteps=16)

        canvas.create_line(width - 174, 13, width - 155, 13, fill=CYAN, width=3)
        canvas.create_text(width - 148, 13, text="CPU", fill=TEXT, anchor="w", font=("Cascadia Mono", 9, "bold"))
        canvas.create_line(width - 96, 13, width - 77, 13, fill=GREEN, width=3)
        canvas.create_text(width - 70, 13, text="RAM", fill=TEXT, anchor="w", font=("Cascadia Mono", 9, "bold"))
        if len(self._cpu_history) < 2:
            canvas.create_text((left + right) / 2, (top + bottom) / 2, text="等待即時取樣…", fill=MUTED, font=("Cascadia Mono", 11))

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
        diameter = min(height - 24, 148)
        x0, y0 = 20, max(10, (height - diameter) / 2)
        bbox = (x0, y0, x0 + diameter, y0 + diameter)
        canvas.create_oval(*bbox, outline="#202124", width=16)
        if total:
            angle = 90
            for _label, count, color in counts:
                if not count:
                    continue
                extent = 360 * count / total
                canvas.create_arc(*bbox, start=angle, extent=-extent, style=tk.ARC, outline=color, width=16)
                angle -= extent
        canvas.create_text(x0 + diameter / 2, y0 + diameter / 2 - 5, text=str(total), fill=TEXT, font=("Cascadia Mono", 22, "bold"))
        canvas.create_text(x0 + diameter / 2, y0 + diameter / 2 + 19, text="TASKS", fill=MUTED, font=("Cascadia Mono", 9, "bold"))
        legend_x = x0 + diameter + 28
        legend_y = max(12, (height - len(counts) * 24) / 2)
        for index, (label, count, color) in enumerate(counts):
            y = legend_y + index * 24
            canvas.create_oval(legend_x, y - 5, legend_x + 9, y + 4, fill=color, outline="")
            canvas.create_text(legend_x + 17, y, text=label, fill=MUTED, anchor="w", font=("Cascadia Mono", 9, "bold"))
            canvas.create_text(width - 16, y, text=str(count), fill=TEXT, anchor="e", font=("Cascadia Mono", 10, "bold"))

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
            canvas.create_text(width / 2, height / 2, text="尚無已完成任務", fill=MUTED, font=("Cascadia Mono", 11))
            return
        left, right = 116, width - 55
        top = 14
        row_height = min(31, max(20, (height - 24) / len(rows)))
        max_duration = max(duration for _task, duration in rows) or 1.0
        for index, (task, duration) in enumerate(rows):
            y = top + index * row_height
            title = str(task.get("provider_id") or task.get("title") or "TASK")[:15]
            canvas.create_text(left - 10, y + 7, text=title, fill=MUTED, anchor="e", font=("Cascadia Mono", 9))
            canvas.create_rectangle(left, y, right, y + 13, fill="#202124", outline="")
            canvas.create_rectangle(left, y, left + max(3, (right - left) * duration / max_duration), y + 13, fill=GREEN, outline="")
            canvas.create_text(width - 8, y + 7, text=native.compact_seconds(duration), fill=TEXT, anchor="e", font=("Cascadia Mono", 9))
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
