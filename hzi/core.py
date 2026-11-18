"""HideZipImage 核心模块。

只负责文件处理（检测 / 隐藏 / 提取 / 校验 / 设置 / 日志），不依赖任何 GUI，
方便单元测试，也方便以后做命令行版本。

设计要点（V3.1.0）：
1. 检测压缩包时不再把整个文件读进内存，改为分块扫描 + 读取文件尾部；
2. ZIP 用「中央目录 + EOCD」反推真实起点，而不是简单找第一个 PK\\x03\\x04，
   这样即使图片本身的像素数据里恰好存在 PK 头，也不会误判；
3. 输出文件先写临时文件再原子替换，中途失败不会留下半截文件；
4. 隐藏完成后可选择对隐藏区做 SHA-256 比对，确保一个字节都没错。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

APP_NAME = "HideZipImage"
APP_VERSION = "3.1.0"
GITHUB_URL = "https://github.com/xinyuwang668-arch/Hide-Zip2Image"
UPDATE_JSON_URL = (
    "https://raw.githubusercontent.com/xinyuwang668-arch/Hide-Zip2Image/main/version.json"
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z"}

ZIP_LOCAL = b"PK\x03\x04"
ZIP_EOCD = b"PK\x05\x06"
ZIP64_EOCD = b"PK\x06\x06"
ZIP64_LOCATOR = b"PK\x06\x07"
RAR4 = b"Rar!\x1a\x07\x00"
RAR5 = b"Rar!\x1a\x07\x01\x00"
SEVENZ = b"7z\xbc\xaf\x27\x1c"

CHUNK_SIZE = 1024 * 1024
# 最长的 ZIP 注释是 65535 字节，加上 EOCD 本身 22 字节，再留点余量。
EOCD_TAIL_SIZE = 65535 + 22 + 4096
# 进度回调的最小间隔，避免大文件时把界面事件队列刷爆。
PROGRESS_INTERVAL = 0.08

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
    "last_image_dir": "",
    "last_archive_dir": "",
    "window_geometry": "1180x780",
    "auto_save_log": False,
    "max_log_lines": 1000,
    "verify_after_hide": True,
    "confirm_close_while_busy": True,
}

THEME_COLORS = {
    "蓝色": "#3B82F6",
    "绿色": "#10B981",
    "粉色": "#EC4899",
    "深灰": "#64748B",
}


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def app_dir() -> str:
    """程序所在目录：打包后是 exe 所在目录，源码运行时是项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(relative_path: str) -> str:
    """兼容源码运行和 PyInstaller 打包后的资源路径。"""
    base = getattr(sys, "_MEIPASS", None) or app_dir()
    return os.path.join(base, relative_path)


def human_size(size: float) -> str:
    """把字节数转成人类可读的大小。"""
    size = float(size)
    if size < 1024:
        return f"{int(size)} B"
    if size < 1024 ** 2:
        return f"{size / 1024:.2f} KB"
    if size < 1024 ** 3:
        return f"{size / 1024 ** 2:.2f} MB"
    return f"{size / 1024 ** 3:.2f} GB"


def human_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    minutes, sec = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes} 分 {sec:02d} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 时 {minutes:02d} 分"


def same_path(a: str, b: str) -> bool:
    """跨平台比较两个路径是否指向同一个文件。"""
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except Exception:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def open_folder(path: str) -> bool:
    """在资源管理器中定位文件（选中文件本身），不带路径时打开所在目录。"""
    if not path:
        return False
    path = os.path.abspath(path)
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    if not folder or not os.path.exists(folder):
        return False
    try:
        if sys.platform.startswith("win"):
            if os.path.isfile(path):
                try:
                    import subprocess

                    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
                    return True
                except Exception:
                    os.startfile(folder)
                    return True
            os.startfile(folder)
            return True
        if sys.platform == "darwin":
            os.system(f'open "{folder}"')
            return True
        os.system(f'xdg-open "{folder}"')
        return True
    except Exception:
        return False


