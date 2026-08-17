"""KakaoTalk Agent 运维面板 - 现代化设计 v2."""
import os
import sys
import subprocess
import threading
import time
import traceback
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Optional
from pathlib import Path

try:
    import requests
except ImportError:
    print("Please install requests: pip install requests")
    sys.exit(1)

try:
    from kakao_mcp.controller import is_kakaotalk_running as _win32_kakao_check
except ImportError:
    _win32_kakao_check = None

from kakao_mcp.envfile import load_env_file, save_env_file, default_env_path, AGENT_ENV_KEYS

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "8765"
POLL_INTERVAL_MS = 3000

_ENVKEY_TO_FIELD = {
    "KAKAO_AGENT_HOST": "host_var",
    "KAKAO_AGENT_PORT": "port_var",
    "KAKAO_AGENT_API_KEY": "api_key_var",
    "KAKAO_AGENT_ALLOW_IPS": "allow_ips_var",
    "KAKAO_AGENT_WEBHOOK_URL": "webhook_var",
}
_FIELD_TO_ENVKEY = {v: k for k, v in _ENVKEY_TO_FIELD.items()}

# ======================================================================
# 现代化配色方案
# ======================================================================
# 深色顶栏
COLOR_NAVY = "#0F172A"
COLOR_NAVY_LIGHT = "#1E293B"
# 主背景
COLOR_BG = "#F1F5F9"
# 卡片
COLOR_CARD = "#FFFFFF"
COLOR_CARD_HOVER = "#F8FAFC"
# 边框
COLOR_BORDER = "#E2E8F0"
COLOR_BORDER_LIGHT = "#F1F5F9"
# 文字
COLOR_TEXT = "#0F172A"
COLOR_TEXT_SEC = "#475569"
COLOR_TEXT_MUTE = "#94A3B8"
# 强调色
COLOR_BLUE = "#3B82F6"
COLOR_BLUE_DARK = "#2563EB"
COLOR_GREEN = "#22C55E"
COLOR_GREEN_DARK = "#16A34A"
COLOR_RED = "#EF4444"
COLOR_RED_DARK = "#DC2626"
COLOR_AMBER = "#F59E0B"
COLOR_PURPLE = "#8B5CF6"
# 终端
COLOR_TERMINAL_BG = "#0F172A"
COLOR_TERMINAL_FG = "#E2E8F0"

FONT = "Segoe UI"
FONT_MONO = "Consolas"

# 状态色映射
STATUS_COLORS = {
    "running": COLOR_GREEN,
    "stopped": COLOR_RED,
    "warning": COLOR_AMBER,
    "unknown": COLOR_TEXT_MUTE,
}


class StatusBar(tk.Canvas):
    """顶部深色导航栏，包含 logo + 标题 + 刷新按钮."""

    def __init__(self, parent, on_refresh=None):
        super().__init__(parent, height=56, bg=COLOR_NAVY, highlightthickness=0)
        self.pack(fill=tk.X)

        # Logo 圆圈
        self.create_oval(20, 10, 46, 36, fill=COLOR_GREEN, outline="")
        self.create_text(33, 23, text="KT", font=(FONT, 11, "bold"), fill="white")

        # 标题
        self.create_text(58, 23, text="KakaoTalk Agent", anchor="w",
                         font=(FONT, 16, "bold"), fill="white")

        # 右侧刷新按钮区域
        btn_frame = tk.Frame(self, bg=COLOR_NAVY)
        self.create_window(self.winfo_reqwidth() - 20, 28, window=btn_frame, anchor="e")

        if on_refresh:
            refresh_btn = tk.Label(btn_frame, text="  刷新  ", bg=COLOR_NAVY_LIGHT,
                                   fg="white", font=(FONT, 10), cursor="hand2",
                                   padx=12, pady=4)
            refresh_btn.pack(side=tk.RIGHT, padx=(0, 8))
            refresh_btn.bind("<Button-1>", lambda e: on_refresh())
            refresh_btn.bind("<Enter>", lambda e: refresh_btn.config(bg=COLOR_BLUE))
            refresh_btn.bind("<Leave>", lambda e: refresh_btn.config(bg=COLOR_NAVY_LIGHT))


