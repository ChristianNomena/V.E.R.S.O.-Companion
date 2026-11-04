"""
V.E.R.S.O. - Companion User Interface
Minimalist companion view with silent Slack intention listener,
light/dark mode toggle (top-right), responsive auxiliary history pane,
and direct UI error/permission alert banners with 1-click settings opener.
"""

import logging
import os
import platform
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import flet as ft
import pyperclip

from verso.database import TaskRecord, get_recent_tasks, insert_task, update_task_title
from verso.sentinel import Sentinel
from verso.sentinel.clipboard_sensor import ClipboardSensor
from verso.services.notification_service import NotificationService
from verso.services.sound_service import SoundService
from verso.workers import WorkerManager

logger = logging.getLogger(__name__)

# Breakpoint width for docked auxiliary panel vs overlay drawer
BREAKPOINT_WIDTH: int = 680

# Complete Design Themes (Obsidian Dark & Crisp Porcelain Light)
THEMES: Dict[str, Dict[str, Any]] = {
    "dark": {
        "page_bg": "#0B0F17",
        "panel_bg": "#0D131F",
        "panel_border": "#1E293B",
        "card_bg": "#111827",
        "card_border": "#1F2937",
        "text_primary": "#F8FAFC",
        "text_secondary": "#94A3B8",
        "text_muted": "#64748B",
        "idle_gradient": ft.LinearGradient(
            begin=ft.Alignment(-1, -1),
            end=ft.Alignment(1, 1),
            colors=["#1E293B", "#0F172A"],
        ),
        "active_gradient": ft.LinearGradient(
            begin=ft.Alignment(-1, -1),
            end=ft.Alignment(1, 1),
            colors=["#3F0A1D", "#1E0610"],
        ),
        "idle_border": "#334155",
        "active_border": "#FB7185",
        "idle_shadow": ft.BoxShadow(
            spread_radius=1, blur_radius=20, color="#030712", offset=ft.Offset(0, 6)
        ),
        "active_shadow": ft.BoxShadow(
            spread_radius=2, blur_radius=24, color="#881337", offset=ft.Offset(0, 4)
        ),
        "idle_icon": "#38BDF8",
        "active_icon": "#FDA4AF",
        "top_btn_bg": "#111827",
        "top_btn_border": "#1E293B",
        "badge_slack_bg": "#082F49",
        "badge_slack_text": "#38BDF8",
        "badge_done_bg": "#064E3B",
        "badge_done_text": "#34D399",
        "backdrop_color": "#000000",
        "alert_bg": "#2A170A",
        "alert_border": "#D97706",
        "alert_title": "#F59E0B",
        "alert_text": "#FDE68A",
        "alert_btn": "#F59E0B",
    },
    "light": {
        "page_bg": "#F8FAFC",
        "panel_bg": "#FFFFFF",
        "panel_border": "#E2E8F0",
        "card_bg": "#F1F5F9",
        "card_border": "#E2E8F0",
        "text_primary": "#0F172A",
        "text_secondary": "#475569",
        "text_muted": "#64748B",
        "idle_gradient": ft.LinearGradient(
            begin=ft.Alignment(-1, -1),
            end=ft.Alignment(1, 1),
            colors=["#F1F5F9", "#E2E8F0"],
        ),
        "active_gradient": ft.LinearGradient(
            begin=ft.Alignment(-1, -1),
            end=ft.Alignment(1, 1),
            colors=["#FFE4E6", "#FECDD3"],
        ),
        "idle_border": "#CBD5E1",
        "active_border": "#F43F5E",
        "idle_shadow": ft.BoxShadow(
            spread_radius=1, blur_radius=16, color="#CBD5E1", offset=ft.Offset(0, 4)
        ),
        "active_shadow": ft.BoxShadow(
            spread_radius=2, blur_radius=20, color="#FDA4AF", offset=ft.Offset(0, 4)
        ),
        "idle_icon": "#0284C7",
        "active_icon": "#E11D48",
        "top_btn_bg": "#FFFFFF",
        "top_btn_border": "#E2E8F0",
        "badge_slack_bg": "#E0F2FE",
        "badge_slack_text": "#0369A1",
        "badge_done_bg": "#DCFCE7",
        "badge_done_text": "#15803D",
        "backdrop_color": "#0F172A",
        "alert_bg": "#FEF3C7",
        "alert_border": "#F59E0B",
        "alert_title": "#B45309",
        "alert_text": "#78350F",
        "alert_btn": "#B45309",
    },
}


def open_deliverable(filepath: str = "deliverables/SLACK_DRAFT.md") -> None:
    """Opens the generated deliverable in the system default editor."""
    if not os.path.exists(filepath):
        logger.warning("Deliverable file not found: %s", filepath)
        return

    current_os = platform.system()
    try:
        if current_os == "Darwin":
            subprocess.run(["open", filepath], check=False)
        elif current_os == "Windows":
            os.startfile(filepath)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", filepath], check=False)
    except Exception as exc:
        logger.error("Failed to open deliverable file: %s", exc)


def open_system_security_settings() -> None:
    """Opens system privacy & security settings directly for the user."""
    current_os = platform.system()
    try:
        if current_os == "Darwin":
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"],
                check=False,
            )
        elif current_os == "Windows":
            subprocess.run(["start", "ms-settings:privacy"], shell=True, check=False)
        else:
            subprocess.run(["gnome-control-center"], check=False)
    except Exception as exc:
        logger.error("Failed to open system security settings: %s", exc)


def _default_chrome_height() -> float:
    """Initial title-bar height estimate (auto-refined by calibration)."""
    system = platform.system()
    if system == "Darwin":
        return 28.0
    if system == "Windows":
        return 32.0
    return 30.0