def clean_drop_path(path: str) -> list[str]:
    """把 tkinterdnd2 拖拽数据解析成路径列表。

    拖进来的数据可能是：``C:/a.png``、``{C:/a b.png}``、
    ``{C:/a b.png} {C:/c.zip}``、``{C:/a.png} C:/c.zip``。
    """
    path = (path or "").strip().replace("\r", "\n")
    if not path:
        return []

    results: list[str] = []
    token = ""
    in_braces = False
    for ch in path:
        if ch == "{":
            in_braces = True
            token = ""
        elif ch == "}":
            in_braces = False
        elif ch in " \n\t" and not in_braces:
            if token:
                results.append(token)
                token = ""
        else:
            token += ch
    if token:
        results.append(token)

    cleaned = []
    for item in results:
        item = item.strip().strip('"')
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


def parse_version(text: str) -> tuple[int, ...]:
    """把 V3.1.0 / 3.1.0-beta 之类转成可比较的元组。"""
    text = str(text).strip().upper().lstrip("V")
    parts: list[int] = []
    for part in text.split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def sha256_file(path: str, start: int = 0, end: Optional[int] = None) -> str:
    """计算文件（或文件某一段）的 SHA-256。"""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        f.seek(start)
        remaining = None if end is None else max(0, end - start)
        while True:
            want = CHUNK_SIZE if remaining is None else min(CHUNK_SIZE, remaining)
            if want <= 0:
                break
            chunk = f.read(want)
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #
class HziError(Exception):
    """所有可预期的业务异常基类。"""


class NoArchiveFound(HziError):
    """图片里没有找到压缩包。"""


class InvalidPath(HziError):
    """路径不合法。"""


class SameFileError(HziError):
    """输出路径和输入路径相同。"""


class FileExists(HziError):
    """输出文件已存在且不允许覆盖。"""


class OperationCancelled(HziError):
    """用户取消了操作。"""


# --------------------------------------------------------------------------- #
# 检测
# --------------------------------------------------------------------------- #
@dataclass
class Detection:
    offset: int = -1
    ext: str = ""
    kind: str = ""
    valid: bool = False
    method: str = "none"
    detail: str = ""

    @property
    def found(self) -> bool:
        return self.offset >= 0

    def describe(self) -> str:
        if not self.found:
            return "未检测到压缩包"
        label = "ZIP" if self.kind == "zip" else self.kind.upper()
        text = f"检测到 {label}（偏移 {self.offset}）"
        if not self.valid:
            text += "，结构未完全校验"
        return text


def _is_plausible_local_header(path: str, pos: int) -> bool:
    """粗略检查 pos 处是否像一个 ZIP 本地文件头。"""
    try:
        with open(path, "rb") as f:
            f.seek(pos)
            header = f.read(30)
    except OSError:
        return False
    if len(header) < 30 or header[:4] != ZIP_LOCAL:
        return False
    try:
        (
            _ver,
            _flags,
            method,
            _mtime,
            _mdate,
            _crc,
            _csize,
            _usize,
            nlen,
            elen,
        ) = struct.unpack("<HHHHHIIIHH", header[4:30])
    except struct.error:
        return False
    # 常见压缩/存储方法；AES 加密的 ZIP 使用 99。
    if method not in (0, 8, 9, 12, 14, 93, 95, 98, 99):
        return False
    return 0 < nlen < 4096 and elen < 4096


def _detect_zip(path: str, size: int) -> Optional[Detection]:
    """用 EOCD 反推 ZIP 起点；比扫描 SIG 更准确。"""
    if size < 22:
        return None

    tail_size = min(size, EOCD_TAIL_SIZE)
    tail_start = size - tail_size
    try:
        with open(path, "rb") as f:
            f.seek(tail_start)
            tail = f.read(tail_size)
    except OSError:
        return None

    idx = tail.rfind(ZIP_EOCD)
    while idx != -1:
        abs_pos = tail_start + idx
        if idx + 22 <= len(tail):
            try:
                (
                    disk_no,
                    cd_disk,
                    _entries_disk,
                    _entries_total,
                    cd_size,
                    cd_offset,
                    comment_len,
                ) = struct.unpack("<HHHHIIH", tail[idx + 4 : idx + 22])
            except struct.error:
                disk_no = cd_disk = cd_size = cd_offset = comment_len = -1

            comment_ok = abs_pos + 22 + comment_len == size
            if comment_ok and disk_no == 0 and cd_disk == 0:
                if cd_offset == 0xFFFFFFFF or cd_size == 0xFFFFFFFF:
                    zip64 = _detect_zip64(path, abs_pos)
                    if zip64 is not None:
                        return zip64
                else:
                    start = abs_pos - cd_size - cd_offset
                    if 0 <= start <= abs_pos:
                        if start == abs_pos:
                            return Detection(start, ".zip", "zip", True, "eocd", "空 ZIP")
                        if _is_plausible_local_header(path, start):
                            return Detection(start, ".zip", "zip", True, "eocd")
        idx = tail.rfind(ZIP_EOCD, 0, idx)

    return None


