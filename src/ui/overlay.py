import tkinter as tk
from tkinter import ttk
import ctypes
from ctypes import wintypes
import threading
from typing import Optional, Callable, List, Tuple


user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20
WS_EX_NOACTIVATE = 0x8000000
WS_EX_TOPMOST = 0x8
LWA_ALPHA = 0x2
SWP_NOSIZE = 0x1
SWP_NOMOVE = 0x2
SWP_NOACTIVATE = 0x10
HWND_TOPMOST = -1


class OverlayWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#1a1a1a")

        self._hwnd = None
        self._setup_window()

        self._current_en = ""
        self._current_es = ""
        self._pending_english = ""
        self._pending_spanish = ""
        self._last_shown_en = ""
        self._last_shown_es = ""
        self._fade_job = None
        self._last_update_id = 0

        self._build_subtitle_ui()

        self.settings_visible = False
        self.settings_frame = None
        self.device_combo = None
        self.start_btn = None
        self.device_list: List[Tuple[int, str, bool]] = []
        self.on_start_callback: Optional[Callable] = None
        self.on_device_change_callback: Optional[Callable[[int], None]] = None

        self.root.protocol("WM_DELETE_WINDOW", self.hide)

    def _build_subtitle_ui(self):
        self._sub_container = tk.Frame(self.root, bg="#222222")
        self._sub_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._sub_container.pack_forget()

        self._en_label = tk.Label(
            self._sub_container,
            text="",
            font=("Segoe UI", 13),
            fg="#b0b0b0",
            bg="#222222",
            wraplength=760,
            justify="center",
            anchor="center",
        )
        self._en_label.pack(fill=tk.X, padx=10, pady=(6, 2))

        self._sep_line = tk.Frame(self._sub_container, bg="#444444", height=1)
        self._sep_line.pack(fill=tk.X, padx=20, pady=2)

        self._es_label = tk.Label(
            self._sub_container,
            text="",
            font=("Segoe UI", 18, "bold"),
            fg="white",
            bg="#222222",
            wraplength=760,
            justify="center",
            anchor="center",
        )
        self._es_label.pack(fill=tk.X, padx=10, pady=(2, 6))

    def _setup_window(self):
        self.root.update_idletasks()
        self._hwnd = self.root.winfo_id()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        w, h = 800, 140
        x = (screen_w - w) // 2
        y = screen_h - h - 80
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _make_click_through(self):
        if self._hwnd:
            ex_style = user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
            ex_style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOPMOST
            user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, ex_style)
            user32.SetLayeredWindowAttributes(self._hwnd, 0, 217, LWA_ALPHA)
            user32.SetWindowPos(
                self._hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
            )

    def _remove_click_through(self):
        if self._hwnd:
            ex_style = user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
            ex_style &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            ex_style |= WS_EX_LAYERED | WS_EX_TOPMOST
            user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, ex_style)
            user32.SetLayeredWindowAttributes(self._hwnd, 0, 242, LWA_ALPHA)

    def show_settings_first(self):
        self.root.deiconify()
        self._remove_click_through()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self._show_settings()

    def hide(self):
        self.root.withdraw()

    def _show_settings(self):
        self.settings_visible = True
        self.root.attributes("-alpha", 0.95)
        self.root.overrideredirect(False)
        self.root.attributes("-topmost", True)

        self.settings_frame = tk.Frame(self.root, bg="#1a1a1a")
        self.settings_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        tk.Label(
            self.settings_frame, text="TradNemo - Configuración",
            font=("Segoe UI", 20, "bold"), fg="white", bg="#1a1a1a"
        ).pack(pady=(0, 15))

        tk.Label(
            self.settings_frame, text="Dispositivo de audio:",
            font=("Segoe UI", 12), fg="#cccccc", bg="#1a1a1a"
        ).pack(anchor="w")

        self.device_combo = ttk.Combobox(
            self.settings_frame, state="readonly", width=50, font=("Segoe UI", 11)
        )
        self.device_combo.pack(fill=tk.X, pady=(5, 15))
        self.device_combo.bind("<<ComboboxSelected>>", self._on_device_selected)

        self.start_btn = tk.Button(
            self.settings_frame, text="Iniciar captura",
            font=("Segoe UI", 12, "bold"), bg="#0078d4", fg="white",
            relief=tk.FLAT, padx=20, pady=10, cursor="hand2",
            command=self._on_start_click
        )
        self.start_btn.pack(pady=10)

        self._update_devices()
        self.root.geometry("")

    def hide_settings_and_show_overlay(self):
        self.settings_visible = False
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", 0.85)
        if self.settings_frame:
            self.settings_frame.destroy()
            self.settings_frame = None
        self._sub_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._make_click_through()
        self._setup_window()

    def _update_devices(self):
        if self.device_combo:
            names = [f"{'✓ ' if d[2] else ''}{d[1]}" for d in self.device_list]
            self.device_combo["values"] = names
            if names:
                default_idx = next((i for i, d in enumerate(self.device_list) if d[2]), 0)
                self.device_combo.current(default_idx)

    def set_devices(self, devices: List[Tuple[int, str, bool]]):
        self.device_list = devices
        if self.root:
            self.root.after(0, self._update_devices)

    def _on_device_selected(self, event):
        idx = self.device_combo.current()
        if idx >= 0 and self.on_device_change_callback:
            self.on_device_change_callback(self.device_list[idx][0])

    def _on_start_click(self):
        if self.start_btn:
            self.start_btn.config(text="Iniciado", state=tk.DISABLED, bg="#107c10")
        if self.on_start_callback:
            self.on_start_callback()

    def update_subtitle(self, english: str, spanish: str):
        if self.root:
            self._last_update_id += 1
            update_id = self._last_update_id
            self._pending_english = english
            self._pending_spanish = spanish
            if self._fade_job:
                self.root.after_cancel(self._fade_job)
            self._fade_job = self.root.after(30, lambda: self._do_update_subtitle(update_id))

    def _do_update_subtitle(self, update_id: int):
        if update_id != self._last_update_id:
            return

        english = self._pending_english
        spanish = self._pending_spanish

        new_en = english.strip()
        new_es = spanish.strip()

        if new_en == self._last_shown_en and new_es == self._last_shown_es:
            return

        self._current_en = new_en
        self._current_es = new_es
        self._last_shown_en = new_en
        self._last_shown_es = new_es

        self._en_label.config(text=self._current_en)
        self._es_label.config(text=self._current_es)

        has_content = bool(self._current_en or self._current_es)
        if has_content:
            self._sub_container.config(bg="#222222")
            self._en_label.config(bg="#222222")
            self._sep_line.config(bg="#444444")
            self._es_label.config(bg="#222222")
        else:
            self._sub_container.config(bg="#1a1a1a")
            self._en_label.config(bg="#1a1a1a")
            self._sep_line.config(bg="#1a1a1a")
            self._es_label.config(bg="#1a1a1a")

    def clear_subtitle(self):
        if self.root:
            self._last_update_id += 1
            update_id = self._last_update_id
            if self._fade_job:
                self.root.after_cancel(self._fade_job)
                self._fade_job = None
            self.root.after(0, lambda: self._do_clear_subtitle(update_id))

    def _do_clear_subtitle(self, update_id: int):
        if update_id != self._last_update_id:
            return
        self._current_en = ""
        self._current_es = ""
        self._last_shown_en = ""
        self._last_shown_es = ""
        self._en_label.config(text="")
        self._es_label.config(text="")
        self._sub_container.config(bg="#1a1a1a")
        self._en_label.config(bg="#1a1a1a")
        self._sep_line.config(bg="#1a1a1a")
        self._es_label.config(bg="#1a1a1a")

    def set_start_callback(self, cb: Callable):
        self.on_start_callback = cb

    def set_device_change_callback(self, cb: Callable[[int], None]):
        self.on_device_change_callback = cb

    def run(self):
        self.root.mainloop()