def create_app(page: ft.Page) -> None:
    current_theme = "dark"
    colors = THEMES[current_theme]
    is_history_open: bool = False
    worker_manager: Optional[WorkerManager] = None

    # Window Configuration (initial size 460x700, user-resizable)
    page.title = "V.E.R.S.O."
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = colors["page_bg"]
    page.window.width = 460
    page.window.height = 700
    page.window.min_width = 380
    page.window.min_height = 500
    page.window.resizable = True
    page.window.prevent_close = True
    page.padding = 0

    # 1. Top Bar Controls
    history_icon = ft.Icon(icon=ft.Icons.HISTORY_ROUNDED, size=20, color=colors["text_secondary"])
    history_btn = ft.Container(
        content=history_icon,
        width=38,
        height=38,
        border_radius=19,
        bgcolor=colors["top_btn_bg"],
        border=ft.Border.all(1, colors["top_btn_border"]),
        alignment=ft.Alignment(0, 0),
        ink=True,
        tooltip="Toggle Task History",
    )

    home_icon = ft.Icon(icon=ft.Icons.HOME_ROUNDED, size=20, color=colors["text_secondary"])
    home_btn = ft.Container(
        content=home_icon,
        width=38,
        height=38,
        border_radius=19,
        bgcolor=colors["top_btn_bg"],
        border=ft.Border.all(1, colors["top_btn_border"]),
        alignment=ft.Alignment(0, 0),
        ink=True,
        visible=False,
        tooltip="Return to Home View (Central Button)",
    )

    compact_toggle_icon = ft.Icon(icon=ft.Icons.PLAY_ARROW_ROUNDED, size=20, color=colors["idle_icon"])
    compact_toggle_btn = ft.Container(
        content=compact_toggle_icon,
        width=38,
        height=38,
        border_radius=19,
        bgcolor=colors["top_btn_bg"],
        border=ft.Border.all(1, colors["top_btn_border"]),
        alignment=ft.Alignment(0, 0),
        ink=True,
        visible=False,
        tooltip="Start / Pause Listening",
    )

    # Voice Mode Toggle Button (Activated vs Deactivated)
    is_voice_enabled: bool = True
    voice_toggle_icon = ft.Icon(icon=ft.Icons.MIC_ROUNDED, size=18, color=colors["idle_icon"])
    voice_toggle_btn = ft.Container(
        content=voice_toggle_icon,
        width=38,
        height=38,
        border_radius=19,
        bgcolor=colors["top_btn_bg"],
        border=ft.Border.all(1, colors["top_btn_border"]),
        alignment=ft.Alignment(0, 0),
        ink=True,
        tooltip="Voice Mode: Active (Click to Deactivate)",
    )

    # Mini Desktop Widget Mode Toggle Button (always on top by design)
    widget_mode_icon = ft.Icon(icon=ft.Icons.PICTURE_IN_PICTURE_ALT_ROUNDED, size=18, color=colors["text_secondary"])
    widget_mode_btn = ft.Container(
        content=widget_mode_icon,
        width=38,
        height=38,
        border_radius=19,
        bgcolor=colors["top_btn_bg"],
        border=ft.Border.all(1, colors["top_btn_border"]),
        alignment=ft.Alignment(0, 0),
        ink=True,
        tooltip="Switch to Widget Mode (always on top)",
    )

    theme_icon = ft.Icon(icon=ft.Icons.LIGHT_MODE_ROUNDED, size=20, color=colors["text_secondary"])
    theme_btn = ft.Container(
        content=theme_icon,
        width=38,
        height=38,
        border_radius=19,
        bgcolor=colors["top_btn_bg"],
        border=ft.Border.all(1, colors["top_btn_border"]),
        alignment=ft.Alignment(0, 0),
        ink=True,
        tooltip="Switch to Light Mode",
    )

    top_bar = ft.Container(
        padding=ft.Padding(left=20, top=16, right=20, bottom=8),
        content=ft.Row(
            [
                ft.Row([history_btn, home_btn], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Container(expand=True),
                ft.Row(
                    [compact_toggle_btn, voice_toggle_btn, widget_mode_btn, theme_btn],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    # 2. UI Error / Permission Alert Banner
    alert_icon = ft.Icon(
        icon=ft.Icons.WARNING_AMBER_ROUNDED,
        size=20,
        color=colors["alert_title"],
    )
    alert_title = ft.Text(
        "Permission Required",
        size=11,
        weight=ft.FontWeight.W_700,
        color=colors["alert_title"],
    )
    alert_text = ft.Text(
        "",
        size=11,
        color=colors["alert_text"],
        expand=True,
        weight=ft.FontWeight.W_400,
    )
    alert_btn_text = ft.Text(
        "Settings",
        size=11,
        weight=ft.FontWeight.W_600,
        color=colors["alert_btn"],
    )
    alert_settings_btn = ft.TextButton(
        content=alert_btn_text,
        on_click=lambda e: open_system_security_settings(),
        tooltip="Open Security Settings",
    )

    def dismiss_alert(e=None) -> None:
        alert_banner.visible = False
        if not sentinel.is_running:
            c = THEMES[current_theme]
            status_dot.bgcolor = c["text_muted"]
            status_text.value = "Idle · Tap button to start listening"
        page.update()

    alert_close_btn = ft.IconButton(
        icon=ft.Icons.CLOSE_ROUNDED,
        icon_size=16,
        icon_color=colors["alert_btn"],
        tooltip="Dismiss",
        on_click=dismiss_alert,
    )

    alert_banner = ft.Container(
        margin=ft.Margin(left=18, top=4, right=18, bottom=8),
        padding=ft.Padding(left=12, top=10, right=8, bottom=10),
        border_radius=8,
        bgcolor=colors["alert_bg"],
        border=ft.Border.all(1, colors["alert_border"]),
        visible=False,
        animate=ft.Animation(250, ft.AnimationCurve.EASE_OUT),
        content=ft.Row(
            [
                alert_icon,
                ft.Column(
                    [
                        alert_title,
                        alert_text,
                    ],
                    spacing=2,
                    expand=True,
                ),
                alert_settings_btn,
                alert_close_btn,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=6,
        ),
    )

    # 3. Main Companion Controls (Title, Tactile Button, Status)
    title = ft.Text(
        "V.E.R.S.O.",
        size=24,
        weight=ft.FontWeight.W_700,
        style=ft.TextStyle(letter_spacing=4.0, color=colors["text_primary"]),
    )

    btn_icon = ft.Icon(
        icon=ft.Icons.PLAY_ARROW_ROUNDED,
        size=38,
        color=colors["idle_icon"],
    )

    toggle_container = ft.Container(
        width=84,
        height=84,
        shape=ft.BoxShape.CIRCLE,
        gradient=colors["idle_gradient"],
        border=ft.Border.all(1.5, colors["idle_border"]),
        shadow=colors["idle_shadow"],
        alignment=ft.Alignment(0, 0),
        content=btn_icon,
        ink=True,
        animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
    )

    status_dot = ft.Container(
        width=8,
        height=8,
        shape=ft.BoxShape.CIRCLE,
        bgcolor=colors["text_muted"],
        animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
    )

    status_text = ft.Text(
        "Idle · Tap button to start listening",
        size=12,
        color=colors["text_muted"],
        weight=ft.FontWeight.W_400,
        text_align=ft.TextAlign.CENTER,
        no_wrap=False,
    )

    status_row = ft.Container(
        content=ft.Row(
            [status_dot, status_text],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
            wrap=True,
        ),
        padding=ft.Padding(left=20, top=0, right=20, bottom=0),
        alignment=ft.Alignment(0, 0),
    )

    # 3.1 Central Response Card (surfaces the generated response with 1-click copy)
    response_badge = ft.Container(
        content=ft.Text(
            "RESPONSE READY",
            size=9,
            weight=ft.FontWeight.W_700,
            color=colors["badge_done_text"],
        ),
        bgcolor=colors["badge_done_bg"],
        border_radius=4,
        padding=ft.Padding(left=6, top=2, right=6, bottom=2),
    )

    response_sender_text = ft.Text(
        "",
        size=11,
        weight=ft.FontWeight.W_600,
        color=colors["text_secondary"],
    )

    def dismiss_response(e=None) -> None:
        response_card.visible = False
        page.update()

    response_close_btn = ft.IconButton(
        icon=ft.Icons.CLOSE_ROUNDED,
        icon_size=16,
        icon_color=colors["text_muted"],
        tooltip="Dismiss",
        on_click=dismiss_response,
    )

    response_body_text = ft.Text(
        "",
        size=12,
        color=colors["text_primary"],
        selectable=True,
    )

    copy_btn_icon = ft.Icon(icon=ft.Icons.CONTENT_COPY_ROUNDED, size=15, color="#FFFFFF")
    copy_btn_text = ft.Text("Copy Response", size=11, weight=ft.FontWeight.W_600, color="#FFFFFF")

    latest_response_text: str = ""
    saved_window_width: float = 460
    saved_window_height: float = 700
    is_mini_mode: bool = False

    # Live window-size tracking. Manual resizes are not reported back into
    # page.window.width/height, so the real content size is captured from
    # resize events and converted with a calibrated chrome delta.
    live_content_width: Optional[float] = None
    live_content_height: Optional[float] = None
    chrome_dw: float = 0.0
    chrome_dh: float = _default_chrome_height()
    pending_probe: Optional[Tuple[float, float, float]] = None

    def copy_main_response(e=None) -> None:
        nonlocal latest_response_text
        if not response_body_text.value:
            return
        latest_response_text = response_body_text.value
        ClipboardSensor.ignore_content(response_body_text.value)
        try:
            pyperclip.copy(response_body_text.value)
            page.set_clipboard(response_body_text.value)
        except Exception:
            pass
        copy_btn_icon.icon = ft.Icons.CHECK_ROUNDED
        copy_btn_text.value = "Copied!"
        status_text.value = "Response copied to clipboard (Cmd+V)!"
        status_dot.bgcolor = "#10B981"
        page.update()

        def reset_btn():
            time.sleep(2.0)
            copy_btn_icon.icon = ft.Icons.CONTENT_COPY_ROUNDED
            copy_btn_text.value = "Copy Response"
            page.update()

        threading.Thread(target=reset_btn, daemon=True).start()

    copy_response_btn = ft.Container(
        content=ft.Row(
            [copy_btn_icon, copy_btn_text],
            spacing=6,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor="#0284C7",
        border_radius=8,
        padding=ft.Padding(left=14, top=8, right=14, bottom=8),
        ink=True,
        on_click=copy_main_response,
        tooltip="Copy directly to clipboard (Cmd+V)",
    )

    # 3.4 Mini Desktop Widget Layout
    mini_dot = ft.Container(
        width=8,
        height=8,
        shape=ft.BoxShape.CIRCLE,
        bgcolor=colors["text_muted"],
        animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
    )
    mini_icon = ft.Icon(
        icon=ft.Icons.RADIO_BUTTON_UNCHECKED_ROUNDED,
        size=15,
        color=colors["idle_icon"],
    )
    mini_brand_text = ft.Text(
        "V.E.R.S.O.",
        size=10,
        weight=ft.FontWeight.W_700,
        style=ft.TextStyle(letter_spacing=1.5, color=colors["text_primary"]),
    )
    mini_status_label = ft.Text(
        "Idle",
        size=10,
        weight=ft.FontWeight.W_500,
        color=colors["text_muted"],
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
    )
    mini_status_col = ft.Column(
        [mini_brand_text, mini_status_label],
        spacing=1,
        alignment=ft.MainAxisAlignment.CENTER,
    )
    mini_left_row = ft.Row(
        [mini_dot, mini_icon, mini_status_col],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    # The whole status zone is clickable: one tap on the left side of the
    # widget returns to the full window (same action as the expand button,
    # wired below next to exit_mini_mode).
    mini_home_zone = ft.Container(
        content=mini_left_row,
        ink=True,
        tooltip="Back to full window",
    )

    mini_copy_icon = ft.Icon(icon=ft.Icons.CONTENT_COPY_ROUNDED, size=14, color="#FFFFFF")
    mini_copy_btn = ft.Container(
        content=mini_copy_icon,
        width=28,
        height=28,
        border_radius=6,
        bgcolor="#0284C7",
        alignment=ft.Alignment(0, 0),
        ink=True,
        visible=False,
        tooltip="Copy Response (Cmd+V)",
    )

    def copy_mini_response(e=None) -> None:
        nonlocal latest_response_text
        if not latest_response_text:
            return
        ClipboardSensor.ignore_content(latest_response_text)
        try:
            pyperclip.copy(latest_response_text)
            page.set_clipboard(latest_response_text)
        except Exception:
            pass
        mini_copy_icon.icon = ft.Icons.CHECK_ROUNDED
        mini_status_label.value = "Copied!"
        page.update()

        def reset_mini_btn():
            time.sleep(2.0)
            mini_copy_icon.icon = ft.Icons.CONTENT_COPY_ROUNDED
            if latest_response_text:
                mini_status_label.value = "Ready (Cmd+V)"
            page.update()

        threading.Thread(target=reset_mini_btn, daemon=True).start()

    mini_copy_btn.on_click = copy_mini_response

    mini_sentinel_icon = ft.Icon(
        icon=ft.Icons.PLAY_ARROW_ROUNDED,
        size=16,
        color=colors["idle_icon"],
    )
    mini_sentinel_btn = ft.Container(
        content=mini_sentinel_icon,
        width=28,
        height=28,
        border_radius=6,
        bgcolor=colors["top_btn_bg"],
        border=ft.Border.all(1, colors["top_btn_border"]),
        alignment=ft.Alignment(0, 0),
        ink=True,
        tooltip="Start / Pause Listening",
    )

    # Primary widget action: back to the full window (accent filled, always visible).
    mini_expand_icon = ft.Icon(
        icon=ft.Icons.OPEN_IN_FULL_ROUNDED,
        size=14,
        color="#FFFFFF",
    )
    mini_expand_btn = ft.Container(
        content=mini_expand_icon,
        width=28,
        height=28,
        border_radius=6,
        bgcolor="#0284C7",
        alignment=ft.Alignment(0, 0),
        ink=True,
        tooltip="Back to full window",
    )

    def exit_app(e=None) -> None:
        page.window.prevent_close = False
        page.update()
        try:
            page.run_task(page.window.destroy)
        except Exception:
            pass

    mini_close_icon = ft.Icon(
        icon=ft.Icons.CLOSE_ROUNDED,
        size=14,
        color=colors["text_muted"],
    )
    mini_close_btn = ft.Container(
        content=mini_close_icon,
        width=28,
        height=28,
        border_radius=6,
        bgcolor=colors["top_btn_bg"],
        border=ft.Border.all(1, colors["top_btn_border"]),
        alignment=ft.Alignment(0, 0),
        ink=True,
        on_click=exit_app,
        tooltip="Exit V.E.R.S.O.",
    )

    mini_voice_icon = ft.Icon(icon=ft.Icons.MIC_ROUNDED, size=14, color=colors["idle_icon"])
    mini_voice_btn = ft.Container(
        content=mini_voice_icon,
        width=28,
        height=28,
        border_radius=6,
        bgcolor=colors["top_btn_bg"],
        border=ft.Border.all(1, colors["top_btn_border"]),
        alignment=ft.Alignment(0, 0),
        ink=True,
        tooltip="Voice Mode: Active (Click to Deactivate)",
    )

    mini_actions_row = ft.Row(
        [mini_copy_btn, mini_voice_btn, mini_sentinel_btn, mini_expand_btn, mini_close_btn],
        spacing=6,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    mini_widget_row = ft.Row(
        [mini_home_zone, ft.Container(expand=True), mini_actions_row],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # Quick-reply buttons shown directly below the widget row in mini mode, so
    # the user can 1-click an answer without opening the full window.
    MINI_COMPACT_HEIGHT = 76
    MINI_OPTION_ROW_H = 54
    mini_options_col = ft.Column([], spacing=6)

    mini_widget_view = ft.Container(
        content=ft.Column(
            [mini_widget_row, mini_options_col],
            spacing=6,
        ),
        expand=True,
        bgcolor=colors["panel_bg"],
        padding=ft.Padding(left=12, top=6, right=12, bottom=6),
        border=ft.Border.all(1, colors["panel_border"]),
    )

    response_card_inner = ft.Container(
        content=response_body_text,
        bgcolor=colors["panel_bg"],
        border_radius=6,
        padding=10,
    )

    # -----------------------------------------------------------------
    # Quick Replies Card (Voice Deactivated / Silent Mode)
    # -----------------------------------------------------------------
    current_quick_payload: Dict[str, Any] = {}

    quick_badge = ft.Container(
        content=ft.Text(
            "QUICK REPLIES",
            size=10,
            weight=ft.FontWeight.W_700,
            style=ft.TextStyle(letter_spacing=0.8, color=colors["badge_slack_text"]),
        ),
        bgcolor=colors["badge_slack_bg"],
        border_radius=4,
        padding=ft.Padding(left=6, top=2, right=6, bottom=2),
    )

    quick_sender_text = ft.Text(
        "",
        size=11,
        weight=ft.FontWeight.W_600,
        color=colors["text_secondary"],
        expand=True,
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
    )

    def dismiss_quick_replies(e=None) -> None:
        quick_replies_card.visible = False
        collapse_mini_options()
        page.update()

    quick_close_btn = ft.IconButton(
        icon=ft.Icons.CLOSE_ROUNDED,
        icon_size=16,
        icon_color=colors["text_muted"],
        tooltip="Dismiss",
        on_click=dismiss_quick_replies,
    )

    quick_summary_text = ft.Text(
        "",
        size=12,
        color=colors["text_primary"],
        weight=ft.FontWeight.W_500,
    )

    quick_summary_box = ft.Container(
        content=quick_summary_text,
        bgcolor=colors["panel_bg"],
        border_radius=6,
        padding=10,
    )

    quick_options_col = ft.Column([], spacing=8)

    need_another_icon = ft.Icon(icon=ft.Icons.REFRESH_ROUNDED, size=14, color=colors["idle_icon"])
    need_another_label = ft.Text(
        "Need another response?",
        size=11,
        weight=ft.FontWeight.W_500,
        color=colors["idle_icon"],
    )
    need_another_btn = ft.Container(
        content=ft.Row(
            [need_another_icon, need_another_label],
            spacing=4,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        ink=True,
        border_radius=6,
        padding=ft.Padding(left=10, top=6, right=10, bottom=6),
        bgcolor=colors["badge_slack_bg"],
        tooltip="Generate fresh alternative replies",
    )

    quick_custom_input = ft.TextField(
        hint_text="Or type custom reply / instructions...",
        hint_style=ft.TextStyle(size=11, color=colors["text_muted"]),
        text_size=12,
        color=colors["text_primary"],
        border_color=colors["card_border"],
        focused_border_color=colors["idle_icon"],
        border_radius=6,
        content_padding=ft.Padding(left=10, top=6, right=10, bottom=6),
        expand=True,
    )

    quick_custom_send_icon = ft.Icon(icon=ft.Icons.SEND_ROUNDED, size=14, color="#FFFFFF")
    quick_custom_send_btn = ft.Container(
        content=quick_custom_send_icon,
        width=32,
        height=32,
        border_radius=6,
        bgcolor="#0284C7",
        alignment=ft.Alignment(0, 0),
        ink=True,
        tooltip="Send Custom Response",
    )

    quick_replies_card = ft.Container(
        width=380,
        margin=ft.Margin(left=20, top=14, right=20, bottom=10),
        padding=14,
        border_radius=10,
        bgcolor=colors["card_bg"],
        border=ft.Border.all(1, colors["card_border"]),
        visible=False,
        animate=ft.Animation(250, ft.AnimationCurve.EASE_OUT),
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Row(
                            [quick_badge, quick_sender_text],
                            spacing=8,
                            expand=True,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        quick_close_btn,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                quick_summary_box,
                ft.Text(
                    "Choose a quick reply:",
                    size=11,
                    weight=ft.FontWeight.W_600,
                    color=colors["text_secondary"],
                ),
                quick_options_col,
                ft.Divider(height=1, color=colors["card_border"]),
                ft.Row([need_another_btn], alignment=ft.MainAxisAlignment.CENTER),
                ft.Row(
                    [quick_custom_input, quick_custom_send_btn],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=10,
        ),
    )

    response_card = ft.Container(
        width=380,
        margin=ft.Margin(left=20, top=16, right=20, bottom=12),
        padding=14,
        border_radius=10,
        bgcolor=colors["card_bg"],
        border=ft.Border.all(1, colors["card_border"]),
        visible=False,
        animate=ft.Animation(250, ft.AnimationCurve.EASE_OUT),
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Row(
                            [response_badge, response_sender_text],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        response_close_btn,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                response_card_inner,
                ft.Row(
                    [
                        ft.Container(expand=True),
                        copy_response_btn,
                    ],
                    alignment=ft.MainAxisAlignment.END,
                ),
            ],
            spacing=10,
        ),
    )

    # 3.2 Home View (Companion Center with large tactile button)
    home_view = ft.Column(
        [
            ft.Container(height=16),
            title,
            ft.Container(height=24),
            toggle_container,
            ft.Container(height=18),
            status_row,
            quick_replies_card,
            response_card,
            ft.Container(height=24),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
    )

    # 3.3 Details View (Task Details with editable title, full exchange, and copy button)
    current_selected_task_id: Optional[int] = None

    details_title_field = ft.TextField(
        value="",
        text_size=17,
        text_style=ft.TextStyle(weight=ft.FontWeight.W_700, color=colors["text_primary"]),
        color=colors["text_primary"],
        border=ft.InputBorder.UNDERLINE,
        border_color=colors["idle_border"],
        focused_border_color=colors["idle_icon"],
        content_padding=ft.Padding(left=4, top=4, right=4, bottom=6),
        expand=True,
        hint_text="Task title...",
        hint_style=ft.TextStyle(color=colors["text_muted"], size=14),
    )

    details_save_icon = ft.IconButton(
        icon=ft.Icons.CHECK_ROUNDED,
        icon_size=20,
        icon_color=colors["idle_icon"],
        tooltip="Save Title",
    )

    def save_task_title(e=None):
        nonlocal current_selected_task_id
        if current_selected_task_id is not None:
            new_title = details_title_field.value.strip() or "Response"
            update_task_title(current_selected_task_id, new_title)
            render_history_items()
            status_text.value = f"Title updated: {new_title}"
            status_dot.bgcolor = "#10B981"
            page.update()

    details_title_field.on_submit = save_task_title
    details_save_icon.on_click = save_task_title

    details_meta_row = ft.Row(spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    details_msg_text = ft.Text("", size=12, color=colors["text_secondary"], selectable=True)
    details_msg_container = ft.Container(
        bgcolor=colors["panel_bg"],
        border_radius=8,
        padding=12,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(icon=ft.Icons.FORUM_OUTLINED, size=15, color=colors["text_muted"]),
                        ft.Text(
                            "RECEIVED MESSAGE",
                            size=10,
                            weight=ft.FontWeight.W_700,
                            style=ft.TextStyle(letter_spacing=1.0, color=colors["text_muted"]),
                        ),
                    ],
                    spacing=6,
                ),
                details_msg_text,
            ],
            spacing=6,
        ),
    )

    details_dialogue_column = ft.Column(spacing=6)
    details_dialogue_container = ft.Container(
        bgcolor=colors["panel_bg"],
        border=ft.Border.all(1, colors["card_border"]),
        border_radius=8,
        padding=12,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(icon=ft.Icons.RECORD_VOICE_OVER_ROUNDED, size=15, color=colors["idle_icon"]),
                        ft.Text(
                            "AMBIENT VOCAL EXCHANGE",
                            size=10,
                            weight=ft.FontWeight.W_700,
                            style=ft.TextStyle(letter_spacing=1.0, color=colors["idle_icon"]),
                        ),
                    ],
                    spacing=6,
                ),
                details_dialogue_column,
            ],
            spacing=6,
        ),
    )

    details_response_text = ft.Text("", size=12, color=colors["text_primary"], selectable=True)
    details_copy_icon = ft.Icon(icon=ft.Icons.CONTENT_COPY_ROUNDED, size=15, color="#FFFFFF")
    details_copy_text = ft.Text("Copy Response", size=11, weight=ft.FontWeight.W_600, color="#FFFFFF")

    def copy_details_response(e=None):
        nonlocal latest_response_text
        if not details_response_text.value:
            return
        latest_response_text = details_response_text.value
        ClipboardSensor.ignore_content(details_response_text.value)
        try:
            pyperclip.copy(details_response_text.value)
            page.set_clipboard(details_response_text.value)
        except Exception:
            pass
        details_copy_icon.icon = ft.Icons.CHECK_ROUNDED
        details_copy_text.value = "Copied!"
        status_text.value = "Response copied to clipboard (Cmd+V)!"
        status_dot.bgcolor = "#10B981"
        page.update()

        def reset_btn():
            time.sleep(2.0)
            details_copy_icon.icon = ft.Icons.CONTENT_COPY_ROUNDED
            details_copy_text.value = "Copy Response"
            page.update()

        threading.Thread(target=reset_btn, daemon=True).start()

    details_copy_btn = ft.Container(
        content=ft.Row(
            [details_copy_icon, details_copy_text],
            spacing=6,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor="#0284C7",
        border_radius=8,
        padding=ft.Padding(left=14, top=8, right=14, bottom=8),
        ink=True,
        on_click=copy_details_response,
        tooltip="Copy response to clipboard (Cmd+V)",
    )

    details_response_container = ft.Container(
        bgcolor=colors["card_bg"],
        border=ft.Border.all(1, colors["idle_border"]),
        border_radius=8,
        padding=12,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Row(
                            [
                                ft.Icon(icon=ft.Icons.AUTO_AWESOME_ROUNDED, size=15, color=colors["badge_slack_text"]),
                                ft.Text(
                                    "READY RESPONSE",
                                    size=10,
                                    weight=ft.FontWeight.W_700,
                                    style=ft.TextStyle(letter_spacing=1.0, color=colors["badge_slack_text"]),
                                ),
                            ],
                            spacing=6,
                        ),
                        details_copy_btn,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=4),
                details_response_text,
            ],
            spacing=6,
        ),
    )

    details_view = ft.Container(
        expand=True,
        padding=ft.Padding(left=24, top=12, right=24, bottom=24),
        content=ft.Column(
            [
                ft.Row(
                    [
                        details_title_field,
                        details_save_icon,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                details_meta_row,
                ft.Divider(height=16, color=colors["card_border"]),
                details_msg_container,
                details_dialogue_container,
                details_response_container,
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

    content_area = ft.Container(
        content=home_view,
        expand=True,
        alignment=ft.Alignment(0, 0),
    )

    main_view = ft.Container(
        expand=True,
        alignment=ft.Alignment(0, 0),
        content=ft.Column(
            [
                top_bar,
                alert_banner,
                content_area,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        ),
    )

    # Helper navigation: Show Details View vs Return to Home View
    def show_task_details(task: TaskRecord) -> None:
        nonlocal current_selected_task_id
        current_selected_task_id = task.id
        c = THEMES[current_theme]

        details_title_field.value = task.action_title

        time_str = (
            task.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(task.timestamp, datetime)
            else str(task.timestamp)
        )
        details_meta_row.controls = [
            ft.Container(
                content=ft.Text(task.trigger_source, size=10, weight=ft.FontWeight.W_600, color=c["badge_slack_text"]),
                bgcolor=c["badge_slack_bg"],
                border_radius=4,
                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
            ),
            ft.Container(
                content=ft.Text(task.status, size=10, weight=ft.FontWeight.W_600, color=c["badge_done_text"]),
                bgcolor=c["badge_done_bg"],
                border_radius=4,
                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
            ),
            ft.Text(time_str, size=11, color=c["text_muted"]),
        ]

        if task.incoming_message:
            details_msg_text.value = task.incoming_message.replace("From ", "").strip()
            details_msg_container.visible = True
        else:
            details_msg_container.visible = False

        details_dialogue_column.controls.clear()
        if task.ai_suggestion or task.user_response:
            if task.ai_suggestion:
                details_dialogue_column.controls.append(
                    ft.Row(
                        [
                            ft.Text("🤖", size=13),
                            ft.Text(task.ai_suggestion, size=11, color=c["text_primary"], weight=ft.FontWeight.W_500, expand=True),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    )
                )
            if task.user_response:
                details_dialogue_column.controls.append(
                    ft.Row(
                        [
                            ft.Text("🗣️", size=13),
                            ft.Text(f"You: '{task.user_response}'", size=11, color=c["text_secondary"], style=ft.TextStyle(italic=True), expand=True),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    )
                )
            details_dialogue_container.visible = True
        else:
            details_dialogue_container.visible = False

        if task.final_response:
            latest_response_text = task.final_response
            mini_copy_btn.visible = True
            details_response_text.value = task.final_response
            details_response_container.visible = True
        else:
            details_response_container.visible = False

        content_area.content = details_view
        home_btn.visible = True
        compact_toggle_btn.visible = True
        page.update()

    def return_to_home(e=None) -> None:
        content_area.content = home_view
        home_btn.visible = False
        compact_toggle_btn.visible = False
        page.update()

    home_btn.on_click = return_to_home

    # 4. History List Views (Independent for Docked Panel & Overlay Drawer)
    list_docked = ft.ListView(
        spacing=8,
        padding=ft.Padding(left=12, top=6, right=12, bottom=16),
        auto_scroll=False,
        expand=True,
    )

    list_drawer = ft.ListView(
        spacing=8,
        padding=ft.Padding(left=12, top=6, right=12, bottom=16),
        auto_scroll=False,
        expand=True,
    )

    def build_task_card(task: TaskRecord, c: Dict[str, Any]) -> ft.Container:
        """Builds a clean, compact history list item with multiline text wrapping."""
        time_str = (
            task.timestamp.strftime("%H:%M")
            if isinstance(task.timestamp, datetime)
            else str(task.timestamp)[:5]
        )
        return ft.Container(
            bgcolor=c["card_bg"],
            border=ft.Border.all(1, c["card_border"]),
            border_radius=8,
            padding=ft.Padding(left=12, top=10, right=10, bottom=10),
            ink=True,
            on_click=lambda e, t=task: show_task_details(t),
            tooltip=f"Details for {task.action_title}",
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Icon(icon=ft.Icons.RECORD_VOICE_OVER_ROUNDED, size=15, color=c["idle_icon"]),
                            ft.Text(
                                task.action_title,
                                size=12,
                                weight=ft.FontWeight.W_600,
                                color=c["text_primary"],
                                expand=True,
                                no_wrap=False,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        expand=True,
                    ),
                    ft.Row(
                        [
                            ft.Text(time_str, size=10, color=c["text_muted"]),
                            ft.Icon(icon=ft.Icons.CHEVRON_RIGHT_ROUNDED, size=16, color=c["text_muted"]),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        )

    def render_history_items() -> None:
        """Renders recent tasks from database into both history list views."""
        list_docked.controls.clear()
        list_drawer.controls.clear()

        recent_tasks: List[TaskRecord] = get_recent_tasks(limit=30)
        c = THEMES[current_theme]

        if not recent_tasks:
            placeholder = ft.Container(
                content=ft.Text(
                    "No tasks recorded yet.\nV.E.R.S.O. is listening.",
                    size=12,
                    color=c["text_muted"],
                    text_align=ft.TextAlign.CENTER,
                ),
                alignment=ft.Alignment(0, 0),
                padding=28,
            )
            list_docked.controls.append(placeholder)
            list_drawer.controls.append(placeholder)
        else:
            for task in recent_tasks:
                list_docked.controls.append(build_task_card(task, c))
                list_drawer.controls.append(build_task_card(task, c))

    # Helper function to check if current window width supports docked panel
    def is_wide_enough() -> bool:
        if live_content_width is not None:
            return live_content_width >= BREAKPOINT_WIDTH
        current_w = page.width or (page.window.width if hasattr(page.window, "width") else 460) or 460
        return current_w >= BREAKPOINT_WIDTH

    pane_width: int = 300

    def on_pane_drag(e: ft.DragUpdateEvent) -> None:
        nonlocal pane_width
        current_w = page.width or (page.window.width if hasattr(page.window, "width") else 460) or 460
        max_allowed = max(240, int(current_w * 0.65)) if is_wide_enough() else max(240, int(current_w - 40))
        new_width = max(220, min(max_allowed, pane_width + int(e.delta_x)))
        pane_width = int(new_width)
        if is_wide_enough():
            docked_pane.width = pane_width
        else:
            overlay_drawer.width = pane_width
        page.update()

    def create_resizer_handle():
        return ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.RESIZE_LEFT_RIGHT,
            drag_interval=10,
            on_pan_update=on_pane_drag,
            content=ft.Container(
                width=10,
                bgcolor=ft.Colors.TRANSPARENT,
                alignment=ft.Alignment(0, 0),
                content=ft.Container(
                    width=2,
                    border_radius=1,
                    bgcolor=colors["panel_border"],
                ),
            ),
        )

    def update_history_layout() -> None:
        """Adapts the UI layout between docked left side panel and overlay drawer."""
        c = THEMES[current_theme]
        wide = is_wide_enough()
        current_w = page.width or (page.window.width if hasattr(page.window, "width") else 460) or 460

        if not is_history_open:
            docked_pane.visible = False
            docked_pane.width = 0
            overlay_drawer.left = -max(340, pane_width + 40)
            backdrop.visible = False
            history_btn.bgcolor = c["top_btn_bg"]
            history_btn.border = ft.Border.all(1, c["top_btn_border"])
        else:
            history_btn.bgcolor = c["card_bg"]
            history_btn.border = ft.Border.all(1, c["idle_border"])

            if wide:
                docked_pane.visible = True
                docked_pane.width = pane_width
                overlay_drawer.left = -max(340, pane_width + 40)
                backdrop.visible = False
            else:
                docked_pane.visible = False
                docked_pane.width = 0
                overlay_drawer.width = min(pane_width, max(240, int(current_w - 40)))
                overlay_drawer.left = 0
                backdrop.visible = True

        page.update()

    def close_history(e=None) -> None:
        nonlocal is_history_open
        is_history_open = False
        update_history_layout()

    def toggle_history(e=None) -> None:
        nonlocal is_history_open
        is_history_open = not is_history_open
        if is_history_open:
            render_history_items()
        update_history_layout()

    history_btn.on_click = toggle_history

    def sync_window() -> None:
        """Pushes pending window-geometry changes in a dedicated patch.

        Whole-page updates do not reliably pick up nested ``page.window``
        mutations (size silently never applied in either direction), while a
        targeted ``window.update()`` always emits a precise patch. Falls back
        to the page update when the window is not attached yet.
        """
        try:
            page.window.update()
        except RuntimeError:
            # Window not attached to the page yet (e.g. pre-mount) — the
            # following page.update() is the only channel available.
            pass

    def _best_window_size() -> Tuple[float, float]:
        """Best-known full window size (chrome included).

        Uses live resize-event data + calibrated chrome when available (manual
        resizes are not reported back into page.window.*); otherwise the
        programmatic values, which are exact when nothing was resized manually.
        """
        if live_content_width is not None and live_content_height is not None:
            return live_content_width + chrome_dw, live_content_height + chrome_dh
        return page.window.width or 460, page.window.height or 700

    def enter_mini_mode(e=None) -> None:
        nonlocal saved_window_width, saved_window_height, is_mini_mode
        nonlocal pending_probe
        if is_history_open:
            close_history()

        if not is_mini_mode:
            saved_window_width, saved_window_height = _best_window_size()
        is_mini_mode = True

        # Pending quick replies follow into the widget for 1-click answers.
        pending_options = (
            current_quick_payload.get("options", [])
            if quick_replies_card.visible
            else []
        )
        render_mini_options(pending_options)
        target_height = MINI_COMPACT_HEIGHT + len(pending_options) * MINI_OPTION_ROW_H

        # Widget mode is always on top by design (pinned desktop widget).
        # Staged for shrink: relax constraints first, shrink, then lock minimums
        # to the exact widget size so the user cannot shrink the widget.
        page.window.always_on_top = True
        page.window.min_width = 280
        page.window.min_height = 68
        sync_window()
        page.window.width = 330
        page.window.height = target_height
        sync_window()
        page.window.min_width = 330
        page.window.min_height = target_height
        sync_window()
        pending_probe = (330, target_height, time.monotonic() + 2.0)

        root_container.content = mini_widget_view
        page.update()

    def exit_mini_mode(e=None) -> None:
        nonlocal is_mini_mode, pending_probe
        is_mini_mode = False
        pending_probe = None  # exit events must never calibrate (no cross-talk)

        # Full window mode restores regular window state (not pinned).
        # Staged for grow: resize while unconstrained, then tighten minimums.
        page.window.always_on_top = False
        page.window.width = max(380, saved_window_width)
        page.window.height = max(500, saved_window_height)
        sync_window()
        page.window.min_width = 380
        page.window.min_height = 500
        sync_window()

        root_container.content = full_stack
        page.update()

    widget_mode_btn.on_click = enter_mini_mode
    mini_expand_btn.on_click = exit_mini_mode
    mini_home_zone.on_click = exit_mini_mode

    def update_voice_visuals() -> None:
        c = THEMES[current_theme]
        if is_voice_enabled:
            voice_toggle_icon.icon = ft.Icons.MIC_ROUNDED
            voice_toggle_icon.color = c["idle_icon"]
            voice_toggle_btn.tooltip = "Voice Mode: Active (Click to Deactivate)"
            mini_voice_icon.icon = ft.Icons.MIC_ROUNDED
            mini_voice_icon.color = c["idle_icon"]
            mini_voice_btn.tooltip = "Voice Mode: Active (Click to Deactivate)"
        else:
            voice_toggle_icon.icon = ft.Icons.MIC_OFF_ROUNDED
            voice_toggle_icon.color = c["text_muted"]
            voice_toggle_btn.tooltip = "Voice Mode: Deactivated / Quick Replies (Click to Activate)"
            mini_voice_icon.icon = ft.Icons.MIC_OFF_ROUNDED
            mini_voice_icon.color = c["text_muted"]
            mini_voice_btn.tooltip = "Voice Mode: Deactivated / Quick Replies (Click to Activate)"

    def toggle_voice_mode(e=None) -> None:
        nonlocal is_voice_enabled
        is_voice_enabled = not is_voice_enabled
        if worker_manager is not None:
            worker_manager.voice_enabled = is_voice_enabled
        update_voice_visuals()
        c = THEMES[current_theme]
        if is_voice_enabled:
            status_text.value = "Voice Mode active · Natural vocal interaction"
        else:
            status_text.value = "Voice Mode deactivated · Quick reply buttons"
        page.update()

    voice_toggle_btn.on_click = toggle_voice_mode
    mini_voice_btn.on_click = toggle_voice_mode

    def on_window_event(e: ft.WindowEvent) -> None:
        """Intercepts window close: switches to widget mode first, or exits if already in widget mode."""
        nonlocal is_mini_mode
        event_name = getattr(e, "data", "") or getattr(e, "type", "")
        if event_name == "close" or getattr(e, "type", None) == ft.WindowEventType.CLOSE:
            if not is_mini_mode:
                enter_mini_mode()
            else:
                exit_app()

    page.window.on_event = on_window_event

    def on_window_resize(e) -> None:
        """Tracks live size (manual resizes are not reported back into
        page.window.*), calibrates chrome from our own widget resize, and
        adapts the history layout."""
        nonlocal live_content_width, live_content_height
        nonlocal chrome_dw, chrome_dh, pending_probe
        try:
            event_w = float(e.width)
            event_h = float(e.height)
        except (TypeError, ValueError, AttributeError):
            event_w = None
            event_h = None
        if event_w is not None and event_h is not None:
            if (
                pending_probe is not None
                and is_mini_mode
                and time.monotonic() <= pending_probe[2]
            ):
                # Event answers our own widget resize (window is exactly the
                # probed size): measure the real chrome delta for conversions.
                chrome_dw = pending_probe[0] - event_w
                chrome_dh = pending_probe[1] - event_h
                pending_probe = None
            elif is_mini_mode:
                # Lock widget size: snap back any user resize attempt. The target
                # follows the shown content (compact, or grown for options).
                intended_h = float(MINI_COMPACT_HEIGHT + len(mini_options_col.controls) * MINI_OPTION_ROW_H)
                target_content_w = 330.0 - chrome_dw
                target_content_h = intended_h - chrome_dh
                if abs(event_w - target_content_w) > 2 or abs(event_h - target_content_h) > 2:
                    page.window.width = event_w + chrome_dw
                    page.window.height = event_h + chrome_dh
                    sync_window()
                    page.window.width = 330
                    page.window.height = intended_h
                    sync_window()
            else:
                live_content_width, live_content_height = event_w, event_h
        if not is_mini_mode and is_history_open:
            update_history_layout()

    page.on_resize = on_window_resize

    # 5. Docked Auxiliary Side Panel (Used when width >= BREAKPOINT_WIDTH)
    docked_header = ft.Container(
        padding=ft.Padding(left=16, top=16, right=12, bottom=10),
        content=ft.Row(
            [
                ft.Row(
                    [
                        ft.Icon(icon=ft.Icons.HISTORY_ROUNDED, size=18, color=colors["text_secondary"]),
                        ft.Text(
                            "TASK HISTORY",
                            size=12,
                            weight=ft.FontWeight.W_700,
                            style=ft.TextStyle(letter_spacing=1.5, color=colors["text_secondary"]),
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    [
                        ft.IconButton(
                            icon=ft.Icons.REFRESH_ROUNDED,
                            icon_size=18,
                            icon_color=colors["text_secondary"],
                            tooltip="Refresh",
                            on_click=lambda e: (render_history_items(), page.update()),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CHEVRON_LEFT_ROUNDED,
                            icon_size=20,
                            icon_color=colors["text_secondary"],
                            tooltip="Hide History",
                            on_click=close_history,
                        ),
                    ],
                    spacing=2,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    docked_resizer = create_resizer_handle()
    docked_pane = ft.Container(
        width=0,
        visible=False,
        bgcolor=colors["panel_bg"],
        content=ft.Row(
            [
                ft.Column(
                    [
                        docked_header,
                        list_docked,
                    ],
                    spacing=0,
                    expand=True,
                ),
                docked_resizer,
            ],
            spacing=0,
            expand=True,
        ),
    )

    # 6. Overlay Drawer & Backdrop (Used when width < BREAKPOINT_WIDTH)
    backdrop = ft.Container(
        top=0,
        bottom=0,
        left=0,
        right=0,
        bgcolor=colors["backdrop_color"],
        opacity=0.45,
        visible=False,
        on_click=close_history,
    )

    drawer_header = ft.Container(
        padding=ft.Padding(left=18, top=16, right=14, bottom=12),
        content=ft.Row(
            [
                ft.Row(
                    [
                        ft.Icon(icon=ft.Icons.HISTORY_ROUNDED, size=18, color=colors["text_secondary"]),
                        ft.Text(
                            "TASK HISTORY",
                            size=12,
                            weight=ft.FontWeight.W_700,
                            style=ft.TextStyle(letter_spacing=1.5, color=colors["text_secondary"]),
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    [
                        ft.IconButton(
                            icon=ft.Icons.REFRESH_ROUNDED,
                            icon_size=18,
                            icon_color=colors["text_secondary"],
                            tooltip="Refresh",
                            on_click=lambda e: (render_history_items(), page.update()),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CHEVRON_LEFT_ROUNDED,
                            icon_size=20,
                            icon_color=colors["text_secondary"],
                            tooltip="Close",
                            on_click=close_history,
                        ),
                    ],
                    spacing=2,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    drawer_resizer = create_resizer_handle()
    overlay_drawer = ft.Container(
        width=300,
        top=0,
        bottom=0,
        left=-340,
        animate_position=ft.Animation(300, ft.AnimationCurve.EASE_OUT_CUBIC),
        bgcolor=colors["panel_bg"],
        shadow=ft.BoxShadow(
            spread_radius=2,
            blur_radius=24,
            color="#000000",
            offset=ft.Offset(6, 0),
        ),
        content=ft.Row(
            [
                ft.Column(
                    [
                        drawer_header,
                        list_drawer,
                    ],
                    spacing=0,
                    expand=True,
                ),
                drawer_resizer,
            ],
            spacing=0,
            expand=True,
        ),
    )

    # 7. Light / Dark Theme Switching
    def apply_theme(theme_name: str) -> None:
        c = THEMES[theme_name]
        is_dark = theme_name == "dark"

        page.theme_mode = ft.ThemeMode.DARK if is_dark else ft.ThemeMode.LIGHT
        page.bgcolor = c["page_bg"]

        # Top Bar
        theme_icon.icon = ft.Icons.LIGHT_MODE_ROUNDED if is_dark else ft.Icons.DARK_MODE_ROUNDED
        theme_icon.color = c["text_secondary"]
        theme_btn.bgcolor = c["top_btn_bg"]
        theme_btn.border = ft.Border.all(1, c["top_btn_border"])
        theme_btn.tooltip = "Switch to Light Mode" if is_dark else "Switch to Dark Mode"

        history_icon.color = c["text_secondary"]
        if is_history_open:
            history_btn.bgcolor = c["card_bg"]
            history_btn.border = ft.Border.all(1, c["idle_border"])
        else:
            history_btn.bgcolor = c["top_btn_bg"]
            history_btn.border = ft.Border.all(1, c["top_btn_border"])

        # Alert Banner
        alert_banner.bgcolor = c["alert_bg"]
        alert_banner.border = ft.Border.all(1, c["alert_border"])
        alert_icon.color = c["alert_title"]
        alert_title.color = c["alert_title"]
        alert_text.color = c["alert_text"]
        alert_btn_text.color = c["alert_btn"]
        alert_close_btn.icon_color = c["alert_btn"]

        # Main Header Title
        title.style.color = c["text_primary"]

        # Central Button
        if sentinel.is_running:
            btn_icon.color = c["active_icon"]
            toggle_container.gradient = c["active_gradient"]
            toggle_container.border = ft.Border.all(1.5, c["active_border"])
            toggle_container.shadow = c["active_shadow"]
        else:
            btn_icon.color = c["idle_icon"]
            toggle_container.gradient = c["idle_gradient"]
            toggle_container.border = ft.Border.all(1.5, c["idle_border"])
            toggle_container.shadow = c["idle_shadow"]

        # Status Row
        if not sentinel.is_running:
            status_dot.bgcolor = c["text_muted"]
        status_text.color = c["text_muted"]

        # Left Panels & Backdrop
        docked_pane.bgcolor = c["panel_bg"]
        docked_resizer.content.content.bgcolor = c["panel_border"]
        overlay_drawer.bgcolor = c["panel_bg"]
        drawer_resizer.content.content.bgcolor = c["panel_border"]
        backdrop.bgcolor = c["backdrop_color"]

        # Central Response Card
        response_card.bgcolor = c["card_bg"]
        response_card.border = ft.Border.all(1, c["card_border"])
        response_badge.bgcolor = c["badge_done_bg"]
        response_badge.content.color = c["badge_done_text"]
        response_sender_text.color = c["text_secondary"]
        response_body_text.color = c["text_primary"]
        response_card_inner.bgcolor = c["panel_bg"]
        response_close_btn.icon_color = c["text_muted"]

        # Quick Replies Card Styling
        quick_replies_card.bgcolor = c["card_bg"]
        quick_replies_card.border = ft.Border.all(1, c["card_border"])
        quick_badge.bgcolor = c["badge_slack_bg"]
        quick_badge.content.color = c["badge_slack_text"]
        quick_sender_text.color = c["text_secondary"]
        quick_summary_box.bgcolor = c["panel_bg"]
        quick_summary_text.color = c["text_primary"]
        quick_close_btn.icon_color = c["text_muted"]
        need_another_btn.bgcolor = c["badge_slack_bg"]
        need_another_icon.color = c["idle_icon"]
        need_another_label.color = c["idle_icon"]
        quick_custom_input.color = c["text_primary"]
        quick_custom_input.border_color = c["card_border"]
        quick_custom_input.focused_border_color = c["idle_icon"]

        # Voice Mode Buttons Styling
        voice_toggle_btn.bgcolor = c["top_btn_bg"]
        voice_toggle_btn.border = ft.Border.all(1, c["top_btn_border"])
        mini_voice_btn.bgcolor = c["top_btn_bg"]
        mini_voice_btn.border = ft.Border.all(1, c["top_btn_border"])
        update_voice_visuals()

        # Top Bar Home & Compact Toggle Buttons
        home_icon.color = c["text_secondary"]
        home_btn.bgcolor = c["top_btn_bg"]
        home_btn.border = ft.Border.all(1, c["top_btn_border"])

        compact_toggle_btn.bgcolor = c["top_btn_bg"]
        compact_toggle_btn.border = ft.Border.all(1, c["top_btn_border"])
        compact_toggle_icon.color = c["active_icon"] if sentinel.is_running else c["idle_icon"]

        # Details View Styling
        details_title_field.color = c["text_primary"]
        details_title_field.border_color = c["idle_border"]
        details_title_field.focused_border_color = c["idle_icon"]
        details_save_icon.icon_color = c["idle_icon"]
        details_msg_container.bgcolor = c["panel_bg"]
        details_msg_text.color = c["text_secondary"]
        details_dialogue_container.bgcolor = c["panel_bg"]
        details_dialogue_container.border = ft.Border.all(1, c["card_border"])
        details_response_container.bgcolor = c["card_bg"]
        details_response_container.border = ft.Border.all(1, c["idle_border"])
        details_response_text.color = c["text_primary"]

        # Mini Desktop Widget Styling
        mini_widget_view.bgcolor = c["panel_bg"]
        mini_widget_view.border = ft.Border.all(1, c["panel_border"])
        mini_brand_text.style.color = c["text_primary"]
        if not sentinel.is_running:
            mini_dot.bgcolor = c["text_muted"]
            mini_status_label.color = c["text_muted"]
            mini_icon.color = c["text_muted"]
        else:
            mini_dot.bgcolor = c["idle_icon"]
            mini_status_label.color = c["text_secondary"]
            mini_icon.color = c["idle_icon"]

        mini_sentinel_btn.bgcolor = c["top_btn_bg"]
        mini_sentinel_btn.border = ft.Border.all(1, c["top_btn_border"])
        mini_sentinel_icon.color = c["active_icon"] if sentinel.is_running else c["idle_icon"]

        # Expand stays the accent primary action in both themes (same as copy buttons).
        mini_expand_btn.bgcolor = "#0284C7"
        mini_expand_btn.border = None
        mini_expand_icon.color = "#FFFFFF"

        mini_close_btn.bgcolor = c["top_btn_bg"]
        mini_close_btn.border = ft.Border.all(1, c["top_btn_border"])
        mini_close_icon.color = c["text_muted"]

        widget_mode_icon.color = c["text_secondary"]
        widget_mode_btn.bgcolor = c["top_btn_bg"]
        widget_mode_btn.border = ft.Border.all(1, c["top_btn_border"])

        render_history_items()
        page.update()

    def toggle_theme(e):
        nonlocal current_theme
        current_theme = "light" if current_theme == "dark" else "dark"
        apply_theme(current_theme)

    theme_btn.on_click = toggle_theme

    # 8. Error / Warning Dispatcher to UI
    def show_error(error_msg: str) -> None:
        """Surfaces critical errors or permission requirements directly on the interface."""
        if error_msg:
            if "permission" in error_msg.lower() or "access" in error_msg.lower():
                alert_title.value = "Permission Required"
                alert_settings_btn.visible = True
            else:
                alert_title.value = "System Alert"
                alert_settings_btn.visible = False
            alert_text.value = error_msg
            alert_banner.visible = True
        else:
            alert_banner.visible = False
        page.update()

    # 9. Connect Background Workers & Sentinel
    def on_status_change(msg: str) -> None:
        c = THEMES[current_theme]
        status_text.value = msg
        msg_lower = msg.lower()

        if "listening to you" in msg_lower or "speak now" in msg_lower or "listening now" in msg_lower:
            status_dot.bgcolor = "#EC4899"  # Hot pink active recording
            btn_icon.icon = ft.Icons.MIC_ROUNDED
            btn_icon.color = "#EC4899"
            toggle_container.border = ft.Border.all(3.0, "#EC4899")
            status_text.weight = ft.FontWeight.W_700
            status_text.color = "#EC4899"

            mini_dot.bgcolor = "#EC4899"
            mini_icon.icon = ft.Icons.MIC_ROUNDED
            mini_icon.color = "#EC4899"
            mini_status_label.value = "Listening to you..."
            mini_status_label.color = "#EC4899"
        elif "incoming" in msg_lower or "speak" in msg_lower or "reading" in msg_lower or "proposing" in msg_lower:
            status_dot.bgcolor = "#38BDF8"  # Cyan vocal output
            btn_icon.icon = ft.Icons.RECORD_VOICE_OVER_ROUNDED
            btn_icon.color = "#38BDF8"
            toggle_container.border = ft.Border.all(2.5, "#38BDF8")
            status_text.weight = ft.FontWeight.W_500
            status_text.color = c["text_primary"]

            mini_dot.bgcolor = "#38BDF8"
            mini_icon.icon = ft.Icons.RECORD_VOICE_OVER_ROUNDED
            mini_icon.color = "#38BDF8"
            mini_status_label.value = "Speaking..."
            mini_status_label.color = "#38BDF8"
        elif "drafting" in msg_lower or "analyz" in msg_lower or "finaliz" in msg_lower or "process" in msg_lower or "understood" in msg_lower:
            status_dot.bgcolor = "#F59E0B"  # Amber reasoning
            btn_icon.icon = ft.Icons.AUTO_AWESOME_ROUNDED
            btn_icon.color = "#F59E0B"
            toggle_container.border = ft.Border.all(2.0, "#F59E0B")
            status_text.weight = ft.FontWeight.W_500
            status_text.color = c["text_primary"]

            mini_dot.bgcolor = "#F59E0B"
            mini_icon.icon = ft.Icons.AUTO_AWESOME_ROUNDED
            mini_icon.color = "#F59E0B"
            mini_status_label.value = "Drafting with Muse..."
            mini_status_label.color = "#F59E0B"
        elif "quick repl" in msg_lower or "choose an option" in msg_lower:
            status_dot.bgcolor = "#10B981"
            btn_icon.icon = ft.Icons.TOUCH_APP_ROUNDED
            btn_icon.color = "#10B981"
            toggle_container.border = ft.Border.all(2.0, "#10B981")
            status_text.weight = ft.FontWeight.W_500
            status_text.color = c["text_primary"]

            mini_dot.bgcolor = "#10B981"
            mini_icon.icon = ft.Icons.TOUCH_APP_ROUNDED
            mini_icon.color = "#10B981"
            mini_status_label.value = "Quick replies ready!"
            mini_status_label.color = "#10B981"
        elif sentinel.is_running:
            status_dot.bgcolor = c["idle_icon"]
            btn_icon.icon = ft.Icons.STOP_ROUNDED
            btn_icon.color = c["active_icon"]
            toggle_container.border = ft.Border.all(1.5, c["active_border"])
            status_text.weight = ft.FontWeight.W_400
            status_text.color = c["text_muted"]

            mini_dot.bgcolor = c["idle_icon"]
            mini_icon.icon = ft.Icons.HEARING_ROUNDED
            mini_icon.color = c["idle_icon"]
            mini_status_label.value = "Listening"
            mini_status_label.color = c["text_secondary"]
        else:
            status_dot.bgcolor = c["text_muted"]
            btn_icon.icon = ft.Icons.PLAY_ARROW_ROUNDED
            btn_icon.color = c["idle_icon"]
            toggle_container.border = ft.Border.all(1.5, c["idle_border"])
            status_text.weight = ft.FontWeight.W_400
            status_text.color = c["text_muted"]

            mini_dot.bgcolor = c["text_muted"]
            mini_icon.icon = ft.Icons.RADIO_BUTTON_UNCHECKED_ROUNDED
            mini_icon.color = c["text_muted"]
            mini_status_label.value = "Idle"
            mini_status_label.color = c["text_muted"]
        page.update()

    def on_task_completed(task: Optional[TaskRecord] = None) -> None:
        nonlocal latest_response_text
        c = THEMES[current_theme]
        status_dot.bgcolor = "#10B981"
        status_text.value = "Response ready and copied (Cmd+V)"
        status_text.weight = ft.FontWeight.W_600
        status_text.color = "#10B981"
        toggle_container.border = ft.Border.all(2.0, "#10B981")
        if sentinel.is_running:
            btn_icon.icon = ft.Icons.STOP_ROUNDED
            btn_icon.color = c["active_icon"]

        mini_dot.bgcolor = "#10B981"
        mini_icon.icon = ft.Icons.CHECK_CIRCLE_ROUNDED
        mini_icon.color = "#10B981"
        mini_status_label.value = "Ready (Cmd+V)"
        mini_status_label.color = "#10B981"

        # Surface response directly in the central interface
        target_task = task
        if not target_task:
            recent = get_recent_tasks(limit=1)
            if recent:
                target_task = recent[0]

        if target_task and target_task.final_response:
            latest_response_text = target_task.final_response
            mini_copy_btn.visible = True
            response_sender_text.value = target_task.action_title
            response_body_text.value = target_task.final_response
            response_card.visible = True

        render_history_items()
        page.update()

    def render_quick_options(options: List[str]) -> None:
        c = THEMES[current_theme]
        quick_options_col.controls.clear()
        for idx, opt_text in enumerate(options, start=1):
            def make_handler(reply_str: str):
                return lambda e: select_quick_reply(reply_str)

            badge = ft.Container(
                content=ft.Text(f"{idx}", size=11, weight=ft.FontWeight.BOLD, color=c["badge_slack_text"]),
                width=22,
                height=22,
                border_radius=11,
                bgcolor=c["badge_slack_bg"],
                alignment=ft.Alignment(0, 0),
            )
            text_control = ft.Text(
                opt_text,
                size=12,
                color=c["text_primary"],
                expand=True,
                selectable=False,
            )
            copy_icon = ft.Icon(icon=ft.Icons.CONTENT_COPY_ROUNDED, size=14, color=c["text_muted"])

            option_row = ft.Row(
                [badge, text_control, copy_icon],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            option_container = ft.Container(
                content=option_row,
                bgcolor=c["panel_bg"],
                border=ft.Border.all(1, c["panel_border"]),
                border_radius=8,
                padding=10,
                ink=True,
                on_click=make_handler(opt_text),
                tooltip=f"Click to copy Option {idx} to clipboard",
            )
            quick_options_col.controls.append(option_container)

    def render_mini_options(options: List[str]) -> None:
        """Renders compact 1-click reply buttons below the mini widget row."""
        c = THEMES[current_theme]
        mini_options_col.controls.clear()
        for idx, opt_text in enumerate(options, start=1):
            def make_handler(reply_str: str):
                return lambda e: select_quick_reply(reply_str)

            badge = ft.Container(
                content=ft.Text(f"{idx}", size=10, weight=ft.FontWeight.BOLD, color=c["badge_slack_text"]),
                width=20,
                height=20,
                border_radius=10,
                bgcolor=c["badge_slack_bg"],
                alignment=ft.Alignment(0, 0),
            )
            text_control = ft.Text(
                opt_text,
                size=11,
                color=c["text_primary"],
                expand=True,
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS,
            )
            option_container = ft.Container(
                content=ft.Row(
                    [badge, text_control],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=c["card_bg"],
                border=ft.Border.all(1, c["card_border"]),
                border_radius=8,
                padding=8,
                ink=True,
                on_click=make_handler(opt_text),
                tooltip=opt_text,
            )
            mini_options_col.controls.append(option_container)

    def grow_mini_for_options(count: int) -> None:
        """Grows the widget window to fit quick-reply buttons (mini mode only)."""
        nonlocal pending_probe
        if not is_mini_mode or count <= 0:
            return
        expanded = MINI_COMPACT_HEIGHT + count * MINI_OPTION_ROW_H
        page.window.height = expanded
        page.window.min_height = expanded
        sync_window()
        pending_probe = (330, expanded, time.monotonic() + 2.0)
        page.update()

    def collapse_mini_options() -> None:
        """Clears widget buttons and restores the compact locked widget size."""
        nonlocal pending_probe
        was_expanded = len(mini_options_col.controls) > 0
        mini_options_col.controls.clear()
        if is_mini_mode and was_expanded:
            # Staged like enter: relax, shrink, then re-lock to exact size.
            page.window.min_height = 68
            sync_window()
            page.window.height = MINI_COMPACT_HEIGHT
            sync_window()
            page.window.min_height = MINI_COMPACT_HEIGHT
            sync_window()
            pending_probe = (330, MINI_COMPACT_HEIGHT, time.monotonic() + 2.0)
            page.update()

    def select_quick_reply(chosen_reply: str) -> None:
        nonlocal latest_response_text
        if not chosen_reply:
            return

        latest_response_text = chosen_reply
        ClipboardSensor.ignore_content(chosen_reply)
        try:
            pyperclip.copy(chosen_reply)
            page.set_clipboard(chosen_reply)
        except Exception:
            pass

        sender = current_quick_payload.get("sender", "Slack User")
        context_details = current_quick_payload.get("context_details", "")
        trigger_source = current_quick_payload.get("trigger_source", "SLACK_INTENT")

        task_record: Optional[TaskRecord] = None
        try:
            task_record = insert_task(
                action_title=f"{sender}",
                trigger_source=trigger_source,
                status="COMPLETED",
                incoming_message=context_details,
                ai_suggestion="Quick Reply Option",
                user_response="Selected 1-click option",
                final_response=chosen_reply,
            )
        except Exception as exc:
            logger.error("Failed to insert quick reply task record: %s", exc)

        SoundService.play_done()
        NotificationService.notify(
            title="V.E.R.S.O.",
            message=f"Quick reply for {sender} copied to clipboard (Cmd+V)!",
            subtitle="Response Ready",
            sound=True,
        )

        quick_replies_card.visible = False
        collapse_mini_options()
        on_task_completed(task_record)
        status_text.value = f"Quick reply copied to clipboard (Cmd+V) · {sender}"
        page.update()

    def on_need_another_response(e=None) -> None:
        context_details = current_quick_payload.get("context_details", "")
        if not context_details or worker_manager is None:
            return

        need_another_label.value = "Generating alternatives..."
        page.update()

        def fetch_new_options():
            try:
                fresh_data = worker_manager.muse_client.generate_quick_replies(
                    f"{context_details} (Please provide alternative, distinct responses)"
                )
                new_options = fresh_data.get("options", [])
                if new_options:
                    current_quick_payload["options"] = new_options
                    render_quick_options(new_options)
                    render_mini_options(new_options)
                    grow_mini_for_options(len(new_options))
            except Exception as exc:
                logger.warning("Failed to generate alternative replies: %s", exc)
            finally:
                need_another_label.value = "Need another response?"
                page.update()

        threading.Thread(target=fetch_new_options, daemon=True).start()

    need_another_btn.on_click = on_need_another_response

    def submit_custom_reply(e=None) -> None:
        user_input = (quick_custom_input.value or "").strip()
        if not user_input or worker_manager is None:
            return

        sender = current_quick_payload.get("sender", "Slack User")
        context_details = current_quick_payload.get("context_details", "")
        trigger_source = current_quick_payload.get("trigger_source", "SLACK_INTENT")

        quick_custom_input.value = ""
        need_another_label.value = "Refining response with Muse Spark..."
        page.update()

        def process_custom():
            nonlocal latest_response_text
            try:
                final_reply = worker_manager.muse_client.finalize_response(
                    incoming_message=context_details,
                    suggested_reply=f"Hi {sender}, thank you for reaching out.",
                    user_speech=user_input,
                )
            except Exception:
                final_reply = user_input

            latest_response_text = final_reply
            ClipboardSensor.ignore_content(final_reply)
            try:
                pyperclip.copy(final_reply)
                page.set_clipboard(final_reply)
            except Exception:
                pass

            task_record: Optional[TaskRecord] = None
            try:
                task_record = insert_task(
                    action_title=f"{sender}",
                    trigger_source=trigger_source,
                    status="COMPLETED",
                    incoming_message=context_details,
                    ai_suggestion="Custom instruction",
                    user_response=user_input,
                    final_response=final_reply,
                )
            except Exception as exc:
                logger.error("Failed to insert custom reply task: %s", exc)

            SoundService.play_done()
            NotificationService.notify(
                title="V.E.R.S.O.",
                message=f"Custom response for {sender} copied to clipboard (Cmd+V)!",
                subtitle="Response Ready",
                sound=True,
            )

            quick_replies_card.visible = False
            collapse_mini_options()
            need_another_label.value = "Need another response?"
            on_task_completed(task_record)
            status_text.value = f"Response copied to clipboard (Cmd+V) · {sender}"
            page.update()

        threading.Thread(target=process_custom, daemon=True).start()

    quick_custom_send_btn.on_click = submit_custom_reply
    quick_custom_input.on_submit = submit_custom_reply

    def on_quick_replies_received(payload: Dict[str, Any]) -> None:
        nonlocal current_quick_payload
        current_quick_payload = payload
        sender = payload.get("sender", "Slack User")
        summary = payload.get("summary", "")
        options = payload.get("options", [])

        quick_sender_text.value = f"{sender}"
        quick_summary_text.value = summary or payload.get("message", "")
        render_quick_options(options)
        render_mini_options(options)
        grow_mini_for_options(len(options))

        response_card.visible = False
        quick_replies_card.visible = True
        status_text.value = f"Quick replies ready for {sender} · Choose an option"
        mini_status_label.value = "Quick replies ready!"
        mini_status_label.color = "#10B981"
        page.update()

    worker_manager = WorkerManager(
        deliverables_dir="deliverables",
        on_status_change=on_status_change,
        on_task_completed=on_task_completed,
        on_quick_replies=on_quick_replies_received,
        on_error=show_error,
        voice_enabled=is_voice_enabled,
    )

    def on_context_detected(context_type: str, payload: str) -> None:
        worker_manager.execute_intention(
            trigger_source=f"{context_type}",
            context_details=payload,
        )

    def on_sentinel_state_change(is_running: bool) -> None:
        c = THEMES[current_theme]
        if not is_running:
            btn_icon.icon = ft.Icons.PLAY_ARROW_ROUNDED
            btn_icon.size = 38
            btn_icon.color = c["idle_icon"]
            toggle_container.gradient = c["idle_gradient"]
            toggle_container.border = ft.Border.all(1.5, c["idle_border"])
            toggle_container.shadow = c["idle_shadow"]

            compact_toggle_icon.icon = ft.Icons.PLAY_ARROW_ROUNDED
            compact_toggle_icon.color = c["idle_icon"]
            compact_toggle_btn.tooltip = "Start listening"

            mini_sentinel_icon.icon = ft.Icons.PLAY_ARROW_ROUNDED
            mini_sentinel_icon.color = c["idle_icon"]
            mini_sentinel_btn.tooltip = "Start listening"

            if not alert_banner.visible:
                status_dot.bgcolor = c["text_muted"]
                status_text.value = "Idle · Tap button to start listening"
                mini_dot.bgcolor = c["text_muted"]
                mini_icon.icon = ft.Icons.RADIO_BUTTON_UNCHECKED_ROUNDED
                mini_icon.color = c["text_muted"]
                mini_status_label.value = "Idle"
                mini_status_label.color = c["text_muted"]
        else:
            btn_icon.icon = ft.Icons.STOP_ROUNDED
            btn_icon.size = 32
            btn_icon.color = c["active_icon"]
            toggle_container.gradient = c["active_gradient"]
            toggle_container.border = ft.Border.all(1.5, c["active_border"])
            toggle_container.shadow = c["active_shadow"]

            compact_toggle_icon.icon = ft.Icons.STOP_ROUNDED
            compact_toggle_icon.color = c["active_icon"]
            compact_toggle_btn.tooltip = "Pause listening"

            mini_sentinel_icon.icon = ft.Icons.STOP_ROUNDED
            mini_sentinel_icon.color = c["active_icon"]
            mini_sentinel_btn.tooltip = "Pause listening"

            status_dot.bgcolor = c["idle_icon"]
            status_text.value = "Listening"
            mini_dot.bgcolor = c["idle_icon"]
            mini_icon.icon = ft.Icons.HEARING_ROUNDED
            mini_icon.color = c["idle_icon"]
            mini_status_label.value = "Listening"
            mini_status_label.color = c["text_secondary"]
        page.update()

    sentinel = Sentinel(
        poll_interval=1.5,
        cooldown_seconds=15.0,
        on_context_detected=on_context_detected,
        on_error=show_error,
        on_state_change=on_sentinel_state_change,
        is_busy_fn=lambda: worker_manager.is_busy,
    )

    def toggle_listening(e):
        c = THEMES[current_theme]
        if sentinel.is_running:
            sentinel.stop()
            NotificationService.notify(
                title="V.E.R.S.O.",
                message="Listening paused.",
            )
        else:
            started, error_reason = sentinel.start()
            if not started:
                # Blocked by permission or sensor error: do NOT switch to STOP and do NOT notify
                show_error(error_reason)
                status_dot.bgcolor = "#F59E0B"
                status_text.value = "Blocked · Permission required"
                btn_icon.icon = ft.Icons.PLAY_ARROW_ROUNDED
                btn_icon.size = 38
                btn_icon.color = c["idle_icon"]
                toggle_container.gradient = c["idle_gradient"]
                toggle_container.border = ft.Border.all(1.5, c["idle_border"])
                toggle_container.shadow = c["idle_shadow"]
                compact_toggle_icon.icon = ft.Icons.PLAY_ARROW_ROUNDED
                compact_toggle_icon.color = c["idle_icon"]
                page.update()
                return

            # Started successfully: clear any previous error and notify
            show_error("")
            NotificationService.notify(
                title="V.E.R.S.O.",
                message="Listening active.",
            )
        page.update()

    toggle_container.on_click = toggle_listening
    compact_toggle_btn.on_click = toggle_listening
    mini_sentinel_btn.on_click = toggle_listening

    # Layout Assembly: Stack with Docked Base Row + Responsive Overlay Layer
    full_stack = ft.Stack(
        controls=[
            # Base Layer: Row with Docked Left Pane + Main Companion View
            ft.Row(
                controls=[
                    docked_pane,
                    main_view,
                ],
                expand=True,
                spacing=0,
            ),
            # Overlay Layer: Backdrop and Sliding Drawer (active only in narrow mode)
            backdrop,
            overlay_drawer,
        ],
        expand=True,
    )

    root_container = ft.Container(
        content=full_stack,
        expand=True,
    )
    page.add(root_container)

    # Initialize task history on startup
    render_history_items()

    # Pre-check sensor permissions on startup and surface banner immediately if access is missing
    is_ready, perm_error = sentinel.check_readiness()
    if not is_ready:
        show_error(perm_error)
        status_dot.bgcolor = "#F59E0B"
        status_text.value = "Blocked · Permission required"
        page.update()