def _detect_zip64(path: str, eocd_abs: int) -> Optional[Detection]:
    """处理 ZIP64（大于 4GB 或条目数超限）的 EOCD。"""
    locator_pos = eocd_abs - 20
    if locator_pos < 0:
        return None
    try:
        with open(path, "rb") as f:
            f.seek(locator_pos)
            locator = f.read(20)
            if len(locator) < 20 or not locator.startswith(ZIP64_LOCATOR):
                return None
            # 找 zip64 EOCD 记录（可能是 56 字节的固定部分）
            search_from = max(0, locator_pos - 4096)
            f.seek(search_from)
            region = f.read(locator_pos - search_from)
    except OSError:
        return None

    idx = region.rfind(ZIP64_EOCD)
    if idx == -1:
        return None
    record_abs = search_from + idx
    try:
        with open(path, "rb") as f:
            f.seek(record_abs + 4)
            size_of_record = struct.unpack("<Q", f.read(8))[0]
            f.seek(record_abs + 40)
            payload = f.read(16)
        cd_size, cd_offset = struct.unpack("<QQ", payload)
    except (OSError, struct.error):
        return None

    if record_abs != locator_pos - (12 + size_of_record):
        return None
    start = record_abs - cd_size - cd_offset
    if not (0 <= start <= record_abs):
        return None
    if start == record_abs or _is_plausible_local_header(path, start):
        return Detection(start, ".zip", "zip", True, "eocd64")
    return None


def _scan_last_signature(path: str, size: int, sig: bytes) -> int:
    """分块扫描，返回最后一个 sig 出现的位置（找不到返回 -1）。"""
    overlap = len(sig) - 1
    last = -1
    offset = 0
    with open(path, "rb") as f:
        prev = b""
        while offset < size:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            buf = prev + chunk
            base = offset - len(prev)
            pos = buf.find(sig)
            while pos != -1:
                last = base + pos
                pos = buf.find(sig, pos + 1)
            prev = buf[-overlap:] if overlap else b""
            offset += len(chunk)
    return last


def _detect_rar_7z(path: str, size: int) -> Optional[Detection]:
    for sig, ext, kind in (
        (RAR5, ".rar", "rar"),
        (RAR4, ".rar", "rar"),
        (SEVENZ, ".7z", "7z"),
    ):
        pos = _scan_last_signature(path, size, sig)
        if pos < 0:
            continue
        if kind == "7z":
            # 7z 头后面紧跟主/次版本号 0.4
            try:
                with open(path, "rb") as f:
                    f.seek(pos + 6)
                    version = f.read(2)
            except OSError:
                continue
            if version != b"\x00\x04":
                continue
            if pos + 32 > size:
                continue
        elif pos + 20 > size:
            continue
        return Detection(pos, ext, kind, True, "signature")
    return None


