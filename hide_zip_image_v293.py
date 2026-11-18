import os
import sys
import json
import urllib.request
import webbrowser
import threading
import time
import tempfile
from datetime import datetime
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES
from PIL import Image

try:
    import pyzipper
except ImportError:
    pyzipper = None

APP_VERSION = "V2.9.3"
UPDATE_JSON_URL = "https://raw.githubusercontent.com/xinyuwang668-arch/Hide-Zip2Image/main/version.json"
GITHUB_URL = "https://github.com/xinyuwang668-arch/Hide-Zip2Image"
THEME_COLORS = {
    "蓝色": "#3B82F6",
    "绿色": "#10B981",
    "粉色": "#EC4899",
    "深灰": "#374151",
}

SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {
    "auto_check_update": True,
    "auto_open_folder": False,
    "auto_overwrite": False,
    "remember_window": True,
    "remember_theme": True,
    "theme": "蓝色",
    "appearance_mode": "dark",
    "output_mode": "same_folder",
    "default_output_dir": "",
    "last_output_dir": "",
    "window_geometry": "860x850",
    "auto_save_log": False,
    "max_log_lines": 1000,
}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def resource_path(relative_path):
    """兼容源码运行和 PyInstaller 打包后的资源路径。"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)




def get_app_dir():
    """获取程序目录，用于保存 settings.json 和日志。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")


def open_folder(path: str):
    """打开文件所在目录，兼容 Windows / macOS / Linux。"""
    if not path:
        return

    folder = os.path.dirname(path) if os.path.isfile(path) else path

    if not folder or not os.path.exists(folder):
        return

    try:
        if sys.platform.startswith("win"):
            os.startfile(folder)
        elif sys.platform == "darwin":
            os.system(f'open "{folder}"')
        else:
            os.system(f'xdg-open "{folder}"')
    except Exception:
        webbrowser.open(folder)

def clean_drop_path(path: str) -> str:
    """清理拖拽进来的路径。"""
    path = path.strip()

    # Windows 拖入带空格路径时，tkinterdnd2 可能会返回 {C:/xxx/aaa bbb.png}
    if path.startswith("{") and path.endswith("}"):
        path = path[1:-1]

    # 多文件拖入时，只取第一个
    if "} {" in path:
        path = path.split("} {")[0].replace("{", "").replace("}", "")

    return path


class DropBox(ctk.CTkFrame):
    def __init__(self, parent, title, hint, command):
        super().__init__(
            parent,
            height=90,
            corner_radius=12,
            border_width=1,
            border_color="#33445c",
            fg_color="#292929"
        )
        self.command = command
        self.pack_propagate(False)

        ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(size=15, weight="bold")
        ).pack(pady=(22, 4))

        ctk.CTkLabel(
            self,
            text=hint,
            font=ctk.CTkFont(size=12),
            text_color="#9db4d6"
        ).pack()

        # 注册拖拽
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self.on_drop)

    def on_drop(self, event):
        path = clean_drop_path(event.data)
        self.command(path)


