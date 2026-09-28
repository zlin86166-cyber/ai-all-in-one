"""Lightweight dimensional Tk surfaces; no GPU or animation loop required."""
import tkinter as tk
from tkinter import ttk


class DepthCard(tk.Frame):
    def __init__(self, parent, *, surface="#0B0B0D", padding=14, **kwargs):
        super().__init__(parent, bg="#202124", **kwargs)
        self.body = tk.Frame(self, bg=surface, bd=1, relief=tk.FLAT,
                             highlightthickness=1, highlightbackground="#25272A")
        self.body.pack(fill=tk.BOTH, expand=True, padx=(0, 5), pady=(0, 6))
        self.content = ttk.Frame(self.body, style="Card.TFrame", padding=padding)
        self.content.pack(fill=tk.BOTH, expand=True)


class DepthMark(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, width=76, height=76, bg="#0B0B0D",
                         highlightthickness=0, takefocus=0)
        self.create_oval(10, 58, 69, 71, fill="#1A1C1F", outline="")
        self.create_polygon(38, 8, 66, 23, 38, 39, 10, 23,
                            fill="#A4F0E2", outline="#65D9E7")
        self.create_polygon(10, 23, 38, 39, 38, 66, 10, 50,
                            fill="#147C75", outline="#32B8A8")
        self.create_polygon(38, 39, 66, 23, 66, 50, 38, 66,
                            fill="#1A6258", outline="#65D9E7")
        self.create_line(38, 39, 38, 65, fill="#B8F5E9", width=2)


def apply_depth_styles(style):
    style.configure("Card.TFrame", background="#0B0B0D")
    style.configure("Card.TLabel", background="#0B0B0D", foreground="#A2A6AC")
    style.configure("CardTitle.TLabel", background="#0B0B0D", foreground="#ECEDEF",
                    font=("Microsoft JhengHei UI", 19, "bold"))
    style.configure("TButton", relief="flat", borderwidth=1,
                    lightcolor="#202124", darkcolor="#151619", padding=(12, 8))
    style.map("TButton", relief=[("pressed", "sunken"), ("!pressed", "flat")],
              background=[("disabled", "#17181A"), ("pressed", "#1A1C1F"), ("active", "#202226")])
    style.configure("TNotebook", padding=6)
    style.configure("TNotebook.Tab", padding=(12, 10), borderwidth=2)
    style.configure("Treeview", rowheight=32)
    style.configure("TLabelframe", relief="groove", borderwidth=2)
