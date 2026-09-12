"""Lightweight dimensional Tk surfaces; no GPU or animation loop required."""
import tkinter as tk
from tkinter import ttk


class DepthCard(tk.Frame):
    def __init__(self, parent, *, surface="#FFFFFF", padding=14, **kwargs):
        super().__init__(parent, bg="#D1DAEB", **kwargs)
        self.body = tk.Frame(self, bg=surface, bd=1, relief=tk.RAISED,
                             highlightthickness=1, highlightbackground="#FFFFFF")
        self.body.pack(fill=tk.BOTH, expand=True, padx=(0, 5), pady=(0, 6))
        self.content = ttk.Frame(self.body, style="Card.TFrame", padding=padding)
        self.content.pack(fill=tk.BOTH, expand=True)


class DepthMark(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, width=76, height=76, bg="#FFFFFF",
                         highlightthickness=0, takefocus=0)
        self.create_oval(10, 58, 69, 71, fill="#E0E7F4", outline="")
        self.create_polygon(38, 8, 66, 23, 38, 39, 10, 23,
                            fill="#A5B4FC", outline="#C7D2FE")
        self.create_polygon(10, 23, 38, 39, 38, 66, 10, 50,
                            fill="#4F46E5", outline="#6366F1")
        self.create_polygon(38, 39, 66, 23, 66, 50, 38, 66,
                            fill="#2563EB", outline="#60A5FA")
        self.create_line(38, 39, 38, 65, fill="#BFDBFE", width=2)


def apply_depth_styles(style):
    style.configure("Card.TFrame", background="#FFFFFF")
    style.configure("Card.TLabel", background="#FFFFFF", foreground="#475569")
    style.configure("CardTitle.TLabel", background="#FFFFFF", foreground="#172554",
                    font=("Microsoft JhengHei UI", 19, "bold"))
    style.configure("TButton", relief="raised", borderwidth=2,
                    lightcolor="#FFFFFF", darkcolor="#BCC9DF", padding=(12, 8))
    style.map("TButton", relief=[("pressed", "sunken"), ("!pressed", "raised")],
              background=[("disabled", "#E2E8F0"), ("pressed", "#DCE6FA"), ("active", "#EFF6FF")])
    style.configure("TNotebook", padding=6)
    style.configure("TNotebook.Tab", padding=(12, 10), borderwidth=2)
    style.configure("Treeview", rowheight=32)
    style.configure("TLabelframe", relief="groove", borderwidth=2)
