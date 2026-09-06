from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from ai_hub.application import AIHubApplication, ApprovalRequired
from ai_hub.security import FULL_ACCESS_PHRASE


BG = "#FFFFFF"
PANEL = "#FFFFFF"
PANEL_2 = "#F8FAFC"
EDGE = "#E2E8F0"
CYAN = "#2563EB"
GREEN = "#16A34A"
PURPLE = "#7C3AED"
TEXT = "#0F172A"
MUTED = "#64748B"
WARN = "#D97706"
DANGER = "#DC2626"
INPUT_BG = "#FFFFFF"
SELECT_BG = "#EFF6FF"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Hub native desktop control deck")
    parser.add_argument("--max-control", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def local_time(value: str | None, seconds: bool = False) -> str:
    if not value:
        return "--"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%m/%d %H:%M:%S" if seconds else "%m/%d %H:%M")
    except ValueError:
        return value[:16]


def compact_seconds(value: int | float | None) -> str:
    if value is None:
        return "--"
    seconds = max(0, int(value))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


class AIHubDesktop:
    def __init__(self, app: AIHubApplication, max_control: bool = False):
        self.app = app
        self.closing = False
        self.current_project_id: str | None = None
        self.current_conversation_id: str | None = None
        self.current_directory: str | None = None
        self.current_file: str | None = None
        self.selected_files: set[str] = set()
        self.provider_vars: dict[str, tk.BooleanVar] = {}
        self.provider_status: dict[str, dict[str, Any]] = {}
        self.project_labels: dict[str, str] = {}
        self.search_rows: dict[str, dict[str, Any]] = {}
        self.file_rows: dict[str, dict[str, Any]] = {}
        self.comfy_last_status: dict[str, Any] | None = None
        self.message_signature: tuple[Any, ...] | None = None
        self.task_signature: tuple[Any, ...] | None = None
        self.terminal_task_id: str | None = None
        self.terminal_last_event = 0
        self.terminal_final_signature: tuple[str, str | None, str | None] | None = None
        self._provider_refresh_running = False
        self._search_after: str | None = None
        self._tick = 0

        if max_control:
            # Consent is renewed on every process launch and lasts for that long-running session.
            self.app.unlock_full_access(FULL_ACCESS_PHRASE, minutes=525_600)
            self.app.update_settings(
                {
                    "permission_mode": "full",
                    "web_access": True,
                    "crawler_enabled": True,
                    "auto_peer_review": True,
                    "adaptive_performance": True,
                    "performance_memory_threshold": 90,
                }
            )
        self.app.start_background()

        self.root = tk.Tk()
        self.root.title("AI Hub · 本機多模型工作台")
        self.root.geometry("1540x930")
        self.root.minsize(1180, 720)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_styles()
        self._build_shell()
        self._bind_shortcuts()
        self._load_initial_state()
        self.root.after(500, self._refresh_loop)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=("Microsoft JhengHei UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Panel2.TFrame", background=PANEL_2)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=PANEL_2, foreground=MUTED)
        style.configure("HeaderMuted.TLabel", background=BG, foreground=MUTED)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Title.TLabel", background=BG, foreground=GREEN, font=("Cascadia Mono", 17, "bold"))
        style.configure("Metric.TLabel", background=PANEL_2, foreground=CYAN, font=("Cascadia Mono", 10, "bold"))
        style.configure("HeaderMetric.TLabel", background=BG, foreground=CYAN, font=("Cascadia Mono", 10, "bold"))
        style.configure(
            "TButton", background="#F8FAFC", foreground=TEXT, bordercolor=EDGE,
            focuscolor=CYAN, padding=(10, 7), font=("Microsoft JhengHei UI", 9),
        )
        style.map("TButton", background=[("active", "#EFF6FF"), ("pressed", "#E2E8F0")])
        style.configure("Accent.TButton", background=CYAN, foreground="#FFFFFF", bordercolor=CYAN)
        style.map("Accent.TButton", background=[("active", "#1D4ED8")], foreground=[("active", "#FFFFFF")])
        style.configure("Green.TButton", background=GREEN, foreground="#FFFFFF", bordercolor=GREEN)
        style.map("Green.TButton", background=[("active", "#15803D")], foreground=[("active", "#FFFFFF")])
        style.configure("Danger.TButton", background=DANGER, foreground="#FFFFFF", bordercolor=DANGER)
        style.map("Danger.TButton", background=[("active", "#B91C1C")], foreground=[("active", "#FFFFFF")])
        style.configure("TEntry", fieldbackground=INPUT_BG, foreground=TEXT, insertcolor=CYAN, bordercolor=EDGE, padding=7)
        style.configure("TCombobox", fieldbackground=INPUT_BG, background=INPUT_BG, foreground=TEXT, arrowcolor=CYAN, padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", INPUT_BG)], foreground=[("readonly", TEXT)])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT, indicatorcolor="#F8FAFC", padding=3)
        style.map("TCheckbutton", indicatorcolor=[("selected", CYAN)], foreground=[("disabled", MUTED)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, bordercolor=EDGE, rowheight=28)
        style.configure("Treeview.Heading", background=PANEL_2, foreground=CYAN, bordercolor=EDGE, font=("Cascadia Mono", 9, "bold"))
        style.map("Treeview", background=[("selected", SELECT_BG)], foreground=[("selected", CYAN)])
        style.map("Treeview.Heading", background=[("active", "#F1F5F9")])
        style.configure("TNotebook", background=BG, bordercolor=EDGE)
        style.configure("TNotebook.Tab", background=PANEL_2, foreground=MUTED, padding=(13, 8), font=("Cascadia Mono", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", CYAN), ("active", TEXT)])
        style.configure("TProgressbar", troughcolor=PANEL_2, background=GREEN, bordercolor=EDGE, lightcolor=GREEN, darkcolor=GREEN)
        style.configure("TLabelframe", background=PANEL, foreground=CYAN, bordercolor=EDGE)
        style.configure("TLabelframe.Label", background=PANEL, foreground=CYAN, font=("Cascadia Mono", 9, "bold"))
        self.root.option_add("*TCombobox*Listbox.background", INPUT_BG)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", SELECT_BG)
        self.root.option_add("*TCombobox*Listbox.selectForeground", CYAN)

    def _build_shell(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        self._build_header()
        content = tk.PanedWindow(
            self.root, orient=tk.HORIZONTAL, bg=EDGE, sashwidth=1, borderwidth=0,
            sashrelief=tk.FLAT,
        )
        content.grid(row=1, column=0, sticky="nsew")
        sidebar = ttk.Frame(content, style="Panel.TFrame", width=282)
        self.main = ttk.Frame(content)
        content.add(sidebar, minsize=250, width=282)
        content.add(self.main, minsize=850)
        self._build_sidebar(sidebar)
        self._build_workspace(self.main)
        self.status_var = tk.StringVar(value="正在初始化本機工作台…")
        status = tk.Label(
            self.root, textvariable=self.status_var, bg="#F8FAFC", fg=MUTED,
            anchor="w", padx=14, pady=5, font=("Cascadia Mono", 9),
        )
        status.grid(row=2, column=0, sticky="ew")

    def _build_header(self) -> None:
        header = ttk.Frame(self.root, padding=(18, 12, 16, 10))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ttk.Label(header, text="AI Hub", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header, text="本機多模型 AI 工作台  ·  原生 Windows 應用程式",
            style="HeaderMuted.TLabel", font=("Microsoft JhengHei UI", 9),
        ).grid(row=1, column=0, sticky="w")
        self.header_state = tk.StringVar(value="安全工作階段")
        ttk.Label(header, textvariable=self.header_state, style="HeaderMetric.TLabel").grid(
            row=0, column=1, rowspan=2, sticky="e", padx=(20, 0)
        )

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(3, weight=1)
        title = ttk.Frame(parent, style="Panel.TFrame", padding=(14, 13, 14, 7))
        title.grid(row=0, column=0, sticky="ew")
        title.grid_columnconfigure(0, weight=1)
        ttk.Label(title, text="專案範圍", style="Panel.TLabel", font=("Microsoft JhengHei UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(title, text="＋", width=3, command=self.add_project).grid(row=0, column=1)
        self.project_combo = ttk.Combobox(parent, state="readonly")
        self.project_combo.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))
        self.project_combo.bind("<<ComboboxSelected>>", self._select_project)

        chat_bar = ttk.Frame(parent, style="Panel.TFrame", padding=(14, 3, 14, 7))
        chat_bar.grid(row=2, column=0, sticky="ew")
        chat_bar.grid_columnconfigure(0, weight=1)
        ttk.Label(chat_bar, text="歷史對話", style="PanelMuted.TLabel", font=("Microsoft JhengHei UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(chat_bar, text="新增", command=self.new_conversation).grid(row=0, column=1)
        self.conversation_tree = ttk.Treeview(parent, show="tree", selectmode="browse")
        self.conversation_tree.grid(row=3, column=0, sticky="nsew", padx=10)
        self.conversation_tree.column("#0", width=246, stretch=True)
        self.conversation_tree.bind("<<TreeviewSelect>>", self._select_conversation)

        options = ttk.LabelFrame(parent, text="執行設定", style="TLabelframe", padding=8)
        options.grid(row=4, column=0, sticky="ew", padx=10, pady=10)
        options.grid_columnconfigure(0, weight=1)
        self.provider_frame = ttk.Frame(options, style="Panel.TFrame")
        self.provider_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.collaboration_var = tk.BooleanVar(value=True)
        self.web_var = tk.BooleanVar(value=bool(self.app.settings.get("web_access", True)))
        self.crawler_var = tk.BooleanVar(value=bool(self.app.settings.get("crawler_enabled", True)))
        self.review_var = tk.BooleanVar(value=bool(self.app.settings.get("auto_peer_review", True)))
        self.adaptive_var = tk.BooleanVar(value=bool(self.app.settings.get("adaptive_performance", False)))
        ttk.Checkbutton(options, text="多 Agent 協作編排", variable=self.collaboration_var).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(options, text="保留上網 / 搜尋", variable=self.web_var).grid(row=2, column=0, sticky="w")
        ttk.Checkbutton(options, text="AI 交叉監控與審查", variable=self.review_var).grid(row=3, column=0, sticky="w")
        ttk.Checkbutton(
            options,
            text="本機模型自動研究網址",
            variable=self.crawler_var,
            command=self.toggle_crawler,
        ).grid(row=4, column=0, sticky="w")
        ttk.Checkbutton(
            options,
            text="負載加速（AC + RAM ≥ 90%）",
            variable=self.adaptive_var,
            command=self.toggle_adaptive,
        ).grid(row=5, column=0, sticky="w")
        permission_row = ttk.Frame(options, style="Panel.TFrame")
        permission_row.grid(row=6, column=0, sticky="ew", pady=(5, 0))
        permission_row.grid_columnconfigure(1, weight=1)
        ttk.Label(permission_row, text="權限", style="PanelMuted.TLabel").grid(row=0, column=0, padx=(0, 7))
        self.permission_var = tk.StringVar(value="full" if self.app.full_access_unlocked() else "workspace")
        permission = ttk.Combobox(
            permission_row, textvariable=self.permission_var,
            values=("full", "workspace", "observe"), state="readonly", width=12,
        )
        permission.grid(row=0, column=1, sticky="ew")

    def _build_workspace(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        self.tabs = ttk.Notebook(parent)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=(1, 0))
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
            (self.chat_tab, "對話"), (self.agents_tab, "執行進度"), (self.files_tab, "檔案"),
            (self.database_tab, "快速查詢"), (self.terminal_tab, "終端機"),
            (self.models_tab, "模型與訓練"), (self.integrations_tab, "整合"),
            (self.automation_tab, "自動工作"), (self.draw_tab, "繪圖"),
        ):
            self.tabs.add(frame, text=label)
        self._build_chat_tab()
        self._build_agents_tab()
        self._build_files_tab()
        self._build_database_tab()
        self._build_terminal_tab()
        self._build_models_tab()
        self._build_integrations_tab()
        self._build_automation_tab()
        self._build_draw_tab()

    def _mono_text(self, parent: tk.Misc, **kwargs: Any) -> ScrolledText:
        return ScrolledText(
            parent, bg=INPUT_BG, fg=TEXT, insertbackground=CYAN, selectbackground=SELECT_BG,
            relief=tk.FLAT, borderwidth=0, font=("Cascadia Mono", 10), padx=12, pady=10,
            wrap=tk.WORD, undo=True, **kwargs,
        )

    def _build_chat_tab(self) -> None:
        tab = self.chat_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        summary = ttk.Frame(tab, style="Panel2.TFrame", padding=(13, 9))
        summary.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        summary.grid_columnconfigure(1, weight=1)
        self.feasibility_score = tk.StringVar(value="成功性前檢 · 等待工作")
        self.feasibility_detail = tk.StringVar(value="輸入工作後，先估算成功率、可信度與時間")
        ttk.Label(summary, textvariable=self.feasibility_score, style="Metric.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(summary, textvariable=self.feasibility_detail, style="Muted.TLabel").grid(row=0, column=1, sticky="e")

        self.chat_text = self._mono_text(tab)
        self.chat_text.grid(row=1, column=0, sticky="nsew", padx=10)
        self.chat_text.configure(state=tk.DISABLED)
        self.chat_text.tag_configure("user_header", foreground=CYAN, font=("Cascadia Mono", 9, "bold"), spacing1=10)
        self.chat_text.tag_configure("assistant_header", foreground=GREEN, font=("Cascadia Mono", 9, "bold"), spacing1=10)
        self.chat_text.tag_configure("system_header", foreground=WARN, font=("Cascadia Mono", 9, "bold"), spacing1=10)
        self.chat_text.tag_configure("body", foreground=TEXT, lmargin1=8, lmargin2=8, spacing3=7)

        composer = ttk.Frame(tab, style="Panel2.TFrame", padding=10)
        composer.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 10))
        composer.grid_columnconfigure(0, weight=1)
        self.context_var = tk.StringVar(value="尚未選取檔案範圍")
        ttk.Label(composer, textvariable=self.context_var, style="Muted.TLabel", font=("Cascadia Mono", 8)).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.prompt_text = tk.Text(
            composer, height=5, bg=INPUT_BG, fg=TEXT, insertbackground=CYAN,
            selectbackground=SELECT_BG, relief=tk.FLAT, borderwidth=1, highlightthickness=1,
            highlightbackground=EDGE, highlightcolor=CYAN,
            font=("Cascadia Mono", 10), padx=10, pady=8, wrap=tk.WORD, undo=True,
        )
        self.prompt_text.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        action = ttk.Frame(composer, style="Panel2.TFrame")
        action.grid(row=1, column=1, sticky="ns")
        ttk.Button(action, text="開始  Ctrl+Enter", style="Green.TButton", command=self.send_prompt).pack(fill=tk.X)
        ttk.Button(action, text="停止", style="Danger.TButton", command=self.stop_latest_task).pack(fill=tk.X, pady=(6, 0))
        self.prompt_text.bind("<Control-Return>", lambda _event: self.send_prompt() or "break")

    def _build_agents_tab(self) -> None:
        tab = self.agents_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=3)
        tab.grid_rowconfigure(1, weight=2)
        columns = ("provider", "title", "status", "stage", "progress", "eta", "end")
        self.task_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="browse")
        headings = {
            "provider": "AI / AGENT", "title": "WORK", "status": "STATE", "stage": "STAGE",
            "progress": "%", "eta": "ETA", "end": "END",
        }
        widths = {"provider": 125, "title": 225, "status": 90, "stage": 210, "progress": 55, "eta": 80, "end": 110}
        for key in columns:
            self.task_tree.heading(key, text=headings[key])
            self.task_tree.column(key, width=widths[key], stretch=key in {"title", "stage"})
        self.task_tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))
        self.task_tree.bind("<<TreeviewSelect>>", self._show_task_details)
        self.task_tree.tag_configure("completed", foreground=GREEN)
        self.task_tree.tag_configure("failed", foreground=DANGER)
        self.task_tree.tag_configure("running", foreground=CYAN)
        self.task_tree.tag_configure("queued", foreground=WARN)

        lower = ttk.Frame(tab, style="Panel2.TFrame", padding=8)
        lower.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 10))
        lower.grid_columnconfigure(0, weight=1)
        lower.grid_rowconfigure(1, weight=1)
        controls = ttk.Frame(lower, style="Panel2.TFrame")
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.task_detail_var = tk.StringVar(value="SELECT AN AGENT TASK")
        ttk.Label(controls, textvariable=self.task_detail_var, style="Metric.TLabel").pack(side=tk.LEFT)
        ttk.Button(controls, text="STOP", style="Danger.TButton", command=self.stop_selected_task).pack(side=tk.RIGHT)
        ttk.Button(controls, text="✕ 驗證失敗", command=lambda: self.rate_task(False)).pack(side=tk.RIGHT, padx=5)
        ttk.Button(controls, text="✓ 驗證成功", command=lambda: self.rate_task(True)).pack(side=tk.RIGHT)
        self.task_event_text = self._mono_text(lower, height=12)
        self.task_event_text.grid(row=1, column=0, sticky="nsew")
        self.task_event_text.configure(state=tk.DISABLED)

    def _build_files_tab(self) -> None:
        tab = self.files_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        bar = ttk.Frame(tab, style="Panel2.TFrame", padding=9)
        bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        bar.grid_columnconfigure(1, weight=1)
        ttk.Button(bar, text="↑", width=3, command=self.file_up).grid(row=0, column=0, padx=(0, 6))
        self.file_path_var = tk.StringVar()
        path_entry = ttk.Entry(bar, textvariable=self.file_path_var)
        path_entry.grid(row=0, column=1, sticky="ew")
        path_entry.bind("<Return>", lambda _event: self.load_files(self.file_path_var.get()))
        ttk.Button(bar, text="重新整理", command=lambda: self.load_files()).grid(row=0, column=2, padx=6)
        ttk.Button(bar, text="檔案總管", command=self.open_in_explorer).grid(row=0, column=3)
        self.download_url_var = tk.StringVar()
        ttk.Label(bar, text="下載網址", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(bar, textvariable=self.download_url_var).grid(row=1, column=1, sticky="ew", pady=(8, 0))
        transfer_actions = ttk.Frame(bar, style="Panel2.TFrame")
        transfer_actions.grid(row=1, column=2, columnspan=2, sticky="e", padx=(6, 0), pady=(8, 0))
        ttk.Button(transfer_actions, text="下載", style="Accent.TButton", command=self.download_from_url).pack(side=tk.LEFT)
        ttk.Button(transfer_actions, text="匯入", command=self.import_external_file).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(transfer_actions, text="匯出", command=self.export_selected_file).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(transfer_actions, text="Bluetooth", command=self.open_bluetooth_transfer).pack(side=tk.LEFT, padx=(5, 0))

        panes = tk.PanedWindow(tab, orient=tk.HORIZONTAL, bg=EDGE, sashwidth=1, borderwidth=0)
        panes.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 10))
        left = ttk.Frame(panes, style="Panel.TFrame")
        right = ttk.Frame(panes, style="Panel2.TFrame")
        panes.add(left, minsize=330, width=440)
        panes.add(right, minsize=430)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=1)
        self.file_tree = ttk.Treeview(left, columns=("size", "modified"), show="tree headings", selectmode="browse")
        self.file_tree.heading("#0", text="NAME")
        self.file_tree.heading("size", text="SIZE")
        self.file_tree.heading("modified", text="MODIFIED")
        self.file_tree.column("#0", width=245, stretch=True)
        self.file_tree.column("size", width=90, anchor="e")
        self.file_tree.column("modified", width=135)
        self.file_tree.grid(row=0, column=0, sticky="nsew")
        self.file_tree.bind("<Double-1>", self._open_file_tree_item)
        self.file_tree.bind("<<TreeviewSelect>>", self._preview_file_tree_item)
        file_actions = ttk.Frame(left, style="Panel.TFrame", padding=(0, 7, 0, 0))
        file_actions.grid(row=1, column=0, sticky="ew")
        ttk.Button(file_actions, text="＋ ADD TO AI CONTEXT", style="Accent.TButton", command=self.add_selected_file).pack(side=tk.LEFT)
        ttk.Button(file_actions, text="REMOVE CONTEXT", command=self.remove_selected_file).pack(side=tk.LEFT, padx=6)

        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        self.file_info_var = tk.StringVar(value="選取檔案即可預覽")
        ttk.Label(right, textvariable=self.file_info_var, style="Metric.TLabel").grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        self.file_editor = self._mono_text(right)
        self.file_editor.grid(row=1, column=0, sticky="nsew")
        editor_actions = ttk.Frame(right, style="Panel2.TFrame", padding=8)
        editor_actions.grid(row=2, column=0, sticky="ew")
        ttk.Button(editor_actions, text="SAVE WITH APPROVAL", style="Green.TButton", command=self.save_current_file).pack(side=tk.RIGHT)

    def _build_database_tab(self) -> None:
        tab = self.database_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=3)
        tab.grid_rowconfigure(2, weight=2)
        bar = ttk.Frame(tab, style="Panel2.TFrame", padding=10)
        bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        bar.grid_columnconfigure(0, weight=1)
        self.search_var = tk.StringVar()
        search = ttk.Entry(bar, textvariable=self.search_var, font=("Cascadia Mono", 11))
        search.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        search.bind("<Return>", lambda _event: self.run_global_search())
        search.bind("<KeyRelease>", self._queue_search)
        self.search_entry = search
        ttk.Button(bar, text="QUERY FTS5", style="Accent.TButton", command=self.run_global_search).grid(row=0, column=1)
        self.search_stats_var = tk.StringVar(value="LOCAL INDEX // projects · chats · tasks · research · audit")
        ttk.Label(bar, textvariable=self.search_stats_var, style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(7, 0))
        crawler_row = ttk.Frame(bar, style="Panel2.TFrame")
        crawler_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        crawler_row.grid_columnconfigure(1, weight=1)
        ttk.Label(crawler_row, text="公開網址研究", style="Muted.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 7))
        self.crawler_url_var = tk.StringVar()
        ttk.Entry(crawler_row, textvariable=self.crawler_url_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(crawler_row, text="擷取並加入索引", style="Accent.TButton", command=self.crawl_public_url).grid(row=0, column=2, padx=(7, 0))

        self.search_tree = ttk.Treeview(tab, columns=("kind", "title", "updated"), show="headings", selectmode="browse")
        for key, title, width in (("kind", "TYPE", 110), ("title", "MATCH", 600), ("updated", "UPDATED", 150)):
            self.search_tree.heading(key, text=title)
            self.search_tree.column(key, width=width, stretch=key == "title")
        self.search_tree.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.search_tree.bind("<<TreeviewSelect>>", self._show_search_result)
        self.search_tree.bind("<Double-1>", self._open_search_result)
        self.search_preview = self._mono_text(tab, height=12)
        self.search_preview.grid(row=2, column=0, sticky="nsew", padx=10, pady=(5, 10))
        self.search_preview.configure(state=tk.DISABLED)

    def _build_terminal_tab(self) -> None:
        tab = self.terminal_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)
        quick = ttk.Frame(tab, style="Panel2.TFrame", padding=9)
        quick.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        ttk.Label(quick, text="開發工具", style="Metric.TLabel").pack(side=tk.LEFT, padx=(0, 9))
        for label, command in (
            ("測試", "python -m unittest discover -v"),
            ("檔案", "Get-ChildItem -Force"),
            ("GIT", "git status --short"),
            ("環境", "Get-Command python,node,git,codex,gemini,ollama -ErrorAction SilentlyContinue | Select-Object Name,Source"),
        ):
            ttk.Button(quick, text=label, command=lambda value=command: self.set_terminal_command(value)).pack(side=tk.LEFT, padx=3)
        ttk.Button(quick, text="開啟本機程式", command=self.launch_local_app).pack(side=tk.RIGHT)
        ttk.Button(quick, text="VS Code", command=lambda: self.set_terminal_command("code .")).pack(side=tk.RIGHT, padx=5)

        command_box = ttk.Frame(tab, style="Panel2.TFrame", padding=9)
        command_box.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        command_box.grid_columnconfigure(0, weight=1)
        self.terminal_command = tk.Text(
            command_box, height=4, bg=INPUT_BG, fg=TEXT, insertbackground=CYAN,
            relief=tk.FLAT, borderwidth=1, highlightthickness=1, highlightbackground=EDGE,
            highlightcolor=CYAN, font=("Cascadia Mono", 10), padx=9, pady=8,
        )
        self.terminal_command.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.terminal_command.bind("<Control-Return>", lambda _event: self.run_terminal() or "break")
        ttk.Button(command_box, text="執行  Ctrl+Enter", style="Green.TButton", command=self.run_terminal).grid(row=0, column=1, sticky="ns")
        self.terminal_output = self._mono_text(tab)
        self.terminal_output.grid(row=2, column=0, sticky="nsew", padx=10, pady=(5, 10))
        self.terminal_output.configure(state=tk.DISABLED)

    def _build_models_tab(self) -> None:
        tab = self.models_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=3)
        tab.grid_rowconfigure(2, weight=1)
        top = ttk.Frame(tab, style="Panel2.TFrame", padding=10)
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        top.grid_columnconfigure(0, weight=1)
        self.model_readiness_var = tk.StringVar(value="正在檢查模型硬體條件…")
        ttk.Label(top, textvariable=self.model_readiness_var, style="Metric.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(top, text="官方來源", command=self.open_model_source).grid(row=0, column=1, padx=5)
        ttk.Button(top, text="重新檢查", command=self.refresh_models).grid(row=0, column=2, padx=5)
        ttk.Button(top, text="下載選取模型", style="Green.TButton", command=self.download_model).grid(row=0, column=3)
        columns = ("family", "model", "params", "runtime", "state", "disk", "notes")
        self.model_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="browse")
        settings = (
            ("family", "FAMILY", 90), ("model", "MODEL", 280), ("params", "SIZE", 70),
            ("runtime", "RUNTIME", 130), ("state", "READINESS", 105), ("disk", "DISK", 70),
            ("notes", "NOTES", 410),
        )
        for key, title, width in settings:
            self.model_tree.heading(key, text=title)
            self.model_tree.column(key, width=width, stretch=key in {"model", "notes"})
        self.model_tree.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 5))
        self.model_tree.tag_configure("ready", foreground=GREEN)
        self.model_tree.tag_configure("downloaded", foreground=PURPLE)
        self.model_tree.tag_configure("available", foreground=CYAN)
        self.model_tree.tag_configure("remote", foreground=WARN)
        self.model_tree.tag_configure("blocked", foreground=DANGER)

        training = ttk.LabelFrame(tab, text="QLoRA 真實訓練", style="TLabelframe", padding=10)
        training.grid(row=2, column=0, sticky="nsew", padx=10, pady=(5, 10))
        training.grid_columnconfigure(1, weight=1)
        training.grid_columnconfigure(4, weight=1)
        self.training_dataset_var = tk.StringVar()
        self.training_output_var = tk.StringVar()
        self.training_epochs_var = tk.StringVar(value="1.0")
        self.training_rank_var = tk.StringVar(value="16")
        self.training_status_var = tk.StringVar(
            value="先選擇文字模型與 JSONL 資料集；未通過 CUDA / VRAM / RAM / 磁碟前檢時不會假裝訓練。"
        )
        ttk.Label(training, text="JSONL 資料集", style="PanelMuted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(training, textvariable=self.training_dataset_var).grid(row=0, column=1, sticky="ew", padx=(7, 5))
        ttk.Button(training, text="選擇", command=self.pick_training_dataset).grid(row=0, column=2, padx=(0, 12))
        ttk.Label(training, text="輸出資料夾", style="PanelMuted.TLabel").grid(row=0, column=3, sticky="w")
        ttk.Entry(training, textvariable=self.training_output_var).grid(row=0, column=4, sticky="ew", padx=(7, 5))
        ttk.Button(training, text="選擇", command=self.pick_training_output).grid(row=0, column=5)
        ttk.Label(training, text="Epochs", style="PanelMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(training, textvariable=self.training_epochs_var, width=8).grid(row=1, column=1, sticky="w", padx=(7, 0), pady=(8, 0))
        ttk.Label(training, text="LoRA rank", style="PanelMuted.TLabel").grid(row=1, column=2, sticky="e", padx=(8, 7), pady=(8, 0))
        ttk.Entry(training, textvariable=self.training_rank_var, width=8).grid(row=1, column=3, sticky="w", pady=(8, 0))
        ttk.Button(training, text="硬體與資料前檢", style="Accent.TButton", command=self.training_preflight).grid(row=1, column=4, sticky="e", padx=(8, 5), pady=(8, 0))
        ttk.Button(training, text="開始 QLoRA", style="Green.TButton", command=self.start_training).grid(row=1, column=5, sticky="e", pady=(8, 0))
        ttk.Label(training, textvariable=self.training_status_var, style="PanelMuted.TLabel", wraplength=1050).grid(
            row=2, column=0, columnspan=6, sticky="ew", pady=(9, 0)
        )

    def _build_integrations_tab(self) -> None:
        tab = self.integrations_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=0)
        tab.grid_rowconfigure(2, weight=1)
        status_frame = ttk.Frame(tab, style="Panel2.TFrame", padding=9)
        status_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))
        status_frame.grid_columnconfigure(0, weight=1)
        status_frame.grid_rowconfigure(0, weight=1)
        self.integration_tree = ttk.Treeview(
            status_frame, columns=("name", "kind", "state", "detail"), show="headings",
            selectmode="browse", height=6,
        )
        for key, title, width in (
            ("name", "INTEGRATION", 190), ("kind", "TYPE", 90),
            ("state", "STATE", 120), ("detail", "DETAIL", 650),
        ):
            self.integration_tree.heading(key, text=title)
            self.integration_tree.column(key, width=width, stretch=key == "detail")
        self.integration_tree.grid(row=0, column=0, columnspan=4, sticky="nsew")
        self.integration_tree.tag_configure("online", foreground=GREEN)
        self.integration_tree.tag_configure("setup", foreground=WARN)
        ttk.Button(status_frame, text="重新檢查", command=lambda: self.refresh_providers(True)).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(status_frame, text="安裝 / 更新 CLI (Codex · Gemini)", command=self.install_clis).grid(row=1, column=1, padx=5, pady=(8, 0))
        ttk.Button(status_frame, text="Codex 登入", command=lambda: self.open_cli_login("codex")).grid(row=1, column=2, padx=5, pady=(8, 0))
        ttk.Button(status_frame, text="Gemini 登入", style="Accent.TButton", command=lambda: self.open_cli_login("gemini")).grid(row=1, column=3, pady=(8, 0))

        ops = ttk.LabelFrame(tab, text="Operator 整合與發布", style="TLabelframe", padding=10)
        ops.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        ops.grid_columnconfigure(0, weight=1)
        self.resource_policy_var = tk.StringVar(value="RESOURCE GOVERNOR // probing")
        ttk.Label(ops, textvariable=self.resource_policy_var, style="PanelMuted.TLabel").grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 8))
        ttk.Button(ops, text="同步 Kimi / DeepSeek", style="Accent.TButton", command=self.sync_official_models).grid(row=1, column=0, sticky="w")
        ttk.Button(ops, text="Google Play", command=self.publish_google_play).grid(row=1, column=1, padx=5)
        ttk.Button(ops, text="Google Sites", command=self.open_google_sites).grid(row=1, column=2, padx=5)
        ttk.Button(ops, text="立即維護", command=self.run_maintenance_now).grid(row=1, column=3, padx=5)
        ttk.Button(ops, text="重新檢查", command=lambda: self.refresh_providers(True)).grid(row=1, column=4, sticky="e")

        config = ttk.Frame(tab, style="Panel2.TFrame", padding=12)
        config.grid(row=2, column=0, sticky="nsew", padx=10, pady=(5, 10))
        config.grid_columnconfigure(1, weight=1)
        config.grid_columnconfigure(3, weight=1)
        ttk.Label(config, text="開源推論節點與繪圖服務設定", style="Metric.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 9))
        provider_config = self.app.settings.get("provider_config", {})
        compatible = provider_config.get("compatible", {})
        comfyui = provider_config.get("comfyui", {})
        self.compatible_url = tk.StringVar(value=compatible.get("base_url", "http://127.0.0.1:8000/v1"))
        self.compatible_model = tk.StringVar(value=compatible.get("model", ""))
        self.compatible_env = tk.StringVar(value=compatible.get("api_key_env", "AI_HUB_API_KEY"))
        self.comfy_url = tk.StringVar(value=comfyui.get("base_url", "http://127.0.0.1:8188"))
        self.comfy_checkpoint = tk.StringVar(value=comfyui.get("checkpoint", ""))
        fields = (
            ("Compatible 端點 URL", self.compatible_url, 1, 0),
            ("Compatible 模型名稱", self.compatible_model, 1, 2),
            ("Compatible 金鑰變數", self.compatible_env, 2, 0),
            ("ComfyUI 繪圖 URL", self.comfy_url, 3, 0),
            ("繪圖 Checkpoint", self.comfy_checkpoint, 3, 2),
        )
        for label, variable, row, column in fields:
            ttk.Label(config, text=label, style="Muted.TLabel").grid(row=row, column=column, sticky="w", padx=(0, 7), pady=5)
            ttk.Entry(config, textvariable=variable).grid(row=row, column=column + 1, sticky="ew", padx=(0, 14), pady=5)
        ttk.Label(
            config,
            text="Codex 與 Gemini 使用本機官方 CLI；開源節點支援 vLLM / SGLang / llama.cpp 等相容端點。",
            style="Muted.TLabel",
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(12, 0))
        ttk.Button(config, text="儲存並重新載入", style="Green.TButton", command=self.save_integrations).grid(row=4, column=3, sticky="e", pady=(12, 0))

    def _build_automation_tab(self) -> None:
        tab = self.automation_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        columns = ("name", "window", "interval", "duration", "mode", "enabled", "last")
        self.schedule_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="browse")
        for key, title, width in (
            ("name", "SCHEDULE", 220), ("window", "WINDOW", 130), ("interval", "EVERY", 90),
            ("duration", "LIMIT", 90), ("mode", "MODE", 100), ("enabled", "STATE", 90),
            ("last", "LAST RUN", 150),
        ):
            self.schedule_tree.heading(key, text=title)
            self.schedule_tree.column(key, width=width, stretch=key == "name")
        self.schedule_tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))

        form = ttk.Frame(tab, style="Panel2.TFrame", padding=11)
        form.grid(row=1, column=0, sticky="ew", padx=10, pady=(5, 10))
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(5, weight=1)
        self.schedule_name = tk.StringVar(value="每日小範圍改善")
        self.schedule_window_start = tk.StringVar(value="00:00")
        self.schedule_window_end = tk.StringVar(value="23:59")
        self.schedule_interval = tk.StringVar(value="1440")
        self.schedule_duration = tk.StringVar(value="60")
        self.schedule_mode = tk.StringVar(value="improve")
        ttk.Label(form, text="NAME", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.schedule_name).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(7, 14))
        ttk.Label(form, text="MODE", style="Muted.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Combobox(form, textvariable=self.schedule_mode, values=("improve", "image"), state="readonly", width=12).grid(row=0, column=5, sticky="ew", padx=(7, 0))
        ttk.Label(form, text="START", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=7)
        ttk.Entry(form, textvariable=self.schedule_window_start, width=9).grid(row=1, column=1, sticky="w", padx=(7, 14))
        ttk.Label(form, text="END", style="Muted.TLabel").grid(row=1, column=2, sticky="w")
        ttk.Entry(form, textvariable=self.schedule_window_end, width=9).grid(row=1, column=3, sticky="w", padx=(7, 14))
        ttk.Label(form, text="INTERVAL MIN", style="Muted.TLabel").grid(row=1, column=4, sticky="w")
        ttk.Entry(form, textvariable=self.schedule_interval, width=8).grid(row=1, column=5, sticky="w", padx=(7, 0))
        ttk.Label(form, text="DURATION MIN", style="Muted.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.schedule_duration, width=9).grid(row=2, column=1, sticky="w", padx=(7, 14))
        ttk.Label(form, text="PROMPT", style="Muted.TLabel").grid(row=3, column=0, sticky="nw", pady=(8, 0))
        self.schedule_prompt = tk.Text(
            form, height=4, bg=INPUT_BG, fg=TEXT, insertbackground=CYAN,
            relief=tk.FLAT, borderwidth=1, highlightthickness=1, highlightbackground=EDGE,
            highlightcolor=CYAN, font=("Cascadia Mono", 9), padx=8, pady=6, wrap=tk.WORD,
        )
        self.schedule_prompt.insert("1.0", "檢查目前專案，找出一項高價值且小範圍的改善，保留原始意圖，修改後執行測試。")
        self.schedule_prompt.grid(row=3, column=1, columnspan=5, sticky="ew", padx=(7, 0), pady=(8, 0))
        controls = ttk.Frame(form, style="Panel2.TFrame")
        controls.grid(row=4, column=0, columnspan=6, sticky="ew", pady=(9, 0))
        ttk.Label(controls, text="全天候工作需讓 AI Hub 保持開啟；每次工作受 duration 硬上限控制。", style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Button(controls, text="DELETE", style="Danger.TButton", command=self.delete_schedule).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(controls, text="CREATE SCHEDULE", style="Green.TButton", command=self.create_schedule).pack(side=tk.RIGHT)

    def _build_draw_tab(self) -> None:
        tab = self.draw_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        status = ttk.Frame(tab, style="Panel2.TFrame", padding=10)
        status.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        status.grid_columnconfigure(0, weight=1)
        self.comfy_status_var = tk.StringVar(value="COMFYUI // not probed")
        ttk.Label(status, textvariable=self.comfy_status_var, style="Metric.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(status, text="PROBE", command=self.refresh_comfy).grid(row=0, column=1)

        form = ttk.Frame(tab, style="Panel2.TFrame", padding=12)
        form.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 10))
        form.grid_columnconfigure(1, weight=1)
        form.grid_rowconfigure(1, weight=1)
        ttk.Label(form, text="PROMPT", style="Muted.TLabel").grid(row=0, column=0, sticky="nw", padx=(0, 9))
        self.image_prompt = self._mono_text(form, height=10)
        self.image_prompt.grid(row=0, column=1, columnspan=5, sticky="nsew")
        ttk.Label(form, text="NEGATIVE", style="Muted.TLabel").grid(row=1, column=0, sticky="nw", padx=(0, 9), pady=(9, 0))
        self.image_negative = self._mono_text(form, height=5)
        self.image_negative.insert("1.0", "low quality, blurry, distorted, watermark")
        self.image_negative.grid(row=1, column=1, columnspan=5, sticky="nsew", pady=(9, 0))
        self.image_width = tk.StringVar(value="768")
        self.image_height = tk.StringVar(value="768")
        self.image_steps = tk.StringVar(value="24")
        self.image_seed = tk.StringVar(value="")
        self.image_checkpoint = tk.StringVar(value=self.comfy_checkpoint.get())
        inputs = (
            ("WIDTH", self.image_width, 0), ("HEIGHT", self.image_height, 1),
            ("STEPS", self.image_steps, 2), ("SEED", self.image_seed, 3),
        )
        for label, variable, column in inputs:
            box = ttk.Frame(form, style="Panel2.TFrame")
            box.grid(row=2, column=column + 1, sticky="ew", padx=(0, 7), pady=10)
            ttk.Label(box, text=label, style="Muted.TLabel").pack(anchor="w")
            ttk.Entry(box, textvariable=variable, width=12).pack(fill=tk.X)
        checkpoint_box = ttk.Frame(form, style="Panel2.TFrame")
        checkpoint_box.grid(row=3, column=1, columnspan=4, sticky="ew", padx=(0, 7))
        ttk.Label(checkpoint_box, text="CHECKPOINT", style="Muted.TLabel").pack(anchor="w")
        self.checkpoint_combo = ttk.Combobox(checkpoint_box, textvariable=self.image_checkpoint)
        self.checkpoint_combo.pack(fill=tk.X)
        ttk.Button(form, text="GENERATE", style="Green.TButton", command=self.generate_image).grid(row=3, column=5, sticky="nsew")
        ttk.Label(
            form,
            text="Use AUTOMATION mode=image for continuous drawing inside a selected time window.",
            style="Muted.TLabel",
        ).grid(row=4, column=1, columnspan=5, sticky="w", pady=(12, 0))

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-n>", lambda _event: self.new_conversation())
        self.root.bind("<Control-k>", self._focus_search)
        self.root.bind("<F5>", lambda _event: self.force_refresh())

    def _focus_search(self, _event: tk.Event | None = None) -> str:
        self.tabs.select(self.database_tab)
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, tk.END)
        return "break"

    def _load_initial_state(self) -> None:
        self._reload_projects()
        self.refresh_providers(True)
        self.refresh_models()
        self.reload_schedules()
        self.refresh_comfy()

    def _set_status(self, message: str, color: str | None = None) -> None:
        self.status_var.set(message)

    def _async(
        self,
        work: Callable[[], Any],
        success: Callable[[Any], None] | None = None,
        failure: Callable[[Exception], None] | None = None,
    ) -> None:
        def runner() -> None:
            try:
                result = work()
            except Exception as error:
                callback = failure or self._show_error
                self._after(lambda error=error, callback=callback: callback(error))
            else:
                if success:
                    self._after(lambda result=result: success(result))

        threading.Thread(target=runner, daemon=True, name="ai-hub-ui-worker").start()

    def _after(self, callback: Callable[[], None]) -> None:
        if self.closing:
            return
        try:
            self.root.after(0, callback)
        except tk.TclError:
            pass

    def _show_error(self, error: Exception) -> None:
        self._set_status(f"ERROR // {error}")
        messagebox.showerror("AI Hub", str(error), parent=self.root)

    def _guarded(
        self,
        builder: Callable[[str | None], Any],
        success: Callable[[Any], None],
        approval_id: str | None = None,
    ) -> None:
        def work() -> Any:
            return builder(approval_id)

        def failure(error: Exception) -> None:
            if isinstance(error, ApprovalRequired):
                approval = error.approval
                approved = messagebox.askyesno(
                    "一次性權限核准",
                    f"{approval.get('summary', str(error))}\n\n"
                    "只核准這一次且會寫入本機稽核紀錄。",
                    icon="warning",
                    parent=self.root,
                )
                self.app.database.resolve_approval(approval["id"], approved)
                if approved:
                    self._guarded(builder, success, approval["id"])
                else:
                    self._set_status("DENIED // action was not executed")
                return
            self._show_error(error)

        self._async(work, success, failure)

    def _reload_projects(self) -> None:
        projects = self.app.database.list_projects()
        self.project_labels.clear()
        values: list[str] = []
        for project in projects:
            label = f"{project['name']}  //  {project['path']}"
            self.project_labels[label] = project["id"]
            values.append(label)
        self.project_combo["values"] = values
        desired = self.current_project_id or self.app.default_project["id"]
        label = next((key for key, value in self.project_labels.items() if value == desired), values[0] if values else "")
        if label:
            self.project_combo.set(label)
            self._set_project(self.project_labels[label])

    def _select_project(self, _event: tk.Event | None = None) -> None:
        project_id = self.project_labels.get(self.project_combo.get())
        if project_id:
            self._set_project(project_id)

    def _set_project(self, project_id: str) -> None:
        if self.current_project_id != project_id:
            self.selected_files.clear()
            self._update_context_label()
        self.current_project_id = project_id
        project = self.app.get_project(project_id)
        self.current_directory = project["path"]
        self.file_path_var.set(project["path"])
        self._reload_conversations()
        self.load_files(project["path"])
        self._set_status(f"PROJECT // {project['name']} // {project['path']}")

    def add_project(self) -> None:
        selected = filedialog.askdirectory(title="選擇 AI Hub 專案資料夾", mustexist=True, parent=self.root)
        if not selected:
            return
        try:
            project = self.app.add_project(selected)
        except Exception as error:
            self._show_error(error)
            return
        self.current_project_id = project["id"]
        self._reload_projects()

    def _reload_conversations(self) -> None:
        if not self.current_project_id:
            return
        conversations = [
            item for item in self.app.database.list_conversations()
            if item.get("project_id") == self.current_project_id
        ]
        current = self.current_conversation_id
        self.conversation_tree.delete(*self.conversation_tree.get_children())
        for conversation in conversations:
            self.conversation_tree.insert(
                "", tk.END, iid=conversation["id"],
                text=f"  {conversation['title']}", values=(conversation.get("updated_at"),),
            )
        if current and self.conversation_tree.exists(current):
            self.conversation_tree.selection_set(current)
        elif conversations:
            self._set_current_conversation(conversations[0]["id"])
        else:
            self.new_conversation()

    def _select_conversation(self, _event: tk.Event | None = None) -> None:
        selected = self.conversation_tree.selection()
        if selected:
            self._set_current_conversation(selected[0])

    def _set_current_conversation(self, conversation_id: str) -> None:
        conversation = self.app.database.get_conversation(conversation_id)
        if not conversation:
            return
        if conversation.get("project_id") and conversation.get("project_id") != self.current_project_id:
            self.current_project_id = conversation["project_id"]
            self._reload_projects()
            return
        self.current_conversation_id = conversation_id
        if self.conversation_tree.exists(conversation_id):
            if self.conversation_tree.selection() != (conversation_id,):
                self.conversation_tree.selection_set(conversation_id)
            self.conversation_tree.see(conversation_id)
        self.message_signature = None
        self.refresh_messages()
        self._set_status(f"CHAT // {conversation['title']}")

    def new_conversation(self) -> None:
        if not self.current_project_id:
            return
        try:
            conversation = self.app.create_conversation(self.current_project_id)
        except Exception as error:
            self._show_error(error)
            return
        self.current_conversation_id = conversation["id"]
        self._reload_conversations()
        self.prompt_text.focus_set()

    def refresh_providers(self, force: bool = False) -> None:
        if self._provider_refresh_running:
            return
        self._provider_refresh_running = True

        def done(items: list[dict[str, Any]]) -> None:
            self._provider_refresh_running = False
            self.provider_status = {item["id"]: item for item in items}
            existing = {key: variable.get() for key, variable in self.provider_vars.items()}
            first_population = not self.provider_vars
            for child in self.provider_frame.winfo_children():
                child.destroy()
            self.provider_vars = {}
            first_available: str | None = None
            for row, item in enumerate(items):
                if item.get("available") and first_available is None:
                    first_available = item["id"]
                selected = existing.get(item["id"], False)
                if first_population and item["id"] == "codex" and item.get("available"):
                    selected = True
                variable = tk.BooleanVar(value=selected and bool(item.get("available")))
                self.provider_vars[item["id"]] = variable
                marker = "●" if item.get("available") else "○"
                checkbox = ttk.Checkbutton(
                    self.provider_frame,
                    text=f"{marker} {item['label']}",
                    variable=variable,
                    state=tk.NORMAL if item.get("available") else tk.DISABLED,
                )
                checkbox.grid(row=row, column=0, sticky="w")
            if first_population and not any(variable.get() for variable in self.provider_vars.values()) and first_available:
                self.provider_vars[first_available].set(True)
            self._populate_integrations(items)
            online = sum(1 for item in items if item.get("available"))
            self._set_status(f"INTEGRATIONS // {online}/{len(items)} ready")

        def failed(error: Exception) -> None:
            self._provider_refresh_running = False
            self._show_error(error)

        self._async(lambda: self.app.providers.status(force=force), done, failed)

    def _selected_provider_ids(self) -> list[str]:
        return [
            provider_id for provider_id, variable in self.provider_vars.items()
            if variable.get() and self.provider_status.get(provider_id, {}).get("available")
        ]

    def send_prompt(self) -> None:
        prompt = self.prompt_text.get("1.0", tk.END).strip()
        if not prompt:
            self.prompt_text.focus_set()
            return
        providers = self._selected_provider_ids()
        if not providers:
            messagebox.showwarning("AI Hub", "請先選擇至少一個已登入或已就緒的 AI。", parent=self.root)
            return
        if not self.current_project_id or not self.current_conversation_id:
            return
        payload = {
            "prompt": prompt,
            "project_id": self.current_project_id,
            "conversation_id": self.current_conversation_id,
            "provider_ids": providers,
            "permission_mode": self.permission_var.get(),
            "selected_files": sorted(self.selected_files),
            "web_access": self.web_var.get(),
            "collaboration": self.collaboration_var.get() and len(providers) > 1,
            "peer_review": self.review_var.get(),
        }
        self._set_status(f"PREFLIGHT // analyzing with {len(providers)} selected AI")

        def builder(approval_id: str | None) -> dict[str, Any]:
            return self.app.run_prompt({**payload, "approval_id": approval_id})

        def done(result: dict[str, Any]) -> None:
            self.prompt_text.delete("1.0", tk.END)
            self._show_feasibility(result.get("feasibility") or {})
            self.message_signature = None
            self.task_signature = None
            self.refresh_messages()
            self.refresh_tasks()
            task_ids = ", ".join(task["id"][-8:] for task in result.get("tasks", []))
            self._set_status(f"RUNNING // {task_ids}")

        self._guarded(builder, done)

    def _show_feasibility(self, feasibility: dict[str, Any]) -> None:
        if not feasibility:
            return
        score = feasibility.get("score", "--")
        confidence = feasibility.get("confidence", "--")
        eta = compact_seconds(feasibility.get("estimated_seconds"))
        self.feasibility_score.set(f"成功性前檢 · {score}% · {feasibility.get('label', '')}")
        weakest = sorted(feasibility.get("factors") or [], key=lambda item: item.get("score", 100))[:2]
        weak_text = " · ".join(f"{item.get('label')} {item.get('score')}" for item in weakest)
        calibration = feasibility.get("calibration") or {}
        quality_labels = {
            "measured-better": "已由本機驗證資料證明優於固定基準",
            "measured-not-better": "已有量測，但尚未優於固定基準",
            "not-yet-measured": "蒐集驗證樣本中",
        }
        brier = calibration.get("validation_brier")
        brier_text = f" · Brier {brier}" if brier is not None else ""
        self.feasibility_detail.set(
            f"可信度 {confidence}% · ETA {eta} · {weak_text} · "
            f"{quality_labels.get(calibration.get('quality'), calibration.get('state', '--'))}{brier_text}"
        )

    def refresh_messages(self) -> None:
        if not self.current_conversation_id:
            return
        messages = self.app.database.list_messages(self.current_conversation_id)
        signature = (
            len(messages),
            messages[-1]["id"] if messages else None,
            len(messages[-1].get("content", "")) if messages else 0,
        )
        if signature == self.message_signature:
            return
        self.message_signature = signature
        self.chat_text.configure(state=tk.NORMAL)
        self.chat_text.delete("1.0", tk.END)
        if not messages:
            self.chat_text.insert(tk.END, "SYSTEM // 對話已建立，等待工作指令。\n", "system_header")
        for message in messages:
            role = message.get("role", "system")
            if role == "user":
                label, tag = "YOU", "user_header"
            elif role == "assistant":
                label, tag = message.get("provider_id") or "AI", "assistant_header"
            else:
                label, tag = "SYSTEM", "system_header"
            self.chat_text.insert(
                tk.END,
                f"\n[{local_time(message.get('created_at'), True)}] {label.upper()}\n",
                tag,
            )
            self.chat_text.insert(tk.END, f"{message.get('content', '')}\n", "body")
            metadata = message.get("metadata") or {}
            if role == "user" and metadata.get("feasibility"):
                self._show_feasibility(metadata["feasibility"])
        self.chat_text.configure(state=tk.DISABLED)
        self.chat_text.see(tk.END)

    def _task_remaining(self, task: dict[str, Any]) -> str:
        if task.get("status") not in {"queued", "running", "cancelling"}:
            if task.get("started_at") and task.get("completed_at"):
                try:
                    duration = datetime.fromisoformat(task["completed_at"]) - datetime.fromisoformat(task["started_at"])
                    return compact_seconds(duration.total_seconds())
                except ValueError:
                    pass
            return "--"
        try:
            predicted = datetime.fromisoformat(task.get("predicted_end_at") or "")
            if predicted.tzinfo is None:
                predicted = predicted.replace(tzinfo=timezone.utc)
            return compact_seconds((predicted - datetime.now(timezone.utc)).total_seconds())
        except ValueError:
            return compact_seconds(task.get("predicted_seconds"))

    def refresh_tasks(self) -> None:
        tasks = self.app.database.list_tasks(limit=160)
        signature = tuple(
            (item["id"], item.get("status"), round(float(item.get("progress") or 0), 1), item.get("stage"), item.get("completed_at"))
            for item in tasks
        )
        if signature == self.task_signature:
            self._refresh_terminal_task()
            return
        self.task_signature = signature
        selected = self.task_tree.selection()
        selected_id = selected[0] if selected else None
        self.task_tree.delete(*self.task_tree.get_children())
        for task in tasks:
            title = task.get("title") or "工作"
            if task.get("parent_task_id"):
                title = "↳ " + title
            status = task.get("status") or "unknown"
            self.task_tree.insert(
                "", tk.END, iid=task["id"],
                values=(
                    task.get("provider_id"), title, status, task.get("stage"),
                    f"{float(task.get('progress') or 0):.0f}", self._task_remaining(task),
                    local_time(task.get("completed_at") or task.get("predicted_end_at")),
                ),
                tags=(status,),
            )
        if selected_id and self.task_tree.exists(selected_id):
            self.task_tree.selection_set(selected_id)
        self._refresh_terminal_task()

    def _selected_task_id(self) -> str | None:
        selected = self.task_tree.selection()
        return selected[0] if selected else None

    def _show_task_details(self, _event: tk.Event | None = None) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        task = self.app.database.get_task(task_id)
        if not task:
            return
        events = self.app.database.list_task_events(task_id)
        self.task_detail_var.set(
            f"{task.get('provider_id')} // {task.get('status')} // {float(task.get('progress') or 0):.0f}% // {task_id[-8:]}"
        )
        lines = [
            f"WORK: {task.get('title')}",
            f"CREATED: {local_time(task.get('created_at'), True)}",
            f"PREDICTED END: {local_time(task.get('predicted_end_at'), True)}",
            f"ACTUAL END: {local_time(task.get('completed_at'), True)}",
            "",
        ]
        for event in events:
            progress = f" {float(event['progress']):.0f}%" if event.get("progress") is not None else ""
            lines.append(f"[{local_time(event.get('created_at'), True)}] {event.get('level', 'info').upper()}{progress}  {event.get('message', '')}")
        if task.get("result"):
            lines.extend(["", "── RESULT ──", str(task["result"])])
        if task.get("error"):
            lines.extend(["", "── ERROR ──", str(task["error"])])
        self._replace_text(self.task_event_text, "\n".join(lines), readonly=True)

    def stop_selected_task(self) -> None:
        task_id = self._selected_task_id()
        if task_id:
            stopped = self.app.tasks.cancel(task_id)
            self._set_status("CANCEL SIGNAL SENT" if stopped else "TASK ALREADY FINISHED")

    def stop_latest_task(self) -> None:
        active = self.app.database.list_tasks(self.current_conversation_id, active_only=True, limit=20)
        if not active:
            self._set_status("NO ACTIVE TASK IN CURRENT CHAT")
            return
        self.app.tasks.cancel(active[0]["id"])
        self._set_status(f"CANCEL SIGNAL // {active[0]['id'][-8:]}")

    def rate_task(self, success: bool) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        try:
            self.app.database.set_task_feedback(task_id, success, "桌面端人工驗證")
        except Exception as error:
            self._show_error(error)
            return
        self._set_status(f"CALIBRATION SAMPLE // {task_id[-8:]} = {'success' if success else 'failed'}")

    @staticmethod
    def _size_label(size: int | float | None) -> str:
        value = float(size or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"

    def load_files(self, path: str | None = None) -> None:
        if not self.current_project_id:
            return
        target = path or self.current_directory
        project_id = self.current_project_id
        self._set_status(f"FILES // reading {target or 'project root'}")

        def done(payload: dict[str, Any]) -> None:
            if project_id != self.current_project_id:
                return
            self.current_directory = payload["path"]
            self.file_path_var.set(payload["path"])
            self.file_rows.clear()
            self.file_tree.delete(*self.file_tree.get_children())
            for index, entry in enumerate(payload.get("entries", [])):
                iid = f"file_{index}"
                self.file_rows[iid] = entry
                icon = "▸" if entry.get("is_dir") else "·"
                self.file_tree.insert(
                    "", tk.END, iid=iid, text=f" {icon}  {entry['name']}",
                    values=("<DIR>" if entry.get("is_dir") else self._size_label(entry.get("size")), local_time(entry.get("modified_at"))),
                )
            self._set_status(f"FILES // {len(payload.get('entries', []))} entries // {payload['path']}")

        self._async(lambda: self.app.list_files(project_id, target), done)

    def file_up(self) -> None:
        if not self.current_project_id or not self.current_directory:
            return
        project = self.app.get_project(self.current_project_id)
        current = Path(self.current_directory).resolve()
        root = Path(project["path"]).resolve()
        if current == root:
            return
        try:
            current.parent.relative_to(root)
        except ValueError:
            return
        self.load_files(str(current.parent))

    def _selected_file_entry(self) -> dict[str, Any] | None:
        selected = self.file_tree.selection()
        return self.file_rows.get(selected[0]) if selected else None

    def _open_file_tree_item(self, _event: tk.Event | None = None) -> None:
        entry = self._selected_file_entry()
        if not entry:
            return
        if entry.get("is_dir"):
            self.load_files(entry["path"])
        else:
            self.preview_file(entry["path"])

    def _preview_file_tree_item(self, _event: tk.Event | None = None) -> None:
        entry = self._selected_file_entry()
        if entry and not entry.get("is_dir"):
            self.preview_file(entry["path"])

    def preview_file(self, path: str) -> None:
        if not self.current_project_id:
            return
        project_id = self.current_project_id

        def done(payload: dict[str, Any]) -> None:
            if project_id != self.current_project_id:
                return
            self.current_file = payload["path"]
            self.file_info_var.set(
                f"FILE // {Path(payload['path']).name} // {self._size_label(payload.get('size'))}"
                + (" // BINARY" if payload.get("binary") else " // UTF-8 EDIT")
            )
            content = "Binary file preview is disabled." if payload.get("binary") else payload.get("content", "")
            self._replace_text(self.file_editor, content, readonly=bool(payload.get("binary")))

        self._async(lambda: self.app.read_file(project_id, path), done)

    def add_selected_file(self) -> None:
        entry = self._selected_file_entry()
        if not entry or entry.get("is_dir"):
            return
        self.selected_files.add(entry["path"])
        self._update_context_label()
        self._set_status(f"AI CONTEXT + // {entry['path']}")

    def remove_selected_file(self) -> None:
        entry = self._selected_file_entry()
        target = entry.get("path") if entry else self.current_file
        if target:
            self.selected_files.discard(str(target))
            self._update_context_label()

    def _update_context_label(self) -> None:
        if not self.selected_files:
            self.context_var.set("尚未選取檔案範圍")
            return
        names = ", ".join(Path(path).name for path in sorted(self.selected_files)[:4])
        suffix = f" +{len(self.selected_files) - 4}" if len(self.selected_files) > 4 else ""
        self.context_var.set(f"已選取 {len(self.selected_files)} 個檔案 · {names}{suffix}")

    def save_current_file(self) -> None:
        if not self.current_project_id or not self.current_file:
            return
        content = self.file_editor.get("1.0", tk.END)
        payload = {
            "project_id": self.current_project_id,
            "path": self.current_file,
            "content": content,
            "permission_mode": self.permission_var.get(),
        }

        def builder(approval_id: str | None) -> dict[str, Any]:
            return self.app.write_file({**payload, "approval_id": approval_id})

        def done(result: dict[str, Any]) -> None:
            self._set_status(f"SAVED // {result['path']} // {self._size_label(result['size'])}")
            self.load_files()

        self._guarded(builder, done)

    def open_in_explorer(self) -> None:
        if not self.current_project_id:
            return
        entry = self._selected_file_entry()
        target = entry.get("path") if entry else self.current_directory
        try:
            self.app.open_in_explorer(self.current_project_id, target)
        except Exception as error:
            self._show_error(error)

    def _show_transfer_task(self, result: dict[str, Any], label: str) -> None:
        task = result["task"]
        self._set_status(f"{label} · 工作 {task['id'][-8:]} 已開始")
        self.task_signature = None
        self.refresh_tasks()
        self.tabs.select(self.agents_tab)

    def download_from_url(self) -> None:
        if not self.current_project_id:
            return
        url = self.download_url_var.get().strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            messagebox.showwarning("AI Hub", "請輸入有效的 HTTP/HTTPS 下載網址。", parent=self.root)
            return
        default_name = Path(urllib.parse.unquote(parsed.path)).name or "download.bin"
        target = filedialog.asksaveasfilename(
            parent=self.root,
            title="選擇下載位置",
            initialdir=self.current_directory or self.app.paths.downloads,
            initialfile=default_name,
        )
        if not target:
            return
        overwrite = Path(target).exists()
        if overwrite and not messagebox.askyesno("覆寫檔案", f"檔案已存在，確定覆寫？\n{target}", parent=self.root):
            return
        payload = {
            "url": url,
            "target": target,
            "overwrite": overwrite,
            "project_id": self.current_project_id,
            "conversation_id": self.current_conversation_id,
            "permission_mode": self.permission_var.get(),
        }

        def builder(approval_id: str | None) -> dict[str, Any]:
            return self.app.download_url({**payload, "approval_id": approval_id})

        self._guarded(builder, lambda result: self._show_transfer_task(result, "下載"))

    def import_external_file(self) -> None:
        if not self.current_project_id:
            return
        source = filedialog.askopenfilename(parent=self.root, title="從本機、網路或外接裝置匯入")
        if not source:
            return
        target = filedialog.asksaveasfilename(
            parent=self.root,
            title="儲存到目前專案",
            initialdir=self.current_directory or self.app.get_project(self.current_project_id)["path"],
            initialfile=Path(source).name,
        )
        if not target:
            return
        overwrite = Path(target).exists()
        if overwrite and not messagebox.askyesno("覆寫檔案", f"檔案已存在，確定覆寫？\n{target}", parent=self.root):
            return
        payload = {
            "source": source,
            "target": target,
            "overwrite": overwrite,
            "project_id": self.current_project_id,
            "conversation_id": self.current_conversation_id,
            "permission_mode": self.permission_var.get(),
        }

        def builder(approval_id: str | None) -> dict[str, Any]:
            return self.app.transfer_file({**payload, "approval_id": approval_id})

        self._guarded(builder, lambda result: self._show_transfer_task(result, "匯入"))

    def export_selected_file(self) -> None:
        if not self.current_project_id:
            return
        entry = self._selected_file_entry()
        source = str(entry.get("path")) if entry and not entry.get("is_dir") else self.current_file
        if not source or not Path(source).is_file():
            messagebox.showwarning("AI Hub", "請先選取要匯出的檔案。", parent=self.root)
            return
        target = filedialog.asksaveasfilename(
            parent=self.root,
            title="匯出到本機、網路或外接裝置",
            initialfile=Path(source).name,
        )
        if not target:
            return
        overwrite = Path(target).exists()
        if overwrite and not messagebox.askyesno("覆寫檔案", f"檔案已存在，確定覆寫？\n{target}", parent=self.root):
            return
        payload = {
            "source": source,
            "target": target,
            "overwrite": overwrite,
            "project_id": self.current_project_id,
            "conversation_id": self.current_conversation_id,
            "permission_mode": self.permission_var.get(),
        }

        def builder(approval_id: str | None) -> dict[str, Any]:
            return self.app.transfer_file({**payload, "approval_id": approval_id})

        self._guarded(builder, lambda result: self._show_transfer_task(result, "匯出"))

    def open_bluetooth_transfer(self) -> None:
        if not self.current_project_id:
            return
        payload = {
            "project_id": self.current_project_id,
            "permission_mode": self.permission_var.get(),
        }

        def builder(approval_id: str | None) -> dict[str, Any]:
            return self.app.launch_bluetooth_transfer({**payload, "approval_id": approval_id})

        self._guarded(builder, lambda _result: self._set_status("已開啟 Windows Bluetooth 檔案傳輸精靈"))

    def _queue_search(self, _event: tk.Event | None = None) -> None:
        if self._search_after:
            try:
                self.root.after_cancel(self._search_after)
            except tk.TclError:
                pass
        self._search_after = self.root.after(280, self.run_global_search)

    def crawl_public_url(self) -> None:
        url = self.crawler_url_var.get().strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            messagebox.showwarning("AI Hub", "請輸入有效的公開 HTTP/HTTPS 網址。", parent=self.root)
            return
        if not messagebox.askyesno(
            "公開網址研究",
            f"將依 robots.txt 擷取最多 2 MB 文字並存入本機索引：\n{url}\n\n繼續嗎？",
            parent=self.root,
        ):
            return
        self._set_status(f"正在擷取公開網址 · {parsed.hostname}")

        def done(document: dict[str, Any]) -> None:
            self.crawler_url_var.set("")
            self.search_var.set(document.get("title") or parsed.hostname or "")
            self.run_global_search()
            self._set_status(f"研究資料已加入本機索引 · {document.get('title')}")

        self._async(lambda: self.app.crawler.fetch(url), done)

    def run_global_search(self) -> None:
        self._search_after = None
        query = self.search_var.get().strip()
        self.search_tree.delete(*self.search_tree.get_children())
        self.search_rows.clear()
        if not query:
            self.search_stats_var.set("LOCAL INDEX // type to search across all stored work")
            return
        try:
            rows = self.app.database.search(query, limit=120)
        except Exception as error:
            self._show_error(error)
            return
        for index, row in enumerate(rows):
            iid = f"search_{index}"
            self.search_rows[iid] = row
            title = row.get("title") or row.get("excerpt") or row.get("ref_id")
            self.search_tree.insert(
                "", tk.END, iid=iid,
                values=(str(row.get("kind", "")).upper(), title, local_time(row.get("updated_at"), True)),
            )
        self.search_stats_var.set(f"FTS5 TRIGRAM // {len(rows)} matches // query: {query}")
        if rows:
            self.search_tree.selection_set("search_0")
            self._show_search_result()

    def _selected_search_row(self) -> dict[str, Any] | None:
        selected = self.search_tree.selection()
        return self.search_rows.get(selected[0]) if selected else None

    def _show_search_result(self, _event: tk.Event | None = None) -> None:
        row = self._selected_search_row()
        if not row:
            return
        detail: dict[str, Any] = dict(row)
        metadata = row.get("metadata") or {}
        if row.get("kind") == "task":
            detail["task"] = self.app.database.get_task(row["ref_id"])
        elif row.get("kind") in {"message", "conversation"} and metadata.get("conversation_id"):
            messages = self.app.database.list_messages(metadata["conversation_id"])
            detail["conversation_tail"] = messages[-8:]
        self._replace_text(self.search_preview, json.dumps(detail, ensure_ascii=False, indent=2), readonly=True)

    def _open_search_result(self, _event: tk.Event | None = None) -> None:
        row = self._selected_search_row()
        if not row:
            return
        metadata = row.get("metadata") or {}
        conversation_id = metadata.get("conversation_id")
        project_id = metadata.get("project_id")
        if project_id and project_id != self.current_project_id:
            self._set_project(project_id)
        if conversation_id:
            self._set_current_conversation(conversation_id)
            self.tabs.select(self.chat_tab)
            return
        if row.get("kind") == "task" and self.task_tree.exists(row["ref_id"]):
            self.task_tree.selection_set(row["ref_id"])
            self.task_tree.see(row["ref_id"])
            self.tabs.select(self.agents_tab)
            self._show_task_details()
            return
        if row.get("kind") == "research" and metadata.get("url"):
            webbrowser.open(metadata["url"])

    def _replace_text(self, widget: tk.Text, content: str, readonly: bool = False) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        if readonly:
            widget.configure(state=tk.DISABLED)

    def _append_text(self, widget: tk.Text, content: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.insert(tk.END, content)
        widget.configure(state=tk.DISABLED)
        widget.see(tk.END)

    def launch_local_app(self) -> None:
        if not self.current_project_id:
            return
        executable = filedialog.askopenfilename(
            parent=self.root,
            title="選擇要開啟的本機程式",
            filetypes=(("Windows applications", "*.exe *.com *.bat *.cmd"), ("All files", "*.*")),
        )
        if not executable:
            return
        payload = {
            "executable": executable,
            "project_id": self.current_project_id,
            "permission_mode": self.permission_var.get(),
        }

        def builder(approval_id: str | None) -> dict[str, Any]:
            return self.app.launch_external_app({**payload, "approval_id": approval_id})

        self._guarded(
            builder,
            lambda result: self._set_status(f"已開啟本機程式 · {result['opened']}"),
        )

    def set_terminal_command(self, command: str) -> None:
        self.terminal_command.delete("1.0", tk.END)
        self.terminal_command.insert("1.0", command)
        self.terminal_command.focus_set()

    def run_terminal(self) -> None:
        command = self.terminal_command.get("1.0", tk.END).strip()
        if not command or not self.current_project_id:
            return
        payload = {
            "command": command,
            "project_id": self.current_project_id,
            "conversation_id": self.current_conversation_id,
            "permission_mode": self.permission_var.get(),
        }
        self._replace_text(self.terminal_output, f"PS> {command}\n\n", readonly=True)

        def builder(approval_id: str | None) -> dict[str, Any]:
            return self.app.run_terminal({**payload, "approval_id": approval_id})

        def done(result: dict[str, Any]) -> None:
            task = result["task"]
            self.terminal_task_id = task["id"]
            self.terminal_last_event = 0
            self.terminal_final_signature = None
            self._set_status(f"TERMINAL RUNNING // {task['id'][-8:]}")

        self._guarded(builder, done)

    def _refresh_terminal_task(self) -> None:
        if not self.terminal_task_id:
            return
        events = self.app.database.list_task_events(self.terminal_task_id, self.terminal_last_event)
        for event in events:
            self.terminal_last_event = max(self.terminal_last_event, int(event["id"]))
            self._append_text(
                self.terminal_output,
                f"[{local_time(event.get('created_at'), True)}] {event.get('message', '')}\n",
            )
        task = self.app.database.get_task(self.terminal_task_id)
        if not task or task.get("status") in {"queued", "running", "cancelling"}:
            return
        signature = (task.get("status", ""), task.get("result"), task.get("error"))
        if signature == self.terminal_final_signature:
            return
        self.terminal_final_signature = signature
        final = task.get("result") or task.get("error") or task.get("status")
        self._append_text(self.terminal_output, f"\n── {task.get('status', '').upper()} ──\n{final}\n")

    def refresh_models(self) -> None:
        def work() -> tuple[list[dict[str, Any]], dict[str, Any]]:
            return self.app.models.catalog(), self.app.models.readiness()

        def done(payload: tuple[list[dict[str, Any]], dict[str, Any]]) -> None:
            catalog, readiness = payload
            self.model_tree.delete(*self.model_tree.get_children())
            for item in catalog:
                state = item.get("compatibility", {}).get("state", "unknown")
                if item.get("installed"):
                    state = "ready"
                parameters = f"{item['parameters_b']}B" if item.get("parameters_b") is not None else "--"
                self.model_tree.insert(
                    "", tk.END, iid=item["id"],
                    values=(
                        item.get("family"), item.get("label"), parameters, item.get("runtime"),
                        state.upper(), f"{item.get('disk_gb', '--')} GB", item.get("notes"),
                    ), tags=(state,),
                )
            detected = readiness.get("lora_training", {}).get("detected", "")
            self.model_readiness_var.set(f"HARDWARE // {detected} // 32B+ routed to remote GPU")

        self._async(work, done)

    def _selected_model_id(self) -> str | None:
        selected = self.model_tree.selection()
        return selected[0] if selected else None

    def open_model_source(self) -> None:
        model_id = self._selected_model_id()
        if not model_id:
            return
        item = next((entry for entry in self.app.models.catalog() if entry["id"] == model_id), None)
        source = (item or {}).get("source")
        if not source:
            messagebox.showinfo("AI Hub", "此本機模型項目沒有外部來源頁。", parent=self.root)
            return
        webbrowser.open(str(source))

    def pick_training_dataset(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="選擇 JSONL 訓練資料集",
            filetypes=(("JSON Lines", "*.jsonl"), ("JSON", "*.json"), ("All files", "*.*")),
        )
        if selected:
            self.training_dataset_var.set(selected)

    def pick_training_output(self) -> None:
        initial = self.app.get_project(self.current_project_id)["path"] if self.current_project_id else str(self.app.paths.root)
        selected = filedialog.askdirectory(parent=self.root, title="選擇 LoRA adapter 輸出資料夾", initialdir=initial)
        if selected:
            self.training_output_var.set(selected)

    @staticmethod
    def _training_summary(preflight: dict[str, Any]) -> str:
        requirements = preflight.get("requirements") or {}
        dataset = preflight.get("dataset") or {}
        cuda = preflight.get("cuda") or {}
        state = "可開始" if preflight.get("ready") else "不可開始"
        blockers = "；".join(preflight.get("blockers") or []) or "所有必要條件已通過"
        return (
            f"{state} · {preflight.get('training_model')} · 資料 {dataset.get('examples', 0)} 筆 · "
            f"CUDA {cuda.get('name')} {cuda.get('vram_gb', 0)} GB · "
            f"最低需求 VRAM {requirements.get('vram_gb', '--')} / RAM {requirements.get('ram_gb', '--')} / "
            f"磁碟 {requirements.get('disk_gb', '--')} GB · {blockers}"
        )

    def training_preflight(self) -> None:
        model_id = self._selected_model_id()
        dataset = self.training_dataset_var.get().strip()
        if not model_id or not dataset:
            messagebox.showwarning("AI Hub", "請先選擇可訓練文字模型與 JSONL 資料集。", parent=self.root)
            return
        self.training_status_var.set("正在驗證資料集、CUDA、VRAM、RAM 與磁碟…")

        def done(result: dict[str, Any]) -> None:
            self.training_status_var.set(self._training_summary(result))

        self._async(lambda: self.app.models.training_preflight(model_id, dataset), done)

    def start_training(self) -> None:
        if not self.current_project_id:
            return
        model_id = self._selected_model_id()
        dataset = self.training_dataset_var.get().strip()
        output = self.training_output_var.get().strip()
        if not model_id or not dataset or not output:
            messagebox.showwarning("AI Hub", "請先選擇模型、JSONL 資料集與輸出資料夾。", parent=self.root)
            return
        try:
            epochs = float(self.training_epochs_var.get())
            rank = int(self.training_rank_var.get())
        except ValueError:
            messagebox.showwarning("AI Hub", "Epochs 或 LoRA rank 格式無效。", parent=self.root)
            return
        payload = {
            "model_id": model_id,
            "dataset": dataset,
            "output": output,
            "epochs": epochs,
            "lora_rank": rank,
            "project_id": self.current_project_id,
            "conversation_id": self.current_conversation_id,
            "permission_mode": self.permission_var.get(),
        }

        def builder(approval_id: str | None) -> dict[str, Any]:
            return self.app.run_training({**payload, "approval_id": approval_id})

        def done(result: dict[str, Any]) -> None:
            self.training_status_var.set(self._training_summary(result["preflight"]))
            self._show_transfer_task(result, "QLoRA 訓練")

        self._guarded(builder, done)

    def download_model(self) -> None:
        model_id = self._selected_model_id()
        if not model_id or not self.current_project_id:
            return
        item = next((entry for entry in self.app.models.catalog() if entry["id"] == model_id), None)
        if item and not messagebox.askyesno(
            "下載模型",
            f"即將下載 {item.get('label')}，預估磁碟 {item.get('disk_gb', '--')} GB。\n"
            f"{item.get('compatibility', {}).get('reason', '')}\n\n繼續嗎？",
            parent=self.root,
        ):
            return
        project = self.app.get_project(self.current_project_id)
        try:
            task = self.app.models.pull(model_id, project, self.current_conversation_id)
        except Exception as error:
            self._show_error(error)
            return
        self._set_status(f"MODEL DOWNLOAD // {model_id} // {task['id'][-8:]}")
        self.tabs.select(self.agents_tab)

    def _populate_integrations(self, items: list[dict[str, Any]]) -> None:
        self.integration_tree.delete(*self.integration_tree.get_children())
        for item in items:
            installed = item.get("installed")
            if item.get("available"):
                state = "READY"
            elif installed:
                state = "LOGIN REQUIRED"
            else:
                state = "SETUP"
            tag = "online" if item.get("available") else "setup"
            self.integration_tree.insert(
                "", tk.END, iid=item["id"],
                values=(item.get("label"), item.get("kind"), state, item.get("detail")),
                tags=(tag,),
            )
        comfy = self.comfy_last_status
        if comfy:
            state = "READY" if comfy.get("available") else "OFFLINE"
            values = (
                "ComfyUI", "image", state,
                f"{comfy.get('base_url')} · {comfy.get('detail')}",
            )
            tag = "online" if comfy.get("available") else "setup"
        else:
            values = ("ComfyUI", "image", "PROBE", self.comfy_url.get())
            tag = "setup"
        self.integration_tree.insert("", tk.END, iid="comfyui", values=values, tags=(tag,))
        integration_state = self.app.integrations.status()
        play = integration_state.get("google_play", {})
        self.integration_tree.insert("", tk.END, iid="google-play", values=("Google Play", "account", "READY" if play.get("token_present") else "TOKEN REQUIRED", play.get("mode")), tags=("online" if play.get("token_present") else "setup",))
        self.integration_tree.insert("", tk.END, iid="google-sites", values=("Google Sites", "browser", "ASSISTED", "Modern Sites browser-assisted session"), tags=("online",))
        sync = integration_state.get("model_sync", {})
        self.integration_tree.insert("", tk.END, iid="model-sync", values=("Kimi / DeepSeek metadata", "models", "READY" if sync.get("metadata_present") else "SYNC REQUIRED", "official organization metadata"), tags=("online" if sync.get("metadata_present") else "setup",))
        if hasattr(self, "resource_policy_var"):
            policy = self.app.hardware.resource_policy(int(self.app.settings.get("max_parallel_agents", 3)))
            reasons = " · ".join(policy.get("reasons") or [])
            self.resource_policy_var.set(f"RESOURCE GOVERNOR // parallel={policy.get('max_parallel_agents')} // remote-first={policy.get('prefer_remote_model')} // {reasons}")

    def save_integrations(self) -> None:
        values = {
            "provider_config": {
                "compatible": {
                    "base_url": self.compatible_url.get().strip(),
                    "model": self.compatible_model.get().strip(),
                    "api_key_env": self.compatible_env.get().strip() or "AI_HUB_API_KEY",
                },
                "comfyui": {
                    "base_url": self.comfy_url.get().strip(),
                    "checkpoint": self.comfy_checkpoint.get().strip(),
                },
            }
        }
        try:
            self.app.update_settings(values)
        except Exception as error:
            self._show_error(error)
            return
        self.image_checkpoint.set(self.comfy_checkpoint.get().strip())
        self._set_status("INTEGRATIONS // 設定已儲存")
        self.refresh_providers(True)
        self.refresh_comfy()

    def sync_official_models(self) -> None:
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

    def install_clis(self) -> None:
        setup = self.app.paths.root / "setup.ps1"
        if not setup.is_file():
            self._show_error(FileNotFoundError(f"找不到 {setup}"))
            return
        if not messagebox.askyesno(
            "安裝 / 更新 CLI",
            "將從官方來源更新 Codex CLI 與 Gemini CLI。繼續嗎？",
            parent=self.root,
        ):
            return
        try:
            subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(setup),
                    "-InstallCli",
                ],
                cwd=str(self.app.paths.root),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except OSError as error:
            self._show_error(error)
            return
        self.app.database.audit("cli.install_opened", str(setup))
        self._set_status("CLI 更新視窗已開啟；完成後按重新檢查")

    def open_cli_login(self, provider_id: str) -> None:
        try:
            provider = self.app.providers.get(provider_id)
            command = getattr(provider, "command", None)
        except Exception as error:
            self._show_error(error)
            return
        if not command:
            messagebox.showwarning("AI Hub", f"{provider_id} CLI 尚未安裝。", parent=self.root)
            return
        if not messagebox.askyesno(
            "外部帳號登入",
            f"即將開啟 {provider_id} 官方 CLI 的互動登入視窗。\n"
            "登入資料由官方 CLI 保存；AI Hub 不會讀取或儲存密碼。\n\n允許這一次嗎？",
            icon="warning",
            parent=self.root,
        ):
            return
        arguments = [str(command)] + (["login"] if provider_id == "codex" else [])
        command_line = subprocess.list2cmdline(arguments)
        project = self.app.get_project(self.current_project_id) if self.current_project_id else self.app.default_project
        try:
            subprocess.Popen(
                [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/k", command_line],
                cwd=project["path"],
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except OSError as error:
            self._show_error(error)
            return
        self.app.database.audit("account.cli_login_opened", provider_id, {"command": str(command)})
        self._set_status(f"LOGIN WINDOW // {provider_id} // refresh after completion")

    @staticmethod
    def _valid_clock(value: str) -> bool:
        try:
            datetime.strptime(value, "%H:%M")
            return True
        except ValueError:
            return False

    def reload_schedules(self) -> None:
        schedules = self.app.database.list_schedules()
        self.schedule_tree.delete(*self.schedule_tree.get_children())
        for schedule in schedules:
            self.schedule_tree.insert(
                "", tk.END, iid=schedule["id"],
                values=(
                    schedule.get("name"),
                    f"{schedule.get('start_time')}–{schedule.get('end_time')}",
                    f"{schedule.get('interval_minutes')}m",
                    f"{schedule.get('duration_minutes')}m",
                    schedule.get("mode"),
                    "ON" if schedule.get("enabled") else "OFF",
                    local_time(schedule.get("last_run_at"), True),
                ),
            )

    def create_schedule(self) -> None:
        if not self.current_project_id:
            return
        start = self.schedule_window_start.get().strip()
        end = self.schedule_window_end.get().strip()
        if not self._valid_clock(start) or not self._valid_clock(end):
            messagebox.showwarning("AI Hub", "時間格式必須是 HH:MM。", parent=self.root)
            return
        try:
            interval = max(5, int(self.schedule_interval.get()))
            duration = max(1, int(self.schedule_duration.get()))
        except ValueError:
            messagebox.showwarning("AI Hub", "間隔與時長必須是整數分鐘。", parent=self.root)
            return
        mode = self.schedule_mode.get()
        providers = [] if mode == "image" else self._selected_provider_ids()
        if mode != "image" and not providers:
            messagebox.showwarning("AI Hub", "改善排程至少需要一個已就緒 AI。", parent=self.root)
            return
        prompt = self.schedule_prompt.get("1.0", tk.END).strip()
        if not prompt:
            return
        payload = {
            "name": self.schedule_name.get().strip() or "自動工作",
            "prompt": prompt,
            "project_id": self.current_project_id,
            "provider_ids": providers,
            "start_time": start,
            "end_time": end,
            "duration_minutes": duration,
            "interval_minutes": interval,
            "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "mode": mode,
            "enabled": True,
        }
        try:
            schedule = self.app.database.create_schedule(payload)
            self.app.database.audit("schedule.created", schedule["id"], {"mode": mode})
        except Exception as error:
            self._show_error(error)
            return
        self.reload_schedules()
        self._set_status(f"AUTOMATION CREATED // {schedule['name']}")

    def delete_schedule(self) -> None:
        selected = self.schedule_tree.selection()
        if not selected:
            return
        schedule_id = selected[0]
        if not messagebox.askyesno(
            "刪除排程", "確定要刪除選取的自動排程？", icon="warning", parent=self.root
        ):
            return
        self.app.database.delete_schedule(schedule_id)
        self.app.database.audit("schedule.deleted", schedule_id)
        self.reload_schedules()
        self._set_status(f"AUTOMATION DELETED // {schedule_id[-8:]}")

    def refresh_comfy(self) -> None:
        def done(status: dict[str, Any]) -> None:
            self.comfy_last_status = status
            state = "READY" if status.get("available") else "OFFLINE"
            self.comfy_status_var.set(f"COMFYUI // {state} // {status.get('detail')}")
            checkpoints = status.get("checkpoints") or []
            self.checkpoint_combo["values"] = checkpoints
            selected = status.get("selected_checkpoint")
            if selected:
                self.image_checkpoint.set(selected)
                self.comfy_checkpoint.set(selected)
            values = ("ComfyUI", "image", state, f"{status.get('base_url')} · {status.get('detail')}")
            tag = "online" if status.get("available") else "setup"
            if self.integration_tree.exists("comfyui"):
                self.integration_tree.item("comfyui", values=values, tags=(tag,))
            else:
                self.integration_tree.insert("", tk.END, iid="comfyui", values=values, tags=(tag,))

        self._async(self.app.images.status, done)

    def generate_image(self) -> None:
        if not self.current_project_id:
            return
        prompt = self.image_prompt.get("1.0", tk.END).strip()
        if not prompt:
            return
        try:
            seed = int(self.image_seed.get()) if self.image_seed.get().strip() else None
            project = self.app.get_project(self.current_project_id)
            task = self.app.images.launch(
                {
                    "prompt": prompt,
                    "negative": self.image_negative.get("1.0", tk.END).strip(),
                    "checkpoint": self.image_checkpoint.get().strip(),
                    "width": int(self.image_width.get()),
                    "height": int(self.image_height.get()),
                    "steps": int(self.image_steps.get()),
                    "seed": seed,
                },
                project,
                self.current_conversation_id,
            )
        except Exception as error:
            self._show_error(error)
            return
        self._set_status(f"DRAW RUNNING // {task['id'][-8:]}")
        self.tabs.select(self.agents_tab)

    def toggle_adaptive(self) -> None:
        try:
            self.app.update_settings(
                {
                    "adaptive_performance": self.adaptive_var.get(),
                    "performance_memory_threshold": 90,
                }
            )
        except Exception as error:
            self._show_error(error)
            return
        self._set_status(
            "PERFORMANCE BOOST ARMED // AC + RAM >= 90%"
            if self.adaptive_var.get()
            else "PERFORMANCE BOOST DISABLED"
        )

    def toggle_crawler(self) -> None:
        try:
            self.app.update_settings({"crawler_enabled": self.crawler_var.get()})
        except Exception as error:
            self._show_error(error)
            return
        self._set_status(
            "本機研究已啟用：自動擷取指令中的公開網址並遵守 robots.txt"
            if self.crawler_var.get()
            else "本機自動研究已停用"
        )

    def refresh_system(self) -> None:
        try:
            snapshot = self.app.hardware.snapshot()
        except Exception as error:
            self._set_status(f"SYSTEM PROBE ERROR // {error}")
            return
        memory = snapshot.get("memory") or {}
        disk = snapshot.get("disk") or {}
        power = snapshot.get("power") or {}
        try:
            admin = bool(ctypes.windll.shell32.IsUserAnAdmin()) if os.name == "nt" else False
        except OSError:
            admin = False
        access = "FULL" if self.app.full_access_unlocked() else "WORKSPACE"
        boost = "BOOST" if snapshot.get("performance_boost_active") else "NORMAL"
        self.header_state.set(
            f"CPU {snapshot.get('cpu_percent', 0):.0f}%  //  RAM {memory.get('percent', 0)}%  //  "
            f"DISK {disk.get('free_gb', 0):.1f}G FREE  //  {'AC' if power.get('ac_connected') else 'BAT'}  //  "
            f"{'ADMIN' if admin else 'USER'} · {access} · {boost}"
        )

    def force_refresh(self) -> None:
        self.message_signature = None
        self.task_signature = None
        self.refresh_messages()
        self.refresh_tasks()
        self._reload_projects()
        self.refresh_providers(True)
        self.refresh_models()
        self.reload_schedules()
        self.refresh_comfy()
        self.refresh_system()

    def _refresh_loop(self) -> None:
        if self.closing:
            return
        self._tick += 1
        try:
            self.refresh_messages()
            self.refresh_tasks()
            if self._tick % 2 == 0:
                self.refresh_system()
            if self._tick % 20 == 0:
                self.reload_schedules()
            if self._tick % 30 == 0:
                self.refresh_providers(True)
        except Exception as error:
            self._set_status(f"REFRESH ERROR // {error}")
        self.root.after(1000, self._refresh_loop)

    def close(self) -> None:
        active = self.app.database.list_tasks(active_only=True, limit=100)
        if active and not messagebox.askyesno(
            "關閉 AI Hub",
            f"目前有 {len(active)} 個工作仍在執行。關閉會停止這些工作與排程，確定嗎？",
            icon="warning",
            parent=self.root,
        ):
            return
        self.closing = True
        for task in active:
            self.app.tasks.cancel(task["id"])
        self.app.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    args = parse_args()
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AIHub.Local.ControlDeck")
        except (AttributeError, OSError):
            pass
    root = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    app = AIHubApplication(root)
    if args.self_test:
        if args.max_control:
            app.unlock_full_access(FULL_ACCESS_PHRASE, 240)
        payload = {
            "native_ui": "tkinter",
            "tk_version": tk.TkVersion,
            "fts5": bool(getattr(app.database, "_fts_enabled", False)),
            "full_access": app.full_access_unlocked(),
            "project_count": len(app.database.list_projects()),
            "conversation_count": len(app.database.list_conversations()),
            "search_probe": len(app.database.search("AI Hub", 5)),
        }
        print(json.dumps(payload, ensure_ascii=False))
        app.stop()
        return 0
    AIHubDesktop(app, max_control=args.max_control).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
