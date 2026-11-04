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
from datetime import datetime
from typing import Any, Dict, List

import flet as ft

from verso.database import TaskRecord, get_recent_tasks
from verso.sentinel import Sentinel
from verso.services.notification_service import NotificationService
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


def create_app(page: ft.Page) -> None:
    current_theme = "dark"
    colors = THEMES[current_theme]
    is_history_open: bool = False

    # Window Configuration (initial size 460x700, user-resizable)
    page.title = "V.E.R.S.O."
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = colors["page_bg"]
    page.window.width = 460
    page.window.height = 700
    page.window.resizable = True
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
                history_btn,
                ft.Container(expand=True),
                theme_btn,
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
    )

    status_row = ft.Row(
        [status_dot, status_text],
        alignment=ft.MainAxisAlignment.CENTER,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=8,
    )

    main_view = ft.Container(
        expand=True,
        alignment=ft.Alignment(0, 0),
        content=ft.Column(
            [
                top_bar,
                alert_banner,
                ft.Container(expand=True),
                title,
                ft.Container(height=32),
                toggle_container,
                ft.Container(height=24),
                status_row,
                ft.Container(expand=True),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        ),
    )

    # 4. History List Views (Independent for Docked Panel & Overlay Drawer)
    list_docked = ft.ListView(
        spacing=10,
        padding=ft.Padding(left=14, top=6, right=14, bottom=16),
        auto_scroll=False,
        expand=True,
    )

    list_drawer = ft.ListView(
        spacing=10,
        padding=ft.Padding(left=14, top=6, right=14, bottom=16),
        auto_scroll=False,
        expand=True,
    )

    def build_task_card(task: TaskRecord, c: Dict[str, Any]) -> ft.Container:
        """Builds a formatted task history card."""
        time_str = (
            task.timestamp.strftime("%H:%M:%S")
            if isinstance(task.timestamp, datetime)
            else str(task.timestamp)
        )
        return ft.Container(
            bgcolor=c["card_bg"],
            border=ft.Border.all(1, c["card_border"]),
            border_radius=8,
            padding=12,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                task.action_title,
                                size=13,
                                weight=ft.FontWeight.W_600,
                                color=c["text_primary"],
                                expand=True,
                            ),
                            ft.Text(
                                time_str,
                                size=11,
                                color=c["text_muted"],
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Text(
                                    task.trigger_source,
                                    size=10,
                                    weight=ft.FontWeight.W_600,
                                    color=c["badge_slack_text"],
                                ),
                                bgcolor=c["badge_slack_bg"],
                                border_radius=4,
                                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                            ),
                            ft.Container(
                                content=ft.Text(
                                    task.status,
                                    size=10,
                                    weight=ft.FontWeight.W_600,
                                    color=c["badge_done_text"],
                                ),
                                bgcolor=c["badge_done_bg"],
                                border_radius=4,
                                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DESCRIPTION_OUTLINED,
                                icon_size=16,
                                icon_color=c["text_secondary"],
                                tooltip="Open SLACK_DRAFT.md",
                                on_click=lambda e: open_deliverable("deliverables/SLACK_DRAFT.md"),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=6,
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
                    "No tasks recorded yet.\nV.E.R.S.O. is listening for Slack intentions.",
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
        current_w = page.width or (page.window.width if hasattr(page.window, "width") else 460) or 460
        return current_w >= BREAKPOINT_WIDTH

    def update_history_layout() -> None:
        """Adapts the UI layout between docked left side panel and overlay drawer."""
        c = THEMES[current_theme]
        wide = is_wide_enough()

        if not is_history_open:
            docked_pane.visible = False
            docked_pane.width = 0
            overlay_drawer.left = -340
            backdrop.visible = False
            history_btn.bgcolor = c["top_btn_bg"]
            history_btn.border = ft.Border.all(1, c["top_btn_border"])
        else:
            history_btn.bgcolor = c["card_bg"]
            history_btn.border = ft.Border.all(1, c["idle_border"])

            if wide:
                docked_pane.visible = True
                docked_pane.width = 280
                overlay_drawer.left = -340
                backdrop.visible = False
            else:
                docked_pane.visible = False
                docked_pane.width = 0
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

    def on_window_resize(e):
        """Dynamically adapts between docked panel and overlay drawer as the user resizes."""
        if is_history_open:
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

    docked_pane = ft.Container(
        width=0,
        visible=False,
        bgcolor=colors["panel_bg"],
        border=ft.Border(right=ft.BorderSide(1, colors["panel_border"])),
        content=ft.Column(
            [
                docked_header,
                list_docked,
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

    overlay_drawer = ft.Container(
        width=300,
        top=0,
        bottom=0,
        left=-340,
        animate_position=ft.Animation(300, ft.AnimationCurve.EASE_OUT_CUBIC),
        bgcolor=colors["panel_bg"],
        border=ft.Border(right=ft.BorderSide(1, colors["panel_border"])),
        shadow=ft.BoxShadow(
            spread_radius=2,
            blur_radius=24,
            color="#000000",
            offset=ft.Offset(6, 0),
        ),
        content=ft.Column(
            [
                drawer_header,
                list_drawer,
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
        docked_pane.border = ft.Border(right=ft.BorderSide(1, c["panel_border"]))
        overlay_drawer.bgcolor = c["panel_bg"]
        overlay_drawer.border = ft.Border(right=ft.BorderSide(1, c["panel_border"]))
        backdrop.bgcolor = c["backdrop_color"]

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
        if "processing" in msg.lower() or "at work" in msg.lower():
            status_dot.bgcolor = "#F59E0B"
        elif sentinel.is_running:
            status_dot.bgcolor = c["idle_icon"]
        else:
            status_dot.bgcolor = c["text_muted"]
        page.update()

    def on_task_completed() -> None:
        status_dot.bgcolor = "#10B981"
        status_text.value = "Draft ready · Listening attentively"
        render_history_items()
        page.update()

    worker_manager = WorkerManager(
        deliverables_dir="deliverables",
        on_status_change=on_status_change,
        on_task_completed=on_task_completed,
        on_error=show_error,
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
            if not alert_banner.visible:
                status_dot.bgcolor = c["text_muted"]
                status_text.value = "Idle · Tap button to start listening"
        else:
            btn_icon.icon = ft.Icons.STOP_ROUNDED
            btn_icon.size = 32
            btn_icon.color = c["active_icon"]
            toggle_container.gradient = c["active_gradient"]
            toggle_container.border = ft.Border.all(1.5, c["active_border"])
            toggle_container.shadow = c["active_shadow"]
            status_dot.bgcolor = c["idle_icon"]
            status_text.value = "Listening attentively on the Verso"
        page.update()

    sentinel = Sentinel(
        poll_interval=1.5,
        cooldown_seconds=15.0,
        on_context_detected=on_context_detected,
        on_error=show_error,
        on_state_change=on_sentinel_state_change,
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
                page.update()
                return

            # Started successfully: clear any previous error and notify
            show_error("")
            NotificationService.notify(
                title="V.E.R.S.O.",
                message="Listening active for Slack intentions.",
            )
        page.update()

    toggle_container.on_click = toggle_listening

    # Layout Assembly: Stack with Docked Base Row + Responsive Overlay Layer
    page.add(
        ft.Stack(
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
    )

    # Initialize task history on startup
    render_history_items()

    # Pre-check sensor permissions on startup and surface banner immediately if access is missing
    is_ready, perm_error = sentinel.check_readiness()
    if not is_ready:
        show_error(perm_error)
        status_dot.bgcolor = "#F59E0B"
        status_text.value = "Blocked · Permission required"
        page.update()