class HideZipImageApp(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()

        self.title(f"HideZipImage {APP_VERSION}")

        self.settings_path = os.path.join(get_app_dir(), SETTINGS_FILE)
        self.settings = self.load_settings()

        appearance = self.settings.get("appearance_mode", "dark")
        ctk.set_appearance_mode(appearance)

        if self.settings.get("remember_window", True):
            self.geometry(self.settings.get("window_geometry", "860x850"))
        else:
            self.geometry("860x850")
        self.minsize(860, 780)
        self.configure(bg="#242424")

        self.image_path = ctk.StringVar(master=self)
        self.archive_path = ctk.StringVar(master=self)
        self.save_path = ctk.StringVar(master=self)
        self.log_lines = []
        self.last_output_path = ""
        self.current_theme_color = "蓝色"
        self.is_busy = False
        self.action_buttons = []
        self.encrypt_var = tk.BooleanVar(master=self, value=False)
        self.password_var = ctk.StringVar(master=self)
        self.password_confirm_var = ctk.StringVar(master=self)

        self.build_ui()

        if self.settings.get("remember_theme", True):
            theme = self.settings.get("theme", "蓝色")
            if theme in THEME_COLORS:
                self.theme_menu.set(theme)
                self.apply_theme_color(theme, save_setting=False)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # 启动 3 秒后自动检查更新；没有新版本时不弹窗打扰。
        if self.settings.get("auto_check_update", True):
            self.after(3000, lambda: self.check_update(show_latest_message=False))

    def build_ui(self):
        # 顶部
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(24, 10))

        title = ctk.CTkLabel(
            header,
            text=f"HideZipImage {APP_VERSION}",
            font=ctk.CTkFont(size=30, weight="bold")
        )
        title.pack(side="left")

        about_btn = ctk.CTkButton(
            header,
            text="关于",
            width=80,
            height=34,
            command=self.show_about
        )
        about_btn.pack(side="right")

        sponsor_btn = ctk.CTkButton(
            header,
            text="赞助",
            width=80,
            height=34,
            fg_color="#dfeee7",
            text_color="#1f2a24",
            hover_color="#c9ded5",
            command=self.show_sponsor
        )
        sponsor_btn.pack(side="right", padx=(8, 0))

        update_btn = ctk.CTkButton(
            header,
            text="检查更新",
            width=95,
            height=34,
            fg_color="#374151",
            hover_color="#4B5563",
            command=self.check_update
        )
        update_btn.pack(side="right", padx=(8, 0))

        settings_btn = ctk.CTkButton(
            header,
            text="设置",
            width=80,
            height=34,
            fg_color="#374151",
            hover_color="#4B5563",
            command=self.show_settings
        )
        settings_btn.pack(side="right", padx=(8, 0))

        subtitle = ctk.CTkLabel(
            self,
            text="把 ZIP / RAR / 7Z 隐藏到图片里，也可以一键提取",
            font=ctk.CTkFont(size=14),
            text_color="#9db4d6"
        )
        subtitle.pack(anchor="w", padx=30, pady=(0, 18))

        # 中间滚动区域
        self.main_frame = ctk.CTkScrollableFrame(
            self,
            corner_radius=18,
            fg_color="#2b2b2b"
        )
        self.main_frame.pack(fill="both", expand=True, padx=30, pady=(0, 10))

        # 拖拽区域
        drop_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        drop_frame.pack(fill="x", padx=20, pady=(22, 18))

        self.image_drop = DropBox(
            drop_frame,
            "拖拽图片到这里",
            "支持 JPG / PNG / WEBP / BMP",
            self.handle_drop
        )
        self.image_drop.pack(side="left", expand=True, fill="x", padx=(0, 10))

        self.archive_drop = DropBox(
            drop_frame,
            "拖拽压缩包到这里",
            "支持 ZIP / RAR / 7Z",
            self.handle_drop
        )
        self.archive_drop.pack(side="left", expand=True, fill="x", padx=(10, 0))

        # 文件选择
        self.add_file_row("图片文件", self.image_path, self.select_image)
        self.add_file_row("压缩包文件", self.archive_path, self.select_archive)
        self.add_file_row("保存位置", self.save_path, self.select_save_path)

        # AES-256 密码加密区域
        encrypt_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        encrypt_frame.pack(fill="x", padx=20, pady=(8, 8))

        self.encrypt_switch = ctk.CTkSwitch(
            encrypt_frame,
            text="启用 AES-256 密码加密（提取后需要密码解压）",
            variable=self.encrypt_var,
            onvalue=True,
            offvalue=False
        )
        self.encrypt_switch.pack(anchor="w", pady=(0, 8))

        pwd_row = ctk.CTkFrame(encrypt_frame, fg_color="transparent")
        pwd_row.pack(fill="x", pady=(0, 4))

        self.password_entry = ctk.CTkEntry(
            pwd_row,
            textvariable=self.password_var,
            placeholder_text="输入密码",
            show="*",
            height=36
        )
        self.password_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.password_confirm_entry = ctk.CTkEntry(
            pwd_row,
            textvariable=self.password_confirm_var,
            placeholder_text="确认密码",
            show="*",
            height=36
        )
        self.password_confirm_entry.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            encrypt_frame,
            text="说明：开启后会先生成一个临时 AES 加密 ZIP，再隐藏到图片中。",
            font=ctk.CTkFont(size=12),
            text_color="#9db4d6"
        ).pack(anchor="w")

        # 信息框
        self.info_box = ctk.CTkTextbox(
            self.main_frame,
            height=160,
            corner_radius=12,
            fg_color="#333333"
        )
        self.info_box.pack(fill="x", padx=20, pady=(12, 22))
        self.info_box.insert("1.0", "等待选择文件...\n")
        self.info_box.configure(state="disabled")

        # V2.9.0 更多功能区域：只新增，不影响原有隐藏/提取功能
        more_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        more_frame.pack(fill="x", padx=20, pady=(0, 18))

        batch_btn = ctk.CTkButton(
            more_frame,
            text="批量隐藏",
            height=38,
            fg_color="#374151",
            hover_color="#4B5563",
            command=self.batch_hide_archives
        )
        batch_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))
        self.action_buttons.append(batch_btn)

        verify_btn = ctk.CTkButton(
            more_frame,
            text="验证隐藏",
            height=38,
            fg_color="#374151",
            hover_color="#4B5563",
            command=self.verify_hidden_file
        )
        verify_btn.pack(side="left", expand=True, fill="x", padx=6)

        log_btn = ctk.CTkButton(
            more_frame,
            text="导出日志",
            height=38,
            fg_color="#374151",
            hover_color="#4B5563",
            command=self.export_log
        )
        log_btn.pack(side="left", expand=True, fill="x", padx=6)

        github_btn = ctk.CTkButton(
            more_frame,
            text="GitHub",
            height=38,
            fg_color="#374151",
            hover_color="#4B5563",
            command=lambda: webbrowser.open(GITHUB_URL)
        )
        github_btn.pack(side="left", expand=True, fill="x", padx=6)

        self.theme_menu = ctk.CTkOptionMenu(
            more_frame,
            values=list(THEME_COLORS.keys()),
            width=95,
            height=38,
            command=self.apply_theme_color
        )
        self.theme_menu.set("蓝色")
        self.theme_menu.pack(side="right", padx=(6, 0))

        changelog_btn = ctk.CTkButton(
            self.main_frame,
            text="查看更新日志",
            height=38,
            fg_color="#374151",
            hover_color="#4B5563",
            command=self.show_update_log
        )
        changelog_btn.pack(fill="x", padx=20, pady=(0, 18))

        # 底部按钮固定，不放进滚动区
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.pack(side="bottom", fill="x", padx=30, pady=(8, 20))

        self.progress_bar = ctk.CTkProgressBar(bottom_frame, height=8)
        self.progress_bar.pack(fill="x", pady=(0, 8))
        self.progress_bar.set(0)

        self.status_label = ctk.CTkLabel(
            bottom_frame,
            text="就绪",
            font=ctk.CTkFont(size=12),
            text_color="#9db4d6"
        )
        self.status_label.pack(fill="x", pady=(0, 8))

        btn_row = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        btn_row.pack(fill="x")

        self.hide_btn = ctk.CTkButton(
            btn_row,
            text="开始隐藏",
            height=46,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self.hide_archive_to_image
        )
        self.hide_btn.pack(side="left", expand=True, fill="x", padx=(0, 10))

        self.extract_btn = ctk.CTkButton(
            btn_row,
            text="一键提取",
            height=46,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self.extract_archive_from_image
        )
        self.extract_btn.pack(side="left", expand=True, fill="x", padx=(10, 0))

        self.action_buttons.extend([self.hide_btn, self.extract_btn])

    def add_file_row(self, label_text, variable, command):
        label = ctk.CTkLabel(
            self.main_frame,
            text=label_text,
            font=ctk.CTkFont(size=14, weight="bold")
        )
        label.pack(anchor="w", padx=20, pady=(8, 4))

        row = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(0, 8))

        entry = ctk.CTkEntry(row, textvariable=variable, height=38)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn = ctk.CTkButton(row, text="浏览", width=90, height=38, command=command)
        btn.pack(side="right")

    def select_image(self):
        path = filedialog.askopenfilename(
            title="选择图片文件",
            filetypes=[
                ("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp"),
                ("所有文件", "*.*")
            ]
        )
        if path:
            self.set_image(path)

    def select_archive(self):
        path = filedialog.askopenfilename(
            title="选择压缩包文件",
            filetypes=[
                ("压缩包文件", "*.zip *.rar *.7z"),
                ("所有文件", "*.*")
            ]
        )
        if path:
            self.set_archive(path)

    def select_save_path(self):
        path = filedialog.asksaveasfilename(
            title="选择保存位置",
            defaultextension=".png",
            filetypes=[
                ("PNG 图片", "*.png"),
                ("JPG 图片", "*.jpg"),
                ("所有文件", "*.*")
            ]
        )
        if path:
            self.save_path.set(path)
            folder = os.path.dirname(path)
            if folder:
                self.settings["last_output_dir"] = folder
                self.save_settings()

    def handle_drop(self, path):
        """拖拽后自动识别文件类型：图片进图片框，压缩包进压缩包框。"""
        path = clean_drop_path(path)

        if not os.path.exists(path):
            messagebox.showerror("错误", "拖入的文件不存在")
            return

        ext = os.path.splitext(path)[1].lower()

        if ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
            self.set_image(path)
        elif ext in [".zip", ".rar", ".7z"]:
            self.set_archive(path)
        else:
            messagebox.showwarning(
                "无法识别",
                "请拖入图片文件，或 ZIP / RAR / 7Z 压缩包。"
            )

    def set_image(self, path):
        path = clean_drop_path(path)

        if not os.path.exists(path):
            messagebox.showerror("错误", "图片文件不存在")
            return

        ext = os.path.splitext(path)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
            messagebox.showwarning("提示", "这个文件可能不是常见图片格式")

        self.image_path.set(path)
        self.auto_set_save_path()
        self.update_info()

    def set_archive(self, path):
        path = clean_drop_path(path)

        if not os.path.exists(path):
            messagebox.showerror("错误", "压缩包文件不存在")
            return

        ext = os.path.splitext(path)[1].lower()
        if ext not in [".zip", ".rar", ".7z"]:
            messagebox.showwarning("提示", "建议使用 ZIP / RAR / 7Z 压缩包")

        self.archive_path.set(path)
        self.auto_set_save_path()
        self.update_info()

    def auto_set_save_path(self):
        image = self.image_path.get()
        archive = self.archive_path.get()

        if image and archive:
            image_folder = os.path.dirname(image)
            output_mode = self.settings.get("output_mode", "same_folder")

            if output_mode == "custom":
                folder = self.settings.get("default_output_dir") or image_folder
            elif output_mode == "last_folder":
                folder = self.settings.get("last_output_dir") or image_folder
            else:
                folder = image_folder

            if not folder or not os.path.exists(folder):
                folder = image_folder

            image_name, image_ext = os.path.splitext(os.path.basename(image))
            if not image_ext:
                image_ext = ".png"
            self.save_path.set(os.path.join(folder, f"{image_name}_hidden{image_ext}"))

    def get_image_info(self, path):
        try:
            with Image.open(path) as img:
                return f"{img.width} × {img.height}"
        except Exception:
            return "无法读取分辨率"

    def fmt_size(self, size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 ** 2:
            return f"{size / 1024:.2f} KB"
        if size < 1024 ** 3:
            return f"{size / 1024 / 1024:.2f} MB"
        return f"{size / 1024 / 1024 / 1024:.2f} GB"

    def update_info(self):
        image = self.image_path.get()
        archive = self.archive_path.get()
        lines = []

        if image and os.path.exists(image):
            image_size = os.path.getsize(image)
            image_ext = os.path.splitext(image)[1].upper().replace(".", "")
            image_res = self.get_image_info(image)
            lines.append("图片信息")
            lines.append(f"文件名：{os.path.basename(image)}")
            lines.append(f"格式：{image_ext}")
            lines.append(f"分辨率：{image_res}")
            lines.append(f"大小：{self.fmt_size(image_size)}")

        if archive and os.path.exists(archive):
            archive_size = os.path.getsize(archive)
            archive_ext = os.path.splitext(archive)[1].upper().replace(".", "")
            if lines:
                lines.append("")
            lines.append("压缩包信息")
            lines.append(f"文件名：{os.path.basename(archive)}")
            lines.append(f"格式：{archive_ext}")
            lines.append(f"大小：{self.fmt_size(archive_size)}")

        if image and archive and os.path.exists(image) and os.path.exists(archive):
            total = os.path.getsize(image) + os.path.getsize(archive)
            ratio = os.path.getsize(archive) / total * 100
            lines.append("")
            lines.append("输出信息")
            lines.append(f"最终大小：{self.fmt_size(total)}")
            lines.append(f"压缩包占比：{ratio:.2f}%")
            if total > 100 * 1024 * 1024:
                lines.append("提醒：最终文件超过 100MB，上传平台可能会限制")

        if not lines:
            lines.append("等待选择文件...")

        self.info_box.configure(state="normal")
        self.info_box.delete("1.0", "end")
        self.info_box.insert("1.0", "\n".join(lines))
        self.info_box.configure(state="disabled")

    def set_busy(self, busy: bool, text: str = ""):
        """切换忙碌状态，防止大文件处理时重复点击。"""
        self.is_busy = busy
        state = "disabled" if busy else "normal"
        for btn in getattr(self, "action_buttons", []):
            try:
                btn.configure(state=state)
            except Exception:
                pass
        try:
            self.configure(cursor="watch" if busy else "")
            self.status_label.configure(text=text or ("处理中..." if busy else "就绪"))
            if not busy:
                self.progress_bar.set(0)
        except Exception:
            pass

    def set_progress(self, value: float, text: str = ""):
        """线程安全地更新进度条。"""
        value = max(0.0, min(1.0, float(value)))
        def update_ui():
            try:
                self.progress_bar.set(value)
                if text:
                    self.status_label.configure(text=text)
            except Exception:
                pass
        self.after(0, update_ui)

    def run_worker(self, target):
        """后台执行耗时任务，避免 UI 假死。"""
        threading.Thread(target=target, daemon=True).start()

    def copy_stream_with_progress(self, src_path, dst_file, done_bytes, total_bytes, prefix="处理中"):
        """按块复制文件，同时更新进度。"""
        chunk_size = 1024 * 1024
        copied = done_bytes
        with open(src_path, "rb") as src:
            while True:
                chunk = src.read(chunk_size)
                if not chunk:
                    break
                dst_file.write(chunk)
                copied += len(chunk)
                if total_bytes > 0:
                    self.set_progress(copied / total_bytes, f"{prefix} {copied / total_bytes * 100:.1f}%")
        return copied

    def encrypt_archive_to_temp_zip(self, src_file, password):
        """把原压缩包打包进临时 AES-256 ZIP，返回临时文件路径。"""
        if pyzipper is None:
            raise RuntimeError("缺少 pyzipper 库，请先运行：pip install pyzipper")

        temp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        temp.close()

        with pyzipper.AESZipFile(
            temp.name,
            "w",
            compression=pyzipper.ZIP_DEFLATED,
            encryption=pyzipper.WZ_AES
        ) as zf:
            zf.setpassword(password.encode("utf-8"))
            zf.setencryption(pyzipper.WZ_AES, nbits=256)
            zf.write(src_file, arcname=os.path.basename(src_file))

        return temp.name

    def hide_archive_to_image(self):
        if self.is_busy:
            return

        image = self.image_path.get()
        archive = self.archive_path.get()
        save = self.save_path.get()

        if not image or not os.path.exists(image):
            messagebox.showerror("错误", "请选择有效的图片文件")
            return

        if not archive or not os.path.exists(archive):
            messagebox.showerror("错误", "请选择有效的压缩包文件")
            return

        if not save:
            messagebox.showerror("错误", "请选择保存位置")
            return

        if os.path.exists(save) and not self.settings.get("auto_overwrite", False):
            if not messagebox.askyesno("文件已存在", "输出文件已经存在，是否覆盖？"):
                return

        encrypt_enabled = bool(self.encrypt_var.get())
        password = self.password_var.get()
        password_confirm = self.password_confirm_var.get()

        if encrypt_enabled:
            if pyzipper is None:
                messagebox.showerror("缺少组件", "启用 AES 加密需要 pyzipper。\n\n请先运行：pip install pyzipper")
                return
            if not password:
                messagebox.showerror("错误", "请输入加密密码")
                return
            if password != password_confirm:
                messagebox.showerror("错误", "两次输入的密码不一致")
                return
            if len(password) < 6:
                if not messagebox.askyesno("密码较短", "密码少于 6 位，安全性较低。是否继续？"):
                    return

        self.set_busy(True, "正在隐藏...")
        self.set_progress(0, "准备处理...")
        self.run_worker(lambda: self.hide_archive_worker(image, archive, save, encrypt_enabled, password))

    def hide_archive_worker(self, image, archive, save, encrypt_enabled=False, password=""):
        start_time = time.time()
        temp_archive = None
        try:
            real_archive = archive

            if encrypt_enabled:
                self.set_progress(0.02, "正在 AES-256 加密压缩包...")
                temp_archive = self.encrypt_archive_to_temp_zip(archive, password)
                real_archive = temp_archive
                self.write_log(f"AES-256 加密完成：{os.path.basename(archive)}")

            total_bytes = os.path.getsize(image) + os.path.getsize(real_archive)
            done = 0

            with open(save, "wb") as output_file:
                done = self.copy_stream_with_progress(image, output_file, done, total_bytes, "写入图片")
                done = self.copy_stream_with_progress(real_archive, output_file, done, total_bytes, "写入压缩包")

            elapsed = time.time() - start_time
            speed = total_bytes / elapsed if elapsed > 0 else total_bytes
            self.last_output_path = save
            self.settings["last_output_dir"] = os.path.dirname(save)
            self.save_settings()
            self.write_log(f"隐藏完成：{save} | 耗时：{elapsed:.2f} 秒 | 速度：{self.fmt_size(speed)}/s")
            self.verify_file_silent(save)
            self.set_progress(1, "隐藏完成 100%")

            self.after(0, lambda: self.hide_archive_done(save))

        except Exception as e:
            self.write_log("隐藏失败", e)
            self.after(0, lambda err=e: messagebox.showerror("错误", f"隐藏失败：\n{err}"))
        finally:
            if temp_archive and os.path.exists(temp_archive):
                try:
                    os.remove(temp_archive)
                except Exception as cleanup_error:
                    self.write_log("删除临时加密文件失败", cleanup_error)
            self.after(0, lambda: self.set_busy(False, "就绪"))

    def hide_archive_done(self, save):
        if self.settings.get("auto_open_folder", False):
            open_folder(save)
            messagebox.showinfo("隐藏完成", f"隐藏完成！\n\n保存位置：\n{save}")
            return

        if messagebox.askyesno(
            "隐藏完成",
            f"隐藏完成！\n\n保存位置：\n{save}\n\n是否打开输出目录？"
        ):
            open_folder(save)

    def extract_archive_from_image(self):
        if self.is_busy:
            return

        image = self.image_path.get()

        if not image or not os.path.exists(image):
            image = filedialog.askopenfilename(
                title="选择需要提取的隐藏图片",
                filetypes=[
                    ("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp"),
                    ("所有文件", "*.*")
                ]
            )

        if not image:
            return

        self.set_busy(True, "正在检测隐藏压缩包...")
        self.set_progress(0, "正在检测...")
        self.run_worker(lambda: self.extract_detect_worker(image))

    def extract_detect_worker(self, image):
        try:
            pos, ext = self.detect_hidden_archive(image)
            if pos == -1:
                self.write_log(f"提取失败：未找到隐藏压缩包，文件 {image}")
                self.after(0, lambda: messagebox.showerror("错误", "没有在图片中找到 ZIP / RAR / 7Z 压缩包"))
                return

            self.set_progress(0.2, "已检测到隐藏压缩包")
            self.after(0, lambda: self.ask_extract_save_path(image, pos, ext))

        except Exception as e:
            self.write_log("提取检测失败", e)
            self.after(0, lambda err=e: messagebox.showerror("错误", f"提取失败：\n{err}"))
        finally:
            # 如果找到了压缩包，会在 ask_extract_save_path 里继续保持 busy 状态
            pass

    def ask_extract_save_path(self, image, found_pos, found_ext):
        folder = os.path.dirname(image)
        name = os.path.splitext(os.path.basename(image))[0]
        default_output = os.path.join(folder, f"{name}_extracted{found_ext}")

        save = filedialog.asksaveasfilename(
            title="保存提取出的压缩包",
            initialfile=os.path.basename(default_output),
            initialdir=folder,
            defaultextension=found_ext,
            filetypes=[
                ("ZIP 压缩包", "*.zip"),
                ("RAR 压缩包", "*.rar"),
                ("7Z 压缩包", "*.7z"),
                ("所有文件", "*.*")
            ]
        )

        if not save:
            self.set_busy(False, "就绪")
            return

        self.set_progress(0.2, "正在提取...")
        self.run_worker(lambda: self.extract_write_worker(image, save, found_pos))

    def extract_write_worker(self, image, save, found_pos):
        start_time = time.time()
        try:
            total_bytes = max(1, os.path.getsize(image) - found_pos)
            copied = 0
            chunk_size = 1024 * 1024

            with open(image, "rb") as src, open(save, "wb") as dst:
                src.seek(found_pos)
                while True:
                    chunk = src.read(chunk_size)
                    if not chunk:
                        break
                    dst.write(chunk)
                    copied += len(chunk)
                    self.set_progress(copied / total_bytes, f"正在提取 {copied / total_bytes * 100:.1f}%")

            elapsed = time.time() - start_time
            speed = copied / elapsed if elapsed > 0 else copied
            self.last_output_path = save
            self.settings["last_output_dir"] = os.path.dirname(save)
            self.save_settings()
            self.write_log(f"提取完成：{save} | 耗时：{elapsed:.2f} 秒 | 速度：{self.fmt_size(speed)}/s")
            self.set_progress(1, "提取完成 100%")
            self.after(0, lambda: self.extract_done(save))

        except Exception as e:
            self.write_log("提取失败", e)
            self.after(0, lambda err=e: messagebox.showerror("错误", f"提取失败：\n{err}"))
        finally:
            self.after(0, lambda: self.set_busy(False, "就绪"))

    def extract_done(self, save):
        if self.settings.get("auto_open_folder", False):
            open_folder(save)
            messagebox.showinfo("提取完成", f"提取完成！\n\n保存位置：\n{save}")
            return

        if messagebox.askyesno(
            "提取完成",
            f"提取完成！\n\n保存位置：\n{save}\n\n是否打开输出目录？"
        ):
            open_folder(save)


    def write_log(self, message, error=None):
        """记录程序运行日志，方便导出给作者排查问题。"""
        time_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{time_text}] {message}"
        if error is not None:
            line += f" | 错误：{error}"
        self.log_lines.append(line)

        max_lines = int(self.settings.get("max_log_lines", 1000) or 1000)
        if len(self.log_lines) > max_lines:
            self.log_lines = self.log_lines[-max_lines:]

        if self.settings.get("auto_save_log", False):
            try:
                log_path = os.path.join(get_app_dir(), "HideZipImage_auto_log.txt")
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    def detect_hidden_archive(self, file_path):
        """检测文件里是否包含 ZIP / RAR / 7Z 压缩包头。返回 (位置, 后缀)。"""
        with open(file_path, "rb") as f:
            data = f.read()

        signatures = [
            (b"PK\x03\x04", ".zip"),
            (b"PK\x05\x06", ".zip"),
            (b"PK\x07\x08", ".zip"),
            (b"Rar!\x1A\x07\x00", ".rar"),
            (b"Rar!\x1A\x07\x01\x00", ".rar"),
            (b"7z\xBC\xAF\x27\x1C", ".7z"),
        ]

        found_pos = -1
        found_ext = ""
        for sig, ext in signatures:
            pos = data.find(sig)
            if pos != -1 and (found_pos == -1 or pos < found_pos):
                found_pos = pos
                found_ext = ext
        return found_pos, found_ext

    def verify_file_silent(self, file_path):
        """生成后静默验证，结果写入日志，不打扰用户。"""
        try:
            pos, ext = self.detect_hidden_archive(file_path)
            if pos != -1:
                self.write_log(f"验证成功：检测到 {ext}，位置 {pos}，文件 {file_path}")
            else:
                self.write_log(f"验证失败：没有检测到隐藏压缩包，文件 {file_path}")
        except Exception as e:
            self.write_log("验证时发生错误", e)

    def verify_hidden_file(self):
        """一键验证当前图片或选择图片中是否含隐藏压缩包。"""
        file_path = self.save_path.get() or self.image_path.get()

        if not file_path or not os.path.exists(file_path):
            file_path = filedialog.askopenfilename(
                title="选择需要验证的图片",
                filetypes=[
                    ("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp"),
                    ("所有文件", "*.*")
                ]
            )

        if not file_path:
            return

        try:
            pos, ext = self.detect_hidden_archive(file_path)
            if pos == -1:
                self.write_log(f"手动验证失败：{file_path}")
                messagebox.showwarning("验证结果", "没有检测到 ZIP / RAR / 7Z 压缩包。")
            else:
                self.write_log(f"手动验证成功：{file_path}，格式 {ext}，位置 {pos}")
                messagebox.showinfo(
                    "验证成功",
                    f"检测到隐藏压缩包。\n\n格式：{ext}\n位置：{pos}\n文件：\n{file_path}"
                )
        except Exception as e:
            self.write_log("手动验证出错", e)
            messagebox.showerror("验证失败", str(e))

    def batch_hide_archives(self):
        """批量隐藏：一张图片 + 多个压缩包，自动生成多个隐藏图片。"""
        if self.is_busy:
            return

        image = self.image_path.get()

        if not image or not os.path.exists(image):
            image = filedialog.askopenfilename(
                title="选择作为封面的图片",
                filetypes=[
                    ("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp"),
                    ("所有文件", "*.*")
                ]
            )

        if not image:
            return

        archives = filedialog.askopenfilenames(
            title="选择一个或多个压缩包",
            filetypes=[
                ("压缩包文件", "*.zip *.rar *.7z"),
                ("所有文件", "*.*")
            ]
        )

        if not archives:
            return

        output_dir = filedialog.askdirectory(title="选择批量输出目录")
        if not output_dir:
            return

        self.set_busy(True, "正在批量隐藏...")
        self.set_progress(0, "准备批量处理...")
        self.run_worker(lambda: self.batch_hide_worker(image, archives, output_dir))

    def batch_hide_worker(self, image, archives, output_dir):
        start_time = time.time()
        try:
            image_name, image_ext = os.path.splitext(os.path.basename(image))
            if not image_ext:
                image_ext = ".png"

            image_size = os.path.getsize(image)
            archive_sizes = []
            for archive in archives:
                archive_sizes.append(os.path.getsize(archive) if os.path.exists(archive) else 0)
            total_bytes = max(1, image_size * len(archives) + sum(archive_sizes))
            done = 0

            success_count = 0
            failed_items = []

            for index, archive in enumerate(archives, start=1):
                try:
                    if not os.path.exists(archive):
                        failed_items.append(os.path.basename(archive))
                        continue

                    archive_name = os.path.splitext(os.path.basename(archive))[0]
                    output = os.path.join(output_dir, f"{image_name}_{archive_name}_hidden{image_ext}")

                    with open(output, "wb") as f:
                        done = self.copy_stream_with_progress(image, f, done, total_bytes, f"批量 {index}/{len(archives)} 写入图片")
                        done = self.copy_stream_with_progress(archive, f, done, total_bytes, f"批量 {index}/{len(archives)} 写入压缩包")

                    success_count += 1
                    self.last_output_path = output
                    self.settings["last_output_dir"] = output_dir
                    self.save_settings()
                    self.write_log(f"批量隐藏成功：{output}")
                    self.verify_file_silent(output)

                except Exception as item_error:
                    failed_items.append(os.path.basename(archive))
                    self.write_log(f"批量隐藏失败：{archive}", item_error)

            elapsed = time.time() - start_time
            self.set_progress(1, "批量隐藏完成 100%")
            self.write_log(f"批量隐藏完成：成功 {success_count} 个，失败 {len(failed_items)} 个 | 耗时：{elapsed:.2f} 秒")
            self.after(0, lambda: self.batch_hide_done(output_dir, success_count, failed_items))

        except Exception as e:
            self.write_log("批量隐藏整体失败", e)
            self.after(0, lambda err=e: messagebox.showerror("批量隐藏失败", str(err)))
        finally:
            self.after(0, lambda: self.set_busy(False, "就绪"))

    def batch_hide_done(self, output_dir, success_count, failed_items):
        msg = f"批量隐藏完成。\n\n成功：{success_count} 个\n失败：{len(failed_items)} 个"
        if failed_items:
            msg += "\n\n失败文件：\n" + "\n".join(failed_items[:10])

        if self.settings.get("auto_open_folder", False):
            open_folder(output_dir)
            messagebox.showinfo("批量完成", msg)
            return

        if messagebox.askyesno("批量完成", msg + "\n\n是否打开输出目录？"):
            open_folder(output_dir)

    def export_log(self):
        """导出 log.txt，方便用户反馈问题。"""
        save = filedialog.asksaveasfilename(
            title="导出日志",
            defaultextension=".txt",
            initialfile="HideZipImage_log.txt",
            filetypes=[
                ("文本文件", "*.txt"),
                ("所有文件", "*.*")
            ]
        )

        if not save:
            return

        try:
            content = []
            content.append(f"HideZipImage 日志")
            content.append(f"程序版本：{APP_VERSION}")
            content.append(f"更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            content.append(f"图片路径：{self.image_path.get()}")
            content.append(f"压缩包路径：{self.archive_path.get()}")
            content.append(f"保存路径：{self.save_path.get()}")
            content.append(f"最后输出：{self.last_output_path}")
            content.append("")
            content.append("运行记录：")
            if self.log_lines:
                content.extend(self.log_lines)
            else:
                content.append("暂无日志。")

            with open(save, "w", encoding="utf-8") as f:
                f.write("\n".join(content))

            messagebox.showinfo("导出完成", f"日志已导出：\n{save}")

        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    def show_update_log(self):
        """从 version.json 显示更新日志，支持多行 message。"""
        try:
            with urllib.request.urlopen(UPDATE_JSON_URL, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))

            latest_version = data.get("latest_version", "未知版本")
            message = data.get("message", "暂无更新日志。")
            download_url = data.get("download_url", GITHUB_URL)

        except Exception as e:
            latest_version = "读取失败"
            message = f"无法读取更新日志。\n\n错误信息：{e}"
            download_url = GITHUB_URL

        win = ctk.CTkToplevel(self)
        win.title("更新日志")
        win.geometry("520x460")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(
            win,
            text=f"HideZipImage 更新日志",
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(pady=(24, 8))

        ctk.CTkLabel(
            win,
            text=f"最新版本：{latest_version}",
            font=ctk.CTkFont(size=14),
            text_color="#9db4d6"
        ).pack(pady=(0, 12))

        box = ctk.CTkTextbox(win, height=260, corner_radius=12)
        box.pack(fill="both", expand=True, padx=28, pady=(0, 16))
        box.insert("1.0", str(message))
        box.configure(state="disabled")

        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.pack(fill="x", padx=28, pady=(0, 22))

        ctk.CTkButton(
            btn_frame,
            text="打开下载页",
            height=38,
            command=lambda: webbrowser.open(download_url)
        ).pack(side="left", expand=True, fill="x", padx=(0, 8))

        ctk.CTkButton(
            btn_frame,
            text="关闭",
            height=38,
            fg_color="#444444",
            hover_color="#555555",
            command=win.destroy
        ).pack(side="left", expand=True, fill="x", padx=(8, 0))

    def apply_theme_color(self, theme_name, save_setting=True):
        """简单主题颜色切换：主要改变按钮颜色，不删除原界面结构。"""
        color = THEME_COLORS.get(theme_name, "#3B82F6")
        self.current_theme_color = theme_name

        if save_setting:
            self.settings["theme"] = theme_name
            self.save_settings()

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, ctk.CTkButton):
                    try:
                        text = child.cget("text")
                        if text not in ["赞助", "关闭"]:
                            child.configure(fg_color=color)
                    except Exception:
                        pass
                walk(child)

        walk(self)
        self.write_log(f"切换主题颜色：{theme_name}")

    def load_settings(self):
        """读取 settings.json；如果不存在或损坏，就自动创建默认设置。"""
        settings = DEFAULT_SETTINGS.copy()

        try:
            if os.path.exists(self.settings_path):
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    user_settings = json.load(f)
                if isinstance(user_settings, dict):
                    settings.update(user_settings)
            else:
                os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
                with open(self.settings_path, "w", encoding="utf-8") as f:
                    json.dump(settings, f, ensure_ascii=False, indent=4)
        except Exception:
            settings = DEFAULT_SETTINGS.copy()

        return settings

    def save_settings(self):
        """保存 settings.json。"""
        try:
            os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.write_log("保存设置失败", e)

    def on_close(self):
        """关闭窗口前保存窗口大小和位置。"""
        try:
            if self.settings.get("remember_window", True):
                self.settings["window_geometry"] = self.geometry()
            self.save_settings()
        except Exception:
            pass
        self.destroy()

    def show_settings(self):
        """设置中心。"""
        win = ctk.CTkToplevel(self)
        win.title("设置")
        win.geometry("560x640")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(
            win,
            text="设置中心",
            font=ctk.CTkFont(size=26, weight="bold")
        ).pack(pady=(24, 8))

        ctk.CTkLabel(
            win,
            text=f"设置文件：{self.settings_path}",
            font=ctk.CTkFont(size=12),
            text_color="#9db4d6"
        ).pack(pady=(0, 12))

        frame = ctk.CTkScrollableFrame(win, corner_radius=14, fg_color="#2b2b2b")
        frame.pack(fill="both", expand=True, padx=26, pady=(0, 18))

        auto_check_var = tk.BooleanVar(value=bool(self.settings.get("auto_check_update", True)))
        auto_open_var = tk.BooleanVar(value=bool(self.settings.get("auto_open_folder", False)))
        auto_overwrite_var = tk.BooleanVar(value=bool(self.settings.get("auto_overwrite", False)))
        remember_window_var = tk.BooleanVar(value=bool(self.settings.get("remember_window", True)))
        remember_theme_var = tk.BooleanVar(value=bool(self.settings.get("remember_theme", True)))
        auto_save_log_var = tk.BooleanVar(value=bool(self.settings.get("auto_save_log", False)))

        def add_switch(text, variable):
            sw = ctk.CTkSwitch(frame, text=text, variable=variable, onvalue=True, offvalue=False)
            sw.pack(anchor="w", padx=18, pady=8)
            return sw

        ctk.CTkLabel(frame, text="常规", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=18, pady=(18, 6))
        add_switch("启动后自动检查更新", auto_check_var)
        add_switch("完成后自动打开输出目录", auto_open_var)
        add_switch("自动覆盖已有文件", auto_overwrite_var)
        add_switch("保存窗口大小和位置", remember_window_var)
        add_switch("记住主题颜色", remember_theme_var)

        ctk.CTkLabel(frame, text="外观", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=18, pady=(18, 6))
        theme_var = ctk.StringVar(value=self.settings.get("theme", "蓝色"))
        theme_menu = ctk.CTkOptionMenu(frame, values=list(THEME_COLORS.keys()), variable=theme_var)
        theme_menu.pack(fill="x", padx=18, pady=(4, 10))

        appearance_var = ctk.StringVar(value=self.settings.get("appearance_mode", "dark"))
        appearance_menu = ctk.CTkOptionMenu(frame, values=["dark", "light", "system"], variable=appearance_var)
        appearance_menu.pack(fill="x", padx=18, pady=(4, 10))

        ctk.CTkLabel(frame, text="默认输出目录", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=18, pady=(18, 6))
        output_mode_var = ctk.StringVar(value=self.settings.get("output_mode", "same_folder"))
        output_mode_menu = ctk.CTkOptionMenu(
            frame,
            values=["same_folder", "last_folder", "custom"],
            variable=output_mode_var
        )
        output_mode_menu.pack(fill="x", padx=18, pady=(4, 10))

        dir_row = ctk.CTkFrame(frame, fg_color="transparent")
        dir_row.pack(fill="x", padx=18, pady=(0, 12))
        default_dir_var = ctk.StringVar(value=self.settings.get("default_output_dir", ""))
        dir_entry = ctk.CTkEntry(dir_row, textvariable=default_dir_var, height=36)
        dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        def choose_default_dir():
            folder = filedialog.askdirectory(title="选择默认输出目录")
            if folder:
                default_dir_var.set(folder)

        ctk.CTkButton(dir_row, text="浏览", width=80, height=36, command=choose_default_dir).pack(side="right")

        ctk.CTkLabel(
            frame,
            text="same_folder=与图片同目录，last_folder=上次目录，custom=自定义目录",
            font=ctk.CTkFont(size=12),
            text_color="#9db4d6"
        ).pack(anchor="w", padx=18, pady=(0, 10))

        ctk.CTkLabel(frame, text="日志", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=18, pady=(18, 6))
        add_switch("自动保存运行日志", auto_save_log_var)
        max_log_var = ctk.StringVar(value=str(self.settings.get("max_log_lines", 1000)))
        ctk.CTkEntry(frame, textvariable=max_log_var, height=36, placeholder_text="最多保留日志行数").pack(fill="x", padx=18, pady=(4, 18))

        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.pack(fill="x", padx=26, pady=(0, 22))

        def save_and_close():
            try:
                max_log_lines = int(max_log_var.get().strip() or "1000")
            except ValueError:
                max_log_lines = 1000

            self.settings.update({
                "auto_check_update": bool(auto_check_var.get()),
                "auto_open_folder": bool(auto_open_var.get()),
                "auto_overwrite": bool(auto_overwrite_var.get()),
                "remember_window": bool(remember_window_var.get()),
                "remember_theme": bool(remember_theme_var.get()),
                "auto_save_log": bool(auto_save_log_var.get()),
                "theme": theme_var.get(),
                "appearance_mode": appearance_var.get(),
                "output_mode": output_mode_var.get(),
                "default_output_dir": default_dir_var.get().strip(),
                "max_log_lines": max_log_lines,
            })

            ctk.set_appearance_mode(self.settings.get("appearance_mode", "dark"))
            self.apply_theme_color(self.settings.get("theme", "蓝色"), save_setting=False)
            self.save_settings()
            self.auto_set_save_path()
            messagebox.showinfo("设置已保存", "设置已保存。部分外观设置重启后效果最稳定。")
            win.destroy()

        ctk.CTkButton(btn_frame, text="保存设置", height=40, command=save_and_close).pack(side="left", expand=True, fill="x", padx=(0, 8))
        ctk.CTkButton(btn_frame, text="关闭", height=40, fg_color="#444444", hover_color="#555555", command=win.destroy).pack(side="left", expand=True, fill="x", padx=(8, 0))

    def version_to_tuple(self, version_text):
        """把 V2.8.4 / 2.8.4 转成 (2, 8, 4)，方便比较版本。"""
        version_text = str(version_text).strip().upper().replace("V", "")
        parts = []

        for part in version_text.split("."):
            try:
                parts.append(int(part))
            except ValueError:
                parts.append(0)

        while len(parts) < 3:
            parts.append(0)

        return tuple(parts[:3])

    def check_update(self, show_latest_message=True):
        """从 version.json 检查是否有新版本。
        show_latest_message=False 时用于启动自动检查，没有新版本或失败时不弹窗打扰。
        """
        try:
            with urllib.request.urlopen(UPDATE_JSON_URL, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))

            latest_version = data.get("latest_version", "").strip()
            download_url = data.get("download_url", "").strip()
            message = data.get("message", "发现新版本。").strip()

            if not latest_version:
                if show_latest_message:
                    messagebox.showwarning("检查更新失败", "version.json 中没有 latest_version")
                return

            current = APP_VERSION.replace("V", "")

            if self.version_to_tuple(latest_version) > self.version_to_tuple(current):
                result = messagebox.askyesno(
                    "发现新版本",
                    f"当前版本：{current}\n"
                    f"最新版本：{latest_version}\n\n"
                    f"{message}\n\n"
                    "是否打开下载页面？"
                )

                if result and download_url:
                    webbrowser.open(download_url)
            else:
                if show_latest_message:
                    messagebox.showinfo(
                        "检查更新",
                        f"当前已经是最新版本。\n\n当前版本：{current}"
                    )

        except Exception as e:
            if show_latest_message:
                messagebox.showwarning(
                    "检查更新失败",
                    f"无法连接更新服务器。\n\n请检查网络，或确认 UPDATE_JSON_URL 是否正确。\n\n错误信息：{e}"
                )

    def show_about(self):
        messagebox.showinfo(
            "关于",
            f"HideZipImage {APP_VERSION}\n\n"
            "作者：WANG XINYU\n\n"
            "功能：\n"
            "1. 把 ZIP / RAR / 7Z 隐藏到图片后面\n"
            "2. 从图片中一键提取压缩包\n"
            "3. 支持拖拽文件和检查更新\n"
            "4. 支持启动自动检查更新和智能拖拽识别\n"
            "5. 支持批量隐藏、验证隐藏、导出日志、主题颜色切换\n"
            "6. 支持 AES-256 密码加密隐藏\n\n"
            f"GitHub：{GITHUB_URL}\n\n"
            "提示：隐藏后的图片仍然可以正常打开。"
        )

    def show_sponsor(self):
        win = ctk.CTkToplevel(self)
        win.title("赞助支持")
        win.geometry("512x720")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        title = ctk.CTkLabel(
            win,
            text="支持 HideZipImage",
            font=ctk.CTkFont(size=26, weight="bold")
        )
        title.pack(pady=(28, 8))

        desc = ctk.CTkLabel(
            win,
            text="如果这个工具帮到了你，可以请作者吃包辣条喵。\n邮箱:xinyuwang668@gmail.com\n",
            font=ctk.CTkFont(size=14),
            text_color="#8fa6b8"
        )
        desc.pack(pady=(0, 18))

        card = ctk.CTkFrame(win, corner_radius=14, fg_color="#2b2b2b")
        card.pack(fill="x", padx=34, pady=8)

        ctk.CTkLabel(
            card,
            text="赞助方式",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(22, 8))

        ctk.CTkLabel(
            card,
            text="微信",
            font=ctk.CTkFont(size=15)
        ).pack(pady=(0, 12))

        try:
            qr_image = ctk.CTkImage(
                light_image=Image.open(resource_path("sponsor.png")),
                dark_image=Image.open(resource_path("sponsor.png")),
                size=(256, 256)
            )

            qr_label = ctk.CTkLabel(card, text="", image=qr_image)
            qr_label.image = qr_image
            qr_label.pack(pady=(0, 14))

        except Exception:
            ctk.CTkLabel(
                card,
                text="未找到 sponsor.png\n请把赞助二维码图片命名为 sponsor.png\n并放到程序同目录。",
                font=ctk.CTkFont(size=13),
                text_color="#ffb4b4",
                justify="center"
            ).pack(padx=20, pady=(8, 22))

        ctk.CTkLabel(
            card,
            text="感谢你的支持！",
            font=ctk.CTkFont(size=13),
            text_color="#9db4d6"
        ).pack(pady=(0, 16))

        def copy_text():
            self.clipboard_clear()
            self.clipboard_append("感谢支持 HideZipImage！")
            messagebox.showinfo("已复制", "赞助信息已复制到剪贴板")

        copy_btn = ctk.CTkButton(
            card,
            text="复制赞助信息",
            height=40,
            command=copy_text
        )
        copy_btn.pack(fill="x", padx=28, pady=(0, 20))

        close_btn = ctk.CTkButton(
            win,
            text="关闭",
            height=40,
            fg_color="#444444",
            hover_color="#555555",
            command=win.destroy
        )
        close_btn.pack(fill="x", padx=34, pady=(20, 0))


if __name__ == "__main__":
    app = HideZipImageApp()
    app.mainloop()
