from __future__ import annotations

"""Premium native operator-console skin for AI Hub.

The functional implementation stays in desktop.py.  This entry point replaces the
native window class with a polished local-only desktop surface and adds convenient
launchers for the bundled Codex/Gemini CLIs.  PyInstaller builds this file as the
main AIHub.exe entry point.
"""

import os
import subprocess
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import desktop as native


# Dark graphite + restrained neon accents.  The base implementation resolves these
# module globals at runtime, so existing functional tabs inherit the same palette.
PALETTE = {
    "BG": "#060A0F",
    "PANEL": "#0A1118",
    "PANEL_2": "#0E1721",
    "EDGE": "#1B2B38",
    "CYAN": "#35D6FF",
    "GREEN": "#43F59A",
    "PURPLE": "#A78BFA",
    "TEXT": "#E8F2F7",
    "MUTED": "#78909C",
    "WARN": "#FFB84D",
    "DANGER": "#FF5573",
    "INPUT_BG": "#081019",
    "SELECT_BG": "#12334A",
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
DEEP = "#02070B"
SIDEBAR = "#080E14"
HEADER = "#070D13"
HOVER = "#132432"

BaseDesktop = native.AIHubDesktop


class GeekDesktop(BaseDesktop):
    """Refined native-only operator deck with first-class local CLI access."""

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

        style.configure(
            "TButton",
            background="#101B25",
            foreground=TEXT,
            bordercolor=EDGE,
            focuscolor=CYAN,
            padding=(11, 7),
            font=("Microsoft JhengHei UI", 9),
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", HOVER), ("pressed", "#0C2736")],
            foreground=[("disabled", "#536570")],
            bordercolor=[("focus", CYAN), ("active", "#294357")],
        )
        style.configure("Ghost.TButton", background=HEADER, foreground=MUTED, bordercolor=EDGE, padding=(10, 6))
        style.map("Ghost.TButton", background=[("active", HOVER)], foreground=[("active", TEXT)])
        style.configure("Accent.TButton", background="#0C7691", foreground="#F5FDFF", bordercolor="#179FC1", padding=(12, 7))
        style.map("Accent.TButton", background=[("active", "#108DAA"), ("pressed", "#09657C")])
        style.configure("Green.TButton", background="#0C754A", foreground="#F2FFF8", bordercolor="#18A869", padding=(12, 7))
        style.map("Green.TButton", background=[("active", "#10925B"), ("pressed", "#08603D")])
        style.configure("Danger.TButton", background="#78273A", foreground="#FFF4F7", bordercolor="#A83B53", padding=(12, 7))
        style.map("Danger.TButton", background=[("active", "#933047")])
        style.configure("Cli.TButton", background="#102632", foreground=CYAN, bordercolor="#1A4D61", padding=(12, 7), font=("Cascadia Mono", 9, "bold"))
        style.map("Cli.TButton", background=[("active", "#163A49")], foreground=[("active", "#A8EEFF")])

        style.configure("TEntry", fieldbackground=INPUT_BG, foreground=TEXT, insertcolor=CYAN, bordercolor=EDGE, padding=8)
        style.map("TEntry", bordercolor=[("focus", CYAN)])
        style.configure("TCombobox", fieldbackground=INPUT_BG, background=INPUT_BG, foreground=TEXT, arrowcolor=CYAN, bordercolor=EDGE, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", INPUT_BG)], foreground=[("readonly", TEXT)], bordercolor=[("focus", CYAN)])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT, indicatorcolor="#12202B", padding=4)
        style.map("TCheckbutton", indicatorcolor=[("selected", GREEN)], foreground=[("disabled", MUTED)])
        style.configure("Sidebar.TCheckbutton", background=SIDEBAR, foreground=TEXT, indicatorcolor="#12202B", padding=4)
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
            background="#0C1620",
            foreground=CYAN,
            bordercolor=EDGE,
            font=("Cascadia Mono", 8, "bold"),
            padding=(5, 7),
        )
        style.map("Treeview", background=[("selected", SELECT_BG)], foreground=[("selected", "#E9FAFF")])
        style.map("Treeview.Heading", background=[("active", HOVER)])

        style.configure("TNotebook", background=BG, bordercolor=BG, tabmargins=(8, 8, 8, 0))
        style.configure(
            "TNotebook.Tab",
            background="#09111A",
            foreground=MUTED,
            bordercolor=EDGE,
            padding=(15, 9),
            font=("Cascadia Mono", 8, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL_2), ("active", "#101D28")],
            foreground=[("selected", CYAN), ("active", TEXT)],
            bordercolor=[("selected", "#28516A")],
        )
        style.configure("TProgressbar", troughcolor="#071018", background=GREEN, bordercolor=EDGE, lightcolor=GREEN, darkcolor=GREEN)
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
            bg="#10202C",
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

        self._build_chat_tab()
        BaseDesktop._build_agents_tab(self)
        BaseDesktop._build_files_tab(self)
        BaseDesktop._build_database_tab(self)
        self._build_terminal_tab()
        BaseDesktop._build_models_tab(self)
        BaseDesktop._build_integrations_tab(self)
        BaseDesktop._build_automation_tab(self)
        BaseDesktop._build_draw_tab(self)

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