class StatusIndicator(tk.Frame):
    """现代化状态指示器卡片."""

    def __init__(self, parent, title: str, subtitle: str = ""):
        super().__init__(parent, bg=COLOR_CARD, highlightbackground=COLOR_BORDER,
                         highlightthickness=1, padx=16, pady=14)

        # 标题行
        top = tk.Frame(self, bg=COLOR_CARD)
        top.pack(fill=tk.X)

        self.dot = tk.Canvas(top, width=14, height=14, bg=COLOR_CARD, highlightthickness=0)
        self.dot.pack(side=tk.LEFT, padx=(0, 10))
        self._draw_dot(COLOR_TEXT_MUTE)

        tk.Label(top, text=title, font=(FONT, 12, "bold"),
                 bg=COLOR_CARD, fg=COLOR_TEXT).pack(side=tk.LEFT)

        # 状态文本
        self.label = tk.Label(self, text=subtitle, font=(FONT, 14, "bold"),
                              bg=COLOR_CARD, fg=COLOR_TEXT_MUTE)
        self.label.pack(anchor="w", pady=(6, 0))

    def _draw_dot(self, color):
        self.dot.delete("all")
        self.dot.create_oval(1, 1, 13, 13, fill=color, outline="")

    def set_status(self, state: str, text: str):
        color = STATUS_COLORS.get(state, COLOR_TEXT_MUTE)
        self._draw_dot(color)
        self.label.config(text=text, fg=color)


class FormField(tk.Frame):
    """单行表单字段: 标签 + 输入框."""

    def __init__(self, parent, label: str, var: tk.StringVar,
                 is_secret=False, hint=None, width=None):
        super().__init__(parent, bg=COLOR_CARD)

        # 标签
        tk.Label(self, text=label, font=(FONT, 10, "bold"),
                 bg=COLOR_CARD, fg=COLOR_TEXT_SEC).pack(anchor="w", pady=(0, 4))

        # 输入框行
        entry_row = tk.Frame(self, bg=COLOR_CARD)
        entry_row.pack(fill=tk.X)

        entry = ttk.Entry(entry_row, textvariable=var, show="*" if is_secret else "")
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        if width:
            entry.config(width=width)

        self._entry = entry

        # Hint
        if hint:
            tk.Label(self, text=hint, font=(FONT, 9),
                     bg=COLOR_CARD, fg=COLOR_TEXT_MUTE).pack(anchor="w", pady=(2, 0))

    @property
    def entry(self):
        return self._entry

    def set_show(self, show: str):
        self._entry.config(show=show)


class SectionHeader(tk.Frame):
    """区域标题栏: 图标 + 标题 + 右侧操作."""

    def __init__(self, parent, title: str, icon=""):
        super().__init__(parent, bg=COLOR_CARD)

        full_title = f"{icon}  {title}" if icon else title
        tk.Label(self, text=full_title, font=(FONT, 12, "bold"),
                 bg=COLOR_CARD, fg=COLOR_TEXT).pack(side=tk.LEFT, pady=(0, 0))


class KakaoAgentGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("KakaoTalk Agent 运维面板")
        self.root.geometry("920x960")
        self.root.minsize(780, 800)
        self.root.configure(bg=COLOR_BG)

        self.process: Optional[subprocess.Popen] = None

        self.host_var = tk.StringVar(value=DEFAULT_HOST)
        self.port_var = tk.StringVar(value=DEFAULT_PORT)
        self.api_key_var = tk.StringVar(value="")
        self.allow_ips_var = tk.StringVar(value="")
        self.webhook_var = tk.StringVar(value="")
        self.show_key_var = tk.BooleanVar(value=False)

        self._setup_style()
        self._create_widgets()
        self._load_config()
        self._refresh_button_states()
        self._schedule_status_poll()

    # ------------------------------------------------------------------
    # Style
    # ------------------------------------------------------------------

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # 通用按钮
        style.configure("TButton", font=(FONT, 11), padding=(14, 7))
        style.configure("Accent.TButton", background=COLOR_GREEN, foreground="white")
        style.map("Accent.TButton",
                  background=[("disabled", "#A5D6A7"), ("active", COLOR_GREEN_DARK)])
        style.configure("Danger.TButton", background=COLOR_RED, foreground="white")
        style.map("Danger.TButton",
                  background=[("disabled", "#FCA5A5"), ("active", COLOR_RED_DARK)])
        style.configure("TEntry", font=(FONT, 11), padding=6)
        style.configure("TCheckbutton", background=COLOR_CARD, font=(FONT, 10))

    # ------------------------------------------------------------------
    # Widgets
    # ------------------------------------------------------------------

    def _create_widgets(self):
        root = self.root

        # ====== 顶部深色导航栏 (pack) ======
        StatusBar(root, on_refresh=self._check_status)

        # ====== 主内容区 (pack 填满剩余) ======
        main = tk.Frame(root, bg=COLOR_BG)
        main.pack(fill=tk.BOTH, expand=True, padx=24, pady=(12, 12))
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=2)  # 运行日志扩展
        main.rowconfigure(3, weight=1)  # 聊天室列表

        # ====== 状态卡片区域 ======
        status_frame = tk.Frame(main, bg=COLOR_BG)
        status_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        status_frame.columnconfigure(0, weight=1)
        status_frame.columnconfigure(1, weight=1)

        self.kakao_card = StatusIndicator(status_frame, "KAKAOTALK", "检测中...")
        self.kakao_card.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.agent_card = StatusIndicator(status_frame, "AGENT HTTP API", "检测中...")
        self.agent_card.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        # ====== 服务配置卡片 ======
        config_card = tk.Frame(main, bg=COLOR_CARD, highlightbackground=COLOR_BORDER,
                               highlightthickness=1)
        config_card.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        config_card.columnconfigure(0, weight=1)

        # 标题
        SectionHeader(config_card, "服务配置", icon="").pack(fill=tk.X, padx=16, pady=(10, 6))

        # 分隔线
        tk.Frame(config_card, height=1, bg=COLOR_BORDER).pack(fill=tk.X, padx=16)

        # 表单区域 - 紧凑布局
        form = tk.Frame(config_card, bg=COLOR_CARD)
        form.pack(fill=tk.X, padx=16, pady=(8, 0))

        # Host + Port 同一行
        hp_row = tk.Frame(form, bg=COLOR_CARD)
        hp_row.pack(fill=tk.X, pady=(0, 6))
        hp_row.columnconfigure(1, weight=1)

        tk.Label(hp_row, text="主机 / 端口", font=(FONT, 10, "bold"),
                 bg=COLOR_CARD, fg=COLOR_TEXT_SEC, width=12, anchor="w").grid(row=0, column=0, sticky="w")

        ttk.Entry(hp_row, textvariable=self.host_var).grid(row=0, column=1, sticky="ew", padx=(0, 4))
        tk.Label(hp_row, text=":", font=(FONT, 12, "bold"),
                 bg=COLOR_CARD, fg=COLOR_TEXT_MUTE).grid(row=0, column=2, padx=(2, 2))
        ttk.Entry(hp_row, textvariable=self.port_var, width=8).grid(row=0, column=3, sticky="w")

        # API Key
        key_row = tk.Frame(form, bg=COLOR_CARD)
        key_row.pack(fill=tk.X, pady=(0, 6))
        key_row.columnconfigure(1, weight=1)

        tk.Label(key_row, text="API 密钥", font=(FONT, 10, "bold"),
                 bg=COLOR_CARD, fg=COLOR_TEXT_SEC, width=12, anchor="w").grid(row=0, column=0, sticky="w")
        key_entry = ttk.Entry(key_row, textvariable=self.api_key_var, show="*")
        key_entry.grid(row=0, column=1, sticky="ew")
        self._api_key_entry = key_entry

        tk.Checkbutton(key_row, text="显示", variable=self.show_key_var,
                       command=self._toggle_api_key, bg=COLOR_CARD, font=(FONT, 10),
                       fg=COLOR_TEXT_MUTE, selectcolor=COLOR_CARD,
                       activebackground=COLOR_CARD).grid(row=0, column=2, padx=(8, 0))

        # Allow IPs
        ip_row = tk.Frame(form, bg=COLOR_CARD)
        ip_row.pack(fill=tk.X, pady=(0, 6))
        ip_row.columnconfigure(1, weight=1)

        tk.Label(ip_row, text="允许 IP", font=(FONT, 10, "bold"),
                 bg=COLOR_CARD, fg=COLOR_TEXT_SEC, width=12, anchor="w").grid(row=0, column=0, sticky="w")
        ttk.Entry(ip_row, textvariable=self.allow_ips_var).grid(row=0, column=1, sticky="ew")
        tk.Label(ip_row, text="逗号分隔", font=(FONT, 9),
                 bg=COLOR_CARD, fg=COLOR_TEXT_MUTE).grid(row=0, column=2, padx=(8, 0))

        # Webhook
        wh_row = tk.Frame(form, bg=COLOR_CARD)
        wh_row.pack(fill=tk.X, pady=(0, 8))
        wh_row.columnconfigure(1, weight=1)

        tk.Label(wh_row, text="Webhook", font=(FONT, 10, "bold"),
                 bg=COLOR_CARD, fg=COLOR_TEXT_SEC, width=12, anchor="w").grid(row=0, column=0, sticky="w")
        ttk.Entry(wh_row, textvariable=self.webhook_var).grid(row=0, column=1, sticky="ew")

        # 分隔线
        tk.Frame(config_card, height=1, bg=COLOR_BORDER).pack(fill=tk.X, padx=16)

        # 按钮行
        btn_frame = tk.Frame(config_card, bg=COLOR_CARD)
        btn_frame.pack(fill=tk.X, padx=16, pady=(8, 12))

        save_btn = tk.Label(btn_frame, text="  保存配置  ", bg=COLOR_BG,
                            fg=COLOR_TEXT_SEC, font=(FONT, 11), cursor="hand2",
                            padx=14, pady=5, relief="flat")
        save_btn.pack(side=tk.LEFT, padx=(0, 8))
        save_btn.bind("<Button-1>", lambda e: self._save_config())
        save_btn.bind("<Enter>", lambda e: save_btn.config(bg=COLOR_BORDER))
        save_btn.bind("<Leave>", lambda e: save_btn.config(bg=COLOR_BG))

        self.start_btn = tk.Label(btn_frame, text="  启动服务  ", bg=COLOR_GREEN,
                                  fg="white", font=(FONT, 11, "bold"), cursor="hand2",
                                  padx=14, pady=5)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.start_btn.bind("<Button-1>", lambda e: self._start_agent())
        self.start_btn.bind("<Enter>", lambda e: self.start_btn.config(bg=COLOR_GREEN_DARK))
        self.start_btn.bind("<Leave>", lambda e: self.start_btn.config(bg=COLOR_GREEN))

        self.stop_btn = tk.Label(btn_frame, text="  停止服务  ", bg=COLOR_RED,
                                 fg="white", font=(FONT, 11, "bold"), cursor="hand2",
                                 padx=14, pady=5)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.stop_btn.bind("<Button-1>", lambda e: self._stop_agent())
        self.stop_btn.bind("<Enter>", lambda e: self.stop_btn.config(bg=COLOR_RED_DARK))
        self.stop_btn.bind("<Leave>", lambda e: self.stop_btn.config(bg=COLOR_RED))

        # ====== 聊天室列表卡片 ======
        rooms_card = tk.Frame(main, bg=COLOR_CARD, highlightbackground=COLOR_BORDER,
                              highlightthickness=1)
        rooms_card.grid(row=3, column=0, sticky="nsew", pady=(0, 8))

        rooms_header = tk.Frame(rooms_card, bg=COLOR_CARD)
        rooms_header.pack(fill=tk.X, padx=16, pady=(10, 6))

        tk.Label(rooms_header, text="聊天室列表", font=(FONT, 12, "bold"),
                 bg=COLOR_CARD, fg=COLOR_TEXT).pack(side=tk.LEFT)

        refresh_rooms = tk.Label(rooms_header, text="刷新", bg=COLOR_BG,
                                 fg=COLOR_BLUE, font=(FONT, 10, "bold"), cursor="hand2",
                                 padx=10, pady=3)
        refresh_rooms.pack(side=tk.RIGHT)
        refresh_rooms.bind("<Button-1>", lambda e: self._refresh_rooms())
        refresh_rooms.bind("<Enter>", lambda e: refresh_rooms.config(fg=COLOR_BLUE_DARK))
        refresh_rooms.bind("<Leave>", lambda e: refresh_rooms.config(fg=COLOR_BLUE))

        self.room_listbox = tk.Listbox(rooms_card, font=(FONT, 11),
                                       relief="flat", bg=COLOR_BG, fg=COLOR_TEXT,
                                       activestyle="dotbox", highlightbackground=COLOR_BORDER,
                                       highlightthickness=1, selectbackground=COLOR_BLUE,
                                       selectforeground="white", borderwidth=0)
        self.room_listbox.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 10))

        # ====== 运行日志卡片 ======
        log_card = tk.Frame(main, bg=COLOR_CARD, highlightbackground=COLOR_BORDER,
                            highlightthickness=1)
        log_card.grid(row=2, column=0, sticky="nsew", pady=(0, 8))

        log_header = tk.Frame(log_card, bg=COLOR_CARD)
        log_header.pack(fill=tk.X, padx=16, pady=(10, 6))
        tk.Label(log_header, text="运行日志", font=(FONT, 12, "bold"),
                 bg=COLOR_CARD, fg=COLOR_TEXT).pack(side=tk.LEFT)

        self.log_text = scrolledtext.ScrolledText(log_card,
                                                  font=(FONT_MONO, 10),
                                                  state="disabled", relief="flat",
                                                  bg=COLOR_TERMINAL_BG,
                                                  fg=COLOR_TERMINAL_FG,
                                                  insertbackground=COLOR_TERMINAL_FG,
                                                  selectbackground=COLOR_BLUE,
                                                  selectforeground="white",
                                                  borderwidth=0, padx=12, pady=8)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 10))

        # 日志颜色
        self.log_text.tag_config("info", foreground="#CBD5E1")
        self.log_text.tag_config("ok", foreground=COLOR_GREEN)
        self.log_text.tag_config("error", foreground=COLOR_RED)
        self.log_text.tag_config("proc", foreground=COLOR_PURPLE)
        self.log_text.tag_config("warn", foreground=COLOR_AMBER)
        self.log_text.tag_config("ts", foreground="#64748B")

    def _toggle_api_key(self):
        show = "" if self.show_key_var.get() else "*"
        self._api_key_entry.config(show=show)

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _config_path(self) -> Path:
        return default_env_path()

    def _save_config(self):
        env_path = self._config_path()
        agent_running = bool(self.process and self.process.poll() is None)

        values = {
            "KAKAO_AGENT_HOST": self.host_var.get().strip(),
            "KAKAO_AGENT_PORT": self.port_var.get().strip(),
            "KAKAO_AGENT_API_KEY": self.api_key_var.get().strip(),
            "KAKAO_AGENT_ALLOW_IPS": self.allow_ips_var.get().strip(),
            "KAKAO_AGENT_WEBHOOK_URL": self.webhook_var.get().strip(),
        }
        try:
            save_env_file(values, path=env_path)
            self._log(f"配置已保存: {env_path}", "ok")
            if agent_running:
                messagebox.showinfo(
                    "需重启生效",
                    "Agent 正在运行，配置已保存。\n请停止并重新启动 Agent 使新配置生效。",
                )
        except OSError as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")

    def _load_config(self):
        env_path = self._config_path()
        if not env_path.is_file():
            return
        try:
            env_vars = load_env_file(env_path)
            for envkey, field_name in _ENVKEY_TO_FIELD.items():
                var = getattr(self, field_name, None)
                if var is not None and envkey in env_vars:
                    var.set(env_vars[envkey])
            self._log(f"已加载配置: {env_path}", "info")
        except (OSError, ValueError) as e:
            self._log(f"读取配置失败: {e}", "error")

    # ------------------------------------------------------------------
    # Agent process control
    # ------------------------------------------------------------------

    def _start_agent(self):
        if self.process and self.process.poll() is None:
            messagebox.showwarning("提示", "Agent 已经在运行")
            return

        host = self.host_var.get().strip()
        port = self.port_var.get().strip()
        api_key = self.api_key_var.get().strip()

        if not api_key:
            messagebox.showerror("错误", "API Key 不能为空")
            return

        try:
            port_int = int(port)
            if not (1 <= port_int <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "Port 必须是 1-65535 的整数")
            return

        if host not in ("127.0.0.1", "::1", "localhost") and not self.allow_ips_var.get().strip():
            messagebox.showerror("错误", "非本机监听时必须填写 Allow IPs")
            return

        env = os.environ.copy()
        env["KAKAO_AGENT_HOST"] = host
        env["KAKAO_AGENT_PORT"] = port
        env["KAKAO_AGENT_API_KEY"] = api_key
        if self.allow_ips_var.get().strip():
            env["KAKAO_AGENT_ALLOW_IPS"] = self.allow_ips_var.get().strip()
        if self.webhook_var.get().strip():
            env["KAKAO_AGENT_WEBHOOK_URL"] = self.webhook_var.get().strip()

        cmd = [sys.executable, "-m", "kakao_mcp.api"]

        try:
            self.process = subprocess.Popen(
                cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
        except OSError as e:
            self.process = None
            messagebox.showerror("启动失败", f"{e}")
            return

        self._log("KakaoTalk Agent 启动中...", "info")
        self.agent_card.set_status("warning", "启动中...")
        self._refresh_button_states()
        threading.Thread(target=self._poll_process, daemon=True).start()

    def _stop_agent(self):
        proc = self.process
        if proc and proc.poll() is None:
            self._log("正在停止 Agent...", "info")
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._log("强制终止进程...", "warn")
                proc.kill()
        self.process = None
        self.agent_card.set_status("stopped", "已停止")
        self._log("Agent 已停止", "ok")
        self._refresh_button_states()

    def _poll_process(self):
        proc = self.process
        if not proc:
            return
        for line in iter(proc.stdout.readline, ""):
            line = line.strip()
            if line:
                self._safe_log(f"[进程] {line}", "proc")
        return_code = proc.wait()
        self._safe_log(f"进程退出，返回码: {return_code}", "warn")
        if self.process is proc:
            self.process = None
            self.agent_card.set_status("stopped", "已停止")
            self._refresh_button_states()

    def _refresh_button_states(self):
        running = bool(self.process and self.process.poll() is None)
        if running:
            self.start_btn.config(state="disabled", bg="#A5D6A7", cursor="")
            self.stop_btn.config(state="normal", cursor="hand2")
        else:
            self.start_btn.config(state="normal", cursor="hand2")
            self.stop_btn.config(state="disabled", bg="#FCA5A5", cursor="")

    # ------------------------------------------------------------------
    # Status / HTTP
    # ------------------------------------------------------------------

    def _schedule_status_poll(self):
        self._check_status()
        self.root.after(POLL_INTERVAL_MS, self._schedule_status_poll)

    def _check_status(self):
        threading.Thread(target=self._check_agent_status_async, daemon=True).start()
        threading.Thread(target=self._check_kakao_status_async, daemon=True).start()

    def _check_agent_status_async(self):
        response = self._request("GET", "/health")
        if response is not None and response.get("success"):
            self.agent_card.set_status("running", "运行中")
        elif self.process and self.process.poll() is None:
            self.agent_card.set_status("warning", "启动中...")
        else:
            self.agent_card.set_status("stopped", "已停止")

    def _check_kakao_status_async(self):
        if _win32_kakao_check is None:
            self.kakao_card.set_status("unknown", "无法检测")
            return
        try:
            info = _win32_kakao_check()
            is_running = bool(info.get("running"))
        except Exception as e:
            self._safe_log(f"KakaoTalk 状态检查失败: {e}", "error")
            is_running = None

        if is_running:
            self.kakao_card.set_status("running", "运行中")
        else:
            self.kakao_card.set_status("stopped", "未运行")

    def _request(self, method: str, path: str, **kwargs) -> Optional[dict]:
        host = self.host_var.get().strip()
        port = self.port_var.get().strip()
        api_key = self.api_key_var.get().strip()

        if not api_key:
            return None

        url = f"http://{host}:{port}{path}"
        headers = {"X-API-Key": api_key}
        timeout = kwargs.pop("timeout", 5)

        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=timeout)
            elif method == "POST":
                resp = requests.post(url, headers=headers, json=kwargs.get("json", {}), timeout=timeout)
            else:
                return None
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException as e:
            self._safe_log(f"请求失败: {e}", "error")
        return None

    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------

    def _refresh_rooms(self):
        threading.Thread(target=self._refresh_rooms_async, daemon=True).start()

    def _refresh_rooms_async(self):
        response = self._request("GET", "/rooms")
        if response is None:
            self._safe_log("获取聊天室失败", "error")
            return

        def _apply():
            self.room_listbox.delete(0, tk.END)
            rooms = response.get("rooms", [])
            for room in rooms:
                self.room_listbox.insert(tk.END, room.get("title", "Unknown"))
            if not rooms:
                self.room_listbox.insert(tk.END, "(没有已打开的聊天室)")

        self.root.after(0, _apply)

    # ------------------------------------------------------------------
    # Thread-safe UI helpers
    # ------------------------------------------------------------------

    def _safe_log(self, message: str, level: str = "info"):
        self.root.after(0, lambda m=message, lv=level: self._log(m, lv))

    def _log(self, message: str, level: str = "info"):
        tag = level if level in ("info", "ok", "error", "proc", "warn") else "info"
        self.log_text.config(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] ", "ts")
        self.log_text.insert(tk.END, f"{message}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")


def main():
    try:
        root = tk.Tk()
        KakaoAgentGUI(root)
        root.mainloop()
    except Exception:
        traceback.print_exc()
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
