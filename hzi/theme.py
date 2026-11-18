"""配色与字体定义（深色 / 浅色两套）。"""

from __future__ import annotations

FONT_FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Consolas"

ACCENTS = {
    "蓝色": ("#3B82F6", "#2563EB", "#60A5FA"),
    "绿色": ("#10B981", "#059669", "#34D399"),
    "粉色": ("#EC4899", "#DB2777", "#F472B6"),
    "深灰": ("#64748B", "#475569", "#94A3B8"),
}

DARK = {
    "bg": "#0B1220",
    "sidebar": "#0E1626",
    "card": "#141D2E",
    "card_alt": "#1B2639",
    "card_hover": "#22304A",
    "border": "#26344C",
    "border_soft": "#1E2A3E",
    "text": "#E8EEF9",
    "muted": "#8A9AB5",
    "faint": "#5D6C85",
    "success": "#22C55E",
    "danger": "#EF4444",
    "warning": "#F59E0B",
    "overlay": "#0B1220",
    "log_bg": "#0A111D",
}

LIGHT = {
    "bg": "#F3F6FB",
    "sidebar": "#FFFFFF",
    "card": "#FFFFFF",
    "card_alt": "#EEF3FA",
    "card_hover": "#E3EBF7",
    "border": "#D9E2F0",
    "border_soft": "#E8EEF7",
    "text": "#0F172A",
    "muted": "#5A6B85",
    "faint": "#8494AC",
    "success": "#16A34A",
    "danger": "#DC2626",
    "warning": "#D97706",
    "overlay": "#FFFFFF",
    "log_bg": "#F7FAFF",
}


def palette(mode: str) -> dict:
    return DARK if mode == "dark" else LIGHT


def accent(name: str) -> tuple[str, str, str]:
    return ACCENTS.get(name, ACCENTS["蓝色"])
