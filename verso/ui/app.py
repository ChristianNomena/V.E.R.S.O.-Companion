"""
V.E.R.S.O. - Companion User Interface
"""

import flet as ft
from verso.sentinel import Sentinel
from verso.services.notification_service import NotificationService
from verso.workers import WorkerManager

# Color Palette (Midnight Obsidian & Refined Accents)
BG_COLOR = "#0B0F17"
TEXT_COLOR = "#F8FAFC"
IDLE_BORDER = "#334155"
ACTIVE_BORDER = "#FB7185"
IDLE_ICON = "#38BDF8"
ACTIVE_ICON = "#FDA4AF"

IDLE_GRADIENT = ft.LinearGradient(
    begin=ft.Alignment(-1, -1),
    end=ft.Alignment(1, 1),
    colors=["#1E293B", "#0F172A"],
)

ACTIVE_GRADIENT = ft.LinearGradient(
    begin=ft.Alignment(-1, -1),
    end=ft.Alignment(1, 1),
    colors=["#3F0A1D", "#1E0610"],
)

IDLE_SHADOW = ft.BoxShadow(
    spread_radius=1,
    blur_radius=20,
    color="#030712",
    offset=ft.Offset(0, 6),
)

ACTIVE_SHADOW = ft.BoxShadow(
    spread_radius=2,
    blur_radius=24,
    color="#881337",
    offset=ft.Offset(0, 4),
)


def create_app(page: ft.Page) -> None:
    # Page setup
    page.title = "V.E.R.S.O."
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG_COLOR
    page.window.width = 460
    page.window.height = 700
    page.window.resizable = True
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

    worker_manager = WorkerManager(deliverables_dir="deliverables")

    def on_context_detected(context_type: str, payload: str) -> None:
        worker_manager.execute_intention(
            trigger_source=f"{context_type}",
            context_details=payload,
        )

    sentinel = Sentinel(
        poll_interval=2.0,
        cooldown_seconds=20.0,
        on_context_detected=on_context_detected,
    )

    btn_icon = ft.Icon(
        icon=ft.Icons.PLAY_ARROW_ROUNDED,
        size=38,
        color=IDLE_ICON,
    )

    def toggle_listening(e):
        if sentinel.is_running:
            sentinel.stop()
            btn_icon.icon = ft.Icons.PLAY_ARROW_ROUNDED
            btn_icon.size = 38
            btn_icon.color = IDLE_ICON
            toggle_container.gradient = IDLE_GRADIENT
            toggle_container.border = ft.Border.all(1.5, IDLE_BORDER)
            toggle_container.shadow = IDLE_SHADOW
            NotificationService.notify(
                title="V.E.R.S.O.",
                message="Listening paused.",
            )
        else:
            sentinel.start()
            btn_icon.icon = ft.Icons.STOP_ROUNDED
            btn_icon.size = 32
            btn_icon.color = ACTIVE_ICON
            toggle_container.gradient = ACTIVE_GRADIENT
            toggle_container.border = ft.Border.all(1.5, ACTIVE_BORDER)
            toggle_container.shadow = ACTIVE_SHADOW
            NotificationService.notify(
                title="V.E.R.S.O.",
                message="Listening active.",
            )
        page.update()

    # Sleek tactile center button
    toggle_container = ft.Container(
        width=84,
        height=84,
        shape=ft.BoxShape.CIRCLE,
        gradient=IDLE_GRADIENT,
        border=ft.Border.all(1.5, IDLE_BORDER),
        shadow=IDLE_SHADOW,
        alignment=ft.Alignment(0, 0),
        content=btn_icon,
        ink=True,
        animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
        on_click=toggle_listening,
    )

    # Refined letter-spaced typography
    title = ft.Text(
        "V.E.R.S.O.",
        size=22,
        weight=ft.FontWeight.W_700,
        style=ft.TextStyle(
            letter_spacing=4.0,
            color=TEXT_COLOR,
        ),
    )

    page.add(
        ft.Column(
            [
                title,
                toggle_container,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=32,
        )
    )