def detect_archive(path: str) -> Detection:
    """检测文件尾部是否追加了 ZIP / RAR / 7Z。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return Detection()

    if size < 4:
        return Detection()

    result = _detect_zip(path, size)
    if result is not None:
        return result

    result = _detect_rar_7z(path, size)
    if result is not None:
        return result

    # 最后的兜底：结构不完整的 ZIP（例如截断的压缩包）
    pos = _scan_last_signature(path, size, ZIP_LOCAL)
    if pos >= 0 and _is_plausible_local_header(path, pos):
        return Detection(pos, ".zip", "zip", False, "signature", "ZIP 结构不完整")
    return Detection()


# --------------------------------------------------------------------------- #
# 进度回调
# --------------------------------------------------------------------------- #
ProgressCallback = Callable[[float, str], None]


class _Progress:
    """对进度回调做节流，保证界面不会被上千次 after() 淹没。"""

    def __init__(self, callback: Optional[ProgressCallback], minimum: float = 0.0, span: float = 1.0):
        self.callback = callback
        self.minimum = minimum
        self.span = span
        self.last_emit = 0.0

    def __call__(self, fraction: float, text: str = "", force: bool = False) -> None:
        if self.callback is None:
            return
        now = time.monotonic()
        if not force and now - self.last_emit < PROGRESS_INTERVAL and fraction < 1:
            return
        self.last_emit = now
        value = self.minimum + max(0.0, min(1.0, float(fraction))) * self.span
        try:
            self.callback(max(0.0, min(1.0, value)), text)
        except Exception:
            pass


class _Cancel:
    """把可选的取消事件包装一层，方便在循环里检查。"""

    def __init__(self, event: Optional[threading.Event]):
        self.event = event

    def check(self) -> None:
        if self.event is not None and self.event.is_set():
            raise OperationCancelled("操作已取消")


# --------------------------------------------------------------------------- #
# 隐藏
# --------------------------------------------------------------------------- #
@dataclass
class HideResult:
    output: str
    total_bytes: int
    elapsed: float
    detection: Detection
    encrypted: bool = False
    verified: bool = False


def _copy_range(
    src: str,
    dst,
    *,
    start: int = 0,
    length: Optional[int] = None,
    progress: Optional[_Progress] = None,
    cancel: Optional[_Cancel] = None,
    label: str = "",
    done_bytes: int = 0,
    total_bytes: int = 0,
    digest: Optional["hashlib._Hash"] = None,
) -> int:
    """按块复制文件内容，同时更新进度、计算哈希。"""
    copied = 0
    with open(src, "rb") as f:
        f.seek(start)
        remaining = length
        while True:
            want = CHUNK_SIZE if remaining is None else min(CHUNK_SIZE, remaining)
            if want <= 0:
                break
            chunk = f.read(want)
            if not chunk:
                break
            dst.write(chunk)
            if digest is not None:
                digest.update(chunk)
            copied += len(chunk)
            if remaining is not None:
                remaining -= len(chunk)
            if cancel is not None:
                cancel.check()
            if progress is not None and total_bytes > 0:
                fraction = (done_bytes + copied) / total_bytes
                progress(fraction, f"{label} {fraction * 100:.1f}%")
    return copied


def make_encrypted_zip(
    src_file: str,
    password: str,
    work_dir: Optional[str] = None,
    progress: Optional[ProgressCallback] = None,
) -> str:
    """把任意压缩包重新封装成 AES-256 加密的 ZIP，返回临时文件路径。

    用流式写入（每 1MiB 一块）而不是一次性 zf.write()，这样大文件也有进度。
    """
    try:
        import pyzipper
    except ImportError as exc:  # pragma: no cover - 依赖缺失时才触发
        raise HziError("缺少 pyzipper 库，无法使用 AES 加密。请先运行：pip install pyzipper") from exc

    if not password:
        raise HziError("密码不能为空")

    stem = os.path.splitext(os.path.basename(src_file))[0] or "archive"
    fd, temp_path = tempfile.mkstemp(prefix=f"{stem}_aes_", suffix=".zip", dir=work_dir)
    os.close(fd)
    total = max(1, os.path.getsize(src_file))
    done = 0
    try:
        with pyzipper.AESZipFile(
            temp_path,
            "w",
            compression=pyzipper.ZIP_DEFLATED,
            encryption=pyzipper.WZ_AES,
        ) as zf:
            zf.setpassword(password.encode("utf-8"))
            zf.setencryption(pyzipper.WZ_AES, nbits=256)
            with zf.open(os.path.basename(src_file), "w", force_zip64=True) as dest:
                with open(src_file, "rb") as src:
                    while True:
                        chunk = src.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        dest.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done / total, f"正在加密 {done * 100 // total}%")
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise
    return temp_path


def hide_archive(
    cover_image: str,
    archive: str,
    output: str,
    *,
    encrypt: bool = False,
    password: str = "",
    overwrite: bool = False,
    verify: bool = True,
    progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> HideResult:
    """把压缩包追加到图片后面。

    输出先写到 ``*.part``，全部完成后再原子替换，避免中断后留下坏文件。
    """
    start_time = time.time()
    cancel = _Cancel(cancel_event)

    for label, path in (("图片", cover_image), ("压缩包", archive)):
        if not path or not os.path.isfile(path):
            raise InvalidPath(f"{label}文件不存在：{path}")
    if not output:
        raise InvalidPath("请选择保存位置")
    if same_path(output, cover_image) or same_path(output, archive):
        raise SameFileError("输出文件不能和输入文件相同，否则会覆盖原文件。")
    if os.path.exists(output) and not overwrite:
        raise FileExists(f"输出文件已存在：{output}")

    output_dir = os.path.dirname(os.path.abspath(output))
    if output_dir and not os.path.isdir(output_dir):
        raise InvalidPath(f"输出目录不存在：{output_dir}")

    cover_size = os.path.getsize(cover_image)
    real_archive = archive
    temp_archive: Optional[str] = None
    temp_output = f"{output}.part"
    archive_digest = hashlib.sha256()

    if progress:
        progress(0.0, "准备处理...")
    try:
        if encrypt:
            encrypt_progress = _Progress(progress, 0.0, 0.12)
            encrypt_progress(0.0, "正在生成 AES-256 加密压缩包...", force=True)
            temp_archive = make_encrypted_zip(
                archive, password, work_dir=output_dir, progress=encrypt_progress
            )
            real_archive = temp_archive
            encrypt_progress(1.0, "加密完成", force=True)

        archive_size = os.path.getsize(real_archive)
        total_bytes = cover_size + archive_size
        written = 0

        with open(temp_output, "wb") as dst:
            written += _copy_range(
                cover_image,
                dst,
                progress=_Progress(progress, 0.12 if encrypt else 0.0, 0.50 if encrypt else 0.62),
                cancel=cancel,
                label="写入图片",
                total_bytes=total_bytes,
                done_bytes=0,
            )
            written += _copy_range(
                real_archive,
                dst,
                progress=_Progress(progress, 0.62, 0.33),
                cancel=cancel,
                label="写入压缩包",
                total_bytes=total_bytes,
                done_bytes=cover_size,
                digest=archive_digest,
            )
            dst.flush()
            os.fsync(dst.fileno())

        cancel.check()

        verified = False
        if verify:
            _Progress(progress, 0.95, 0.05)(0.0, "正在校验隐藏结果...", force=True)
            detection = detect_archive(temp_output)
            if detection.offset != cover_size:
                raise HziError(
                    "校验失败：隐藏区偏移不正确"
                    f"（期望 {cover_size}，实际 {detection.offset}）"
                )
            if sha256_file(temp_output, cover_size) != archive_digest.hexdigest():
                raise HziError("校验失败：隐藏区数据与原压缩包不一致")
            verified = True
        else:
            detection = detect_archive(temp_output)

        os.replace(temp_output, output)
        elapsed = time.time() - start_time
        if progress:
            progress(1.0, "隐藏完成 100%")
        return HideResult(
            output=output,
            total_bytes=written,
            elapsed=elapsed,
            detection=detection,
            encrypted=encrypt,
            verified=verified,
        )
    finally:
        if temp_archive:
            try:
                os.remove(temp_archive)
            except OSError:
                pass
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# 提取
# --------------------------------------------------------------------------- #
@dataclass
class ExtractResult:
    output: str
    ext: str
    offset: int
    size: int
    elapsed: float
    verified: bool = False


def extract_archive(
    hidden_image: str,
    output: str,
    *,
    detection: Optional[Detection] = None,
    overwrite: bool = False,
    progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> ExtractResult:
    """从图片尾部把压缩包原样提取出来。"""
    start_time = time.time()
    cancel = _Cancel(cancel_event)

    if not hidden_image or not os.path.isfile(hidden_image):
        raise InvalidPath(f"图片文件不存在：{hidden_image}")
    if same_path(output, hidden_image):
        raise SameFileError("提取位置不能和原图片相同，否则会破坏原文件。")
    if os.path.exists(output) and not overwrite:
        raise FileExists(f"输出文件已存在：{output}")

    result = detection or detect_archive(hidden_image)
    if not result.found:
        raise NoArchiveFound("没有在图片中找到 ZIP / RAR / 7Z 压缩包")

    source_size = os.path.getsize(hidden_image)
    payload_size = max(0, source_size - result.offset)
    if payload_size <= 0:
        raise NoArchiveFound("检测到压缩包标记，但文件长度为 0")

    output_dir = os.path.dirname(os.path.abspath(output))
    if output_dir and not os.path.isdir(output_dir):
        raise InvalidPath(f"输出目录不存在：{output_dir}")

    temp_output = f"{output}.part"
    try:
        with open(hidden_image, "rb") as src, open(temp_output, "wb") as dst:
            copied = _copy_range(
                hidden_image,
                dst,
                start=result.offset,
                length=payload_size,
                progress=_Progress(progress, 0.0, 1.0),
                cancel=cancel,
                label="正在提取",
                total_bytes=payload_size,
                done_bytes=0,
            )
            dst.flush()
            os.fsync(dst.fileno())

        if copied != payload_size:
            raise HziError("提取不完整，已中止")
        cancel.check()

        # 轻量校验：提取出来的文件本身应当是一个完整压缩包。
        check = detect_archive(temp_output)
        verified = check.found and check.offset == 0 and check.valid
        if not verified and result.valid:
            raise HziError("校验失败：提取出的压缩包结构不正确")

        os.replace(temp_output, output)
        elapsed = time.time() - start_time
        if progress:
            progress(1.0, "提取完成 100%")
        return ExtractResult(
            output=output,
            ext=result.ext,
            offset=result.offset,
            size=payload_size,
            elapsed=elapsed,
            verified=verified,
        )
    finally:
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# 批量隐藏
# --------------------------------------------------------------------------- #
@dataclass
class BatchItem:
    archive: str
    output: str = ""
    ok: bool = False
    error: str = ""
    total_bytes: int = 0


@dataclass
class BatchResult:
    items: list[BatchItem] = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def success_count(self) -> int:
        return sum(1 for item in self.items if item.ok)

    @property
    def failed_items(self) -> list[BatchItem]:
        return [item for item in self.items if not item.ok]


def batch_hide(
    cover_image: str,
    archives: Iterable[str],
    output_dir: str,
    *,
    encrypt: bool = False,
    password: str = "",
    overwrite: bool = False,
    verify: bool = True,
    progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> BatchResult:
    """一张封面图 + 多个压缩包，批量生成隐藏图片。"""
    cancel = _Cancel(cancel_event)
    archives = [a for a in archives if a]
    if not cover_image or not os.path.isfile(cover_image):
        raise InvalidPath("封面图片不存在")
    if not archives:
        raise InvalidPath("请至少选择一个压缩包")
    if not output_dir or not os.path.isdir(output_dir):
        raise InvalidPath("输出目录不存在")

    start_time = time.time()
    image_name, image_ext = os.path.splitext(os.path.basename(cover_image))
    image_ext = image_ext or ".png"
    result = BatchResult()
    total = max(1, len(archives))

    for index, archive in enumerate(archives, start=1):
        cancel.check()
        item = BatchItem(archive=archive)
        archive_name = os.path.splitext(os.path.basename(archive))[0]
        item.output = os.path.join(output_dir, f"{image_name}_{archive_name}_hidden{image_ext}")
        base = (index - 1) / total

        def item_progress(value: float, text: str, base=base, index=index) -> None:
            if progress:
                progress(base + min(1.0, value) / total, f"批量 {index}/{total} {text}")

        try:
            hidden = hide_archive(
                cover_image,
                archive,
                item.output,
                encrypt=encrypt,
                password=password,
                overwrite=overwrite,
                verify=verify,
                progress=item_progress,
                cancel_event=cancel_event,
            )
            item.ok = True
            item.total_bytes = hidden.total_bytes
        except OperationCancelled:
            item.error = "已取消"
            result.items.append(item)
            raise
        except Exception as exc:  # 单个失败不影响其它文件
            item.error = str(exc)
        result.items.append(item)
        if progress:
            progress(index / total, f"批量完成 {index}/{total}")

    result.elapsed = time.time() - start_time
    return result


# --------------------------------------------------------------------------- #
# 设置
# --------------------------------------------------------------------------- #
class SettingsStore:
    """settings.json 的读写，带锁和原子写入。"""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self.data = self.load()

    def _defaults(self) -> dict:
        return json.loads(json.dumps(DEFAULT_SETTINGS))

    def _coerce(self, key: str, value):
        default = DEFAULT_SETTINGS.get(key)
        try:
            if isinstance(default, bool):
                if isinstance(value, str):
                    return value.strip().lower() in ("1", "true", "yes", "on")
                return bool(value)
            if isinstance(default, int) and not isinstance(default, bool):
                return max(0, int(value))
            if isinstance(default, str):
                return str(value)
        except (TypeError, ValueError):
            return default
        return value

    def load(self) -> dict:
        with self._lock:
            data = self._defaults()
            if os.path.exists(self.path):
                try:
                    with open(self.path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    if isinstance(raw, dict):
                        for key, value in raw.items():
                            if key in data:
                                data[key] = self._coerce(key, value)
                except (OSError, ValueError):
                    # 配置损坏时保留默认值，并把坏文件改名备份，避免反复失败。
                    try:
                        os.replace(self.path, f"{self.path}.bak")
                    except OSError:
                        pass
                return data
            self.data = data
            self.save()
            return data

    def save(self, override: Optional[dict] = None) -> None:
        with self._lock:
            data = self.data if override is None else override
            folder = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(folder, exist_ok=True)
            temp = f"{self.path}.tmp"
            try:
                with open(temp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                os.replace(temp, self.path)
            finally:
                if os.path.exists(temp):
                    try:
                        os.remove(temp)
                    except OSError:
                        pass

    def get(self, key: str, default=None):
        with self._lock:
            return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        with self._lock:
            self.data[key] = value

    def update(self, mapping: dict) -> None:
        with self._lock:
            self.data.update(mapping)

    def reset(self) -> None:
        """恢复出厂设置并落盘（不改动日志文件）。"""
        with self._lock:
            self.data = self._defaults()
            self.save()


# --------------------------------------------------------------------------- #
# 日志
# --------------------------------------------------------------------------- #
class LogBook:
    """环形内存日志 + 可选落盘（超过 2MB 自动截断）。"""

    MAX_FILE_BYTES = 2 * 1024 * 1024
    TRIM_BYTES = 512 * 1024

    def __init__(self, settings: SettingsStore, file_path: Optional[str] = None):
        self.settings = settings
        self.file_path = file_path
        self._lines: list[str] = []
        self._lock = threading.RLock()

    @property
    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()

    def log(self, message: str, error: Optional[BaseException] = None) -> str:
        from datetime import datetime

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{stamp}] {message}"
        if error is not None:
            line += f" | 错误：{error}"
        with self._lock:
            self._lines.append(line)
            try:
                limit = int(self.settings.get("max_log_lines", 1000) or 1000)
            except (TypeError, ValueError):
                limit = 1000
            if len(self._lines) > limit:
                del self._lines[: len(self._lines) - limit]

            if self.file_path and self.settings.get("auto_save_log", False):
                try:
                    self._append_file(line)
                except OSError:
                    pass
        return line

    def _append_file(self, line: str) -> None:
        assert self.file_path
        if os.path.exists(self.file_path) and os.path.getsize(self.file_path) > self.MAX_FILE_BYTES:
            with open(self.file_path, "rb") as f:
                f.seek(-self.TRIM_BYTES, os.SEEK_END)
                tail = f.read()
            with open(self.file_path, "wb") as f:
                f.write("...(日志过长，已截断)...\n".encode("utf-8") + tail)
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def export(self, path: str, extra: Optional[dict] = None) -> None:
        from datetime import datetime

        content = [f"{APP_NAME} 日志", f"程序版本：{APP_VERSION}"]
        content.append(f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if extra:
            for key, value in extra.items():
                content.append(f"{key}：{value}")
        content.append("")
        content.append("运行记录：")
        lines = self.lines
        content.extend(lines if lines else ["暂无日志。"])
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(content))


# --------------------------------------------------------------------------- #
# 自动更新
# --------------------------------------------------------------------------- #
@dataclass
class UpdateInfo:
    latest_version: str = ""
    download_url: str = GITHUB_URL
    message: str = ""
    error: str = ""

    @property
    def has_update(self) -> bool:
        return bool(self.latest_version) and is_newer(self.latest_version, APP_VERSION)


def fetch_update_info(timeout: float = 8.0) -> UpdateInfo:
    import urllib.request

    request = urllib.request.Request(
        UPDATE_JSON_URL,
        headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return UpdateInfo(error=str(exc))

    if not isinstance(data, dict):
        return UpdateInfo(error="version.json 格式不正确")
    info = UpdateInfo(
        latest_version=str(data.get("latest_version", "")).strip(),
        download_url=str(data.get("download_url", GITHUB_URL)).strip() or GITHUB_URL,
        message=str(data.get("message", "")).strip(),
    )
    if not info.latest_version:
        info.error = "version.json 缺少 latest_version"
    return info
