import tkinter as tk
from tkinter import ttk
import ctypes
from ctypes import wintypes
import threading
import math
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

        self._base_w = 800
        self._single_h = 100
        self._base_font_en = 13
        self._base_font_es = 13
        self._min_w = 300
        self._min_h = 60
        self._edge_size = 8
        self._user_resized = False
        self._saved_w = None
        self._saved_h = None

        self._current_en = ""
        self._current_es = ""
        self._last_shown_en = ""
        self._last_shown_es = ""
        self._fade_job = None
        self._last_update_id = 0
        self._hide_job = None
        self._min_display_ms = 3000
        self._show_time = 0
        self._min_display_job = None

        self._resize_data = {"active": False, "edge": None, "start_x": 0, "start_y": 0, "start_geo": None}

        self._build_subtitle_ui()
        self._setup_window()

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
        self._sub_container.pack(fill=tk.BOTH, expand=True)
        self._sub_container.pack_forget()

        self._en_label = tk.Label(
            self._sub_container, text="",
            font=("Segoe UI", self._base_font_en),
            fg="#b0b0b0", bg="#222222",
            wraplength=760, justify="center", anchor="center",
        )
        self._en_label.pack(fill=tk.X, padx=12, pady=(8, 1))

        self._sep_line = tk.Frame(self._sub_container, bg="#444444", height=1)
        self._sep_line.pack(fill=tk.X, padx=30, pady=2)

        self._es_label = tk.Label(
            self._sub_container, text="",
            font=("Segoe UI", self._base_font_es, "bold"),
            fg="white", bg="#222222",
            wraplength=760, justify="center", anchor="center",
        )
        self._es_label.pack(fill=tk.X, padx=12, pady=(1, 8))

        self._drag_data = {"x": 0, "y": 0}
        self._sub_container.bind("<Button-1>", self._on_press)
        self._sub_container.bind("<B1-Motion>", self._on_motion)
        self._sub_container.bind("<ButtonRelease-1>", self._on_release)
        self._sub_container.bind("<Motion>", self._on_motion_hover)

    def _get_edge(self, x, y):
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        e = self._edge_size
        on_left = x < e
        on_right = x > w - e
        on_top = y < e
        on_bottom = y > h - e

        if on_top and on_left:
            return "nw"
        if on_top and on_right:
            return "ne"
        if on_bottom and on_left:
            return "sw"
        if on_bottom and on_right:
            return "se"
        if on_top:
            return "n"
        if on_bottom:
            return "s"
        if on_left:
            return "w"
        if on_right:
            return "e"
        return None

    def _edge_to_cursor(self, edge):
        cursors = {
            "nw": "top_left_corner", "ne": "top_right_corner",
            "sw": "bottom_left_corner", "se": "bottom_right_corner",
            "n": "sb_v_double_arrow", "s": "sb_v_double_arrow",
            "w": "sb_h_double_arrow", "e": "sb_h_double_arrow",
        }
        return cursors.get(edge, "arrow")

    def _on_motion_hover(self, event):
        if self._resize_data["active"]:
            return
        edge = self._get_edge(event.x, event.y)
        cursor = self._edge_to_cursor(edge) if edge else "fleur"
        self._sub_container.config(cursor=cursor)

    def _on_press(self, event):
        edge = self._get_edge(event.x, event.y)
        if edge:
            self._resize_data = {
                "active": True,
                "edge": edge,
                "start_x": event.x_root,
                "start_y": event.y_root,
                "start_geo": self.root.geometry(),
                "start_w": self.root.winfo_width(),
                "start_h": self.root.winfo_height(),
                "start_rx": self.root.winfo_x(),
                "start_ry": self.root.winfo_y(),
            }
        else:
            self._drag_data["x"] = event.x_root
            self._drag_data["y"] = event.y_root
            self._resize_data["active"] = False

    def _on_motion(self, event):
        if self._resize_data["active"]:
            self._do_resize(event)
        else:
            dx = event.x_root - self._drag_data["x"]
            dy = event.y_root - self._drag_data["y"]
            x = self.root.winfo_x() + dx
            y = self.root.winfo_y() + dy
            self.root.geometry(f"+{x}+{y}")
            self._drag_data["x"] = event.x_root
            self._drag_data["y"] = event.y_root

    def _on_release(self, event):
        if self._resize_data["active"]:
            self._user_resized = True
            self._saved_w = self.root.winfo_width()
            self._saved_h = self.root.winfo_height()
        self._resize_data["active"] = False
        self._resize_data["edge"] = None

    def _do_resize(self, event):
        d = self._resize_data
        edge = d["edge"]
        dx = event.x_root - d["start_x"]
        dy = event.y_root - d["start_y"]

        new_w = d["start_w"]
        new_h = d["start_h"]
        new_x = d["start_rx"]
        new_y = d["start_ry"]

        if "e" in edge:
            new_w = max(self._min_w, d["start_w"] + dx)
        if "w" in edge:
            new_w = max(self._min_w, d["start_w"] - dx)
            new_x = d["start_rx"] + (d["start_w"] - new_w)
        if "s" in edge:
            new_h = max(self._min_h, d["start_h"] + dy)
        if "n" in edge:
            new_h = max(self._min_h, d["start_h"] - dy)
            new_y = d["start_ry"] + (d["start_h"] - new_h)

        self.root.geometry(f"{int(new_w)}x{int(new_h)}+{int(new_x)}+{int(new_y)}")
        self._update_font_size()

    def _update_font_size(self):
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        if w <= 0 or h <= 0:
            return

        scale_w = w / self._base_w
        scale_h = h / self._single_h
        scale = min(scale_w, scale_h)
        scale = max(0.5, min(3.0, scale))

        font_en = max(8, int(self._base_font_en * scale))
        font_es = max(8, int(self._base_font_es * scale))
        wrap = max(200, int(760 * scale))

        self._en_label.config(font=("Segoe UI", font_en), wraplength=wrap)
        self._es_label.config(font=("Segoe UI", font_es, "bold"), wraplength=wrap)

    def _setup_window(self):
        self.root.update_idletasks()
        self._hwnd = self.root.winfo_id()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        w = self._base_w
        h = self._single_h
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
        self.root.geometry("")
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"+{x}+{y}")
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
            self.settings_frame, text="TradNemo - Configuracion",
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
        self._user_resized = False
        self._saved_w = None
        self._saved_h = None
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", 0.85)
        if self.settings_frame:
            self.settings_frame.destroy()
            self.settings_frame = None
        self._sub_container.pack(fill=tk.BOTH, expand=True)
        self._remove_click_through()
        self._setup_window()
        self._update_font_size()
        self.root.bind("<Control-Alt-t>", self._toggle_click_through)
        self.root.bind("<Escape>", self._toggle_click_through)

    def _toggle_click_through(self, event=None):
        if self._hwnd:
            ex_style = user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
            is_click_through = bool(ex_style & WS_EX_TRANSPARENT)
            if is_click_through:
                self._remove_click_through()
            else:
                self._make_click_through()

    def _update_devices(self):
        if self.device_combo and self.settings_frame and self.settings_frame.winfo_exists():
            names = [f"{'[DEFAULT] ' if d[2] else ''}{d[1]}" for d in self.device_list]
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
        if not self.root:
            return
        self.root.after(0, lambda: self._update_subtitle_safe(english, spanish))

    def _update_subtitle_safe(self, english: str, spanish: str):
        self._show_now(english, spanish)

    def _show_now(self, english: str, spanish: str):
        if self._min_display_job:
            self.root.after_cancel(self._min_display_job)
            self._min_display_job = None

        self._current_en = english
        self._current_es = spanish
        self._last_shown_en = english
        self._last_shown_es = spanish
        self._en_label.config(text=english)
        self._es_label.config(text=spanish)
        import time
        self._show_time = int(time.time() * 1000)

        bg = "#222222"
        self._sub_container.config(bg=bg)
        self._en_label.config(bg=bg)
        self._sep_line.config(bg="#444444")
        self._es_label.config(bg=bg)
        self._sub_container.pack(fill=tk.BOTH, expand=True)
        self._min_display_job = self.root.after(self._min_display_ms, self._on_min_display_done)
        self._start_auto_hide_timer()

    def _on_min_display_done(self):
        self._min_display_job = None

    def _start_auto_hide_timer(self):
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
        self._hide_job = self.root.after(45000, self._on_auto_hide)

    def _on_auto_hide(self):
        self._hide_job = None
        self.clear_subtitle()

    def clear_subtitle(self):
        if not self.root:
            return
        self.root.after(0, self._clear_subtitle_safe)

    def _clear_subtitle_safe(self):
        self._current_en = ""
        self._current_es = ""
        self._last_shown_en = ""
        self._last_shown_es = ""
        self._en_label.config(text="")
        self._es_label.config(text="")
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        if self._min_display_job:
            self.root.after_cancel(self._min_display_job)
            self._min_display_job = None
        self._sub_container.pack_forget()

    def set_start_callback(self, cb: Callable):
        self.on_start_callback = cb

    def set_device_change_callback(self, cb: Callable[[int], None]):
        self.on_device_change_callback = cb

    def run(self):
        self.root.mainloop()
