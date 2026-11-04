"""Headless regression tests for widget/window behavior (no GUI).

Runs the real ``create_app`` against a real Flet ``Session`` with a stubbed
transport, drives the mode buttons found by tooltip, and asserts the exact
window-geometry patches emitted on the protocol. Portable: plain imports,
temporary working directory for the sqlite db and deliverables.
"""

import gc
import os
import tempfile
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flet.messaging.session import Session
from verso.database import get_recent_tasks, init_db
from verso.services.notification_service import NotificationService
from verso.services.sound_service import SoundService
from verso.ui.app import create_app
from verso.workers.workers import WorkerManager

ENTER_TOOLTIP = "Switch to Widget Mode (always on top)"
EXIT_TOOLTIP = "Back to full window"

WIDGET_SIZE = (330, 76)
WINDOW_SIZE = (460, 700)


def _walk_clickables(root):
    """Collects {tooltip: [handlers]} by walking content/controls recursively."""
    found = {}
    seen = set()

    def walk(node):
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        tooltip = getattr(node, "tooltip", None)
        handler = getattr(node, "on_click", None)
        if isinstance(tooltip, str) and callable(handler):
            found.setdefault(tooltip, []).append(handler)
        content = getattr(node, "content", None)
        if content is not None and not isinstance(content, (str, bytes)):
            walk(content)
        controls = getattr(node, "controls", None)
        if isinstance(controls, (list, tuple)):
            for child in controls:
                if not isinstance(child, (str, bytes)):
                    walk(child)

    walk(root)
    return found


def _window_patch_frames(messages, window_id):
    """Extracts per-message [{(prop, value)}] from window-targeted patches."""
    frames = []
    for call in messages:
        body = getattr(call.args[0], "body", None)
        if type(body).__name__ != "PatchControlBody":
            continue
        if getattr(body, "id", None) != window_id:
            continue
        ops = set()
        patch = getattr(body, "patch", []) or []
        for op in patch[1:]:
            try:
                kind, prop = op[0], op[2]
                value = op[3] if len(op) > 3 else None
            except (IndexError, TypeError):
                continue
            if getattr(kind, "name", kind) == "Replace":
                ops.add((prop, value))
        frames.append(ops)
    return frames


def _window_size_ops(messages, window_id):
    """Extracts {(prop, value)} from window-targeted PATCH_CONTROL messages."""
    merged = set()
    for frame in _window_patch_frames(messages, window_id):
        merged |= frame
    return merged


def _has_prop(frame, name):
    return any(prop == name for prop, _ in frame)


def _has_min_prop(frame):
    return any("min" in str(prop).lower() for prop, _ in frame)


class WindowModePatchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        old_cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, old_cwd)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            init_db()
            self.conn = MagicMock()
            self.session = Session(self.conn)
            self.page = self.session.page
            create_app(self.page)
            # Production mount parity: initial serialization indexes and
            # parents the tree (including page.window).
            self.session.get_page_patch()
        self.conn.send_message.reset_mock()

    def _click(self, tooltip):
        handlers = _walk_clickables(self.page).get(tooltip, [])
        self.assertTrue(handlers, f"no clickable found for tooltip {tooltip!r}")
        handlers[0]()
        return _window_size_ops(
            self.conn.send_message.call_args_list, self.page.window._i
        )

    def _frames(self):
        return _window_patch_frames(
            self.conn.send_message.call_args_list, self.page.window._i
        )

    def _fire_resize(self, width, height):
        self.page.on_resize(SimpleNamespace(width=width, height=height))

    def test_enter_widget_sends_shrink_patch(self):
        ops = self._click(ENTER_TOOLTIP)
        self.assertIn(("width", WIDGET_SIZE[0]), ops)
        self.assertIn(("height", WIDGET_SIZE[1]), ops)
        self.assertEqual(self.page.window.width, WIDGET_SIZE[0])
        self.assertEqual(self.page.window.height, WIDGET_SIZE[1])
        self.assertTrue(self.page.window.always_on_top)
        self.assertTrue(self.page.window.resizable)

    def test_exit_widget_restores_window_size_patch(self):
        self._click(ENTER_TOOLTIP)
        self.conn.send_message.reset_mock()
        ops = self._click(EXIT_TOOLTIP)
        self.assertIn(("width", WINDOW_SIZE[0]), ops)
        self.assertIn(("height", WINDOW_SIZE[1]), ops)
        self.assertEqual(self.page.window.width, WINDOW_SIZE[0])
        self.assertEqual(self.page.window.height, WINDOW_SIZE[1])
        self.assertFalse(self.page.window.always_on_top)
        self.assertTrue(self.page.window.resizable)

    def test_second_cycle_still_emits_patches(self):
        self._click(ENTER_TOOLTIP)
        self._click(EXIT_TOOLTIP)
        self.conn.send_message.reset_mock()
        ops = self._click(ENTER_TOOLTIP)
        self.assertIn(("width", WIDGET_SIZE[0]), ops)
        self.assertIn(("height", WIDGET_SIZE[1]), ops)

    def test_enter_stages_constraints_before_size(self):
        self._click(ENTER_TOOLTIP)
        frames = self._frames()
        self.assertGreaterEqual(len(frames), 2)
        # First patch relaxes minimums (small size never clamped by old ones).
        self.assertTrue(_has_min_prop(frames[0]))
        self.assertFalse(_has_prop(frames[0], "width"))
        # Second patch applies the widget size.
        self.assertIn(("width", WIDGET_SIZE[0]), frames[1])
        self.assertIn(("height", WIDGET_SIZE[1]), frames[1])

    def test_exit_stages_size_before_minimums(self):
        self._click(ENTER_TOOLTIP)
        self.conn.send_message.reset_mock()
        self._click(EXIT_TOOLTIP)
        frames = self._frames()
        self.assertGreaterEqual(len(frames), 2)
        # First patch grows while unconstrained.
        self.assertIn(("width", WINDOW_SIZE[0]), frames[0])
        self.assertIn(("height", WINDOW_SIZE[1]), frames[0])
        self.assertFalse(_has_min_prop(frames[0]))
        # Second patch tightens minimums afterwards.
        self.assertTrue(_has_min_prop(frames[1]))

    def test_manual_resize_cycle_restores_tracked_size(self):
        # Calibrate chrome from our own widget resize (330x76 known).
        self._click(ENTER_TOOLTIP)
        self._fire_resize(330.0, 48.0)  # -> chrome delta (0, 28)
        self._click(EXIT_TOOLTIP)
        # Manual resize in window mode (events carry the real content size).
        self._fire_resize(900.0, 800.0)
        self._click(ENTER_TOOLTIP)
        self.conn.send_message.reset_mock()
        self._click(EXIT_TOOLTIP)
        ops = _window_size_ops(
            self.conn.send_message.call_args_list, self.page.window._i
        )
        self.assertIn(("width", 900.0), ops)
        self.assertIn(("height", 828.0), ops)

    def test_cycle_without_manual_resize_preserves_initial_size(self):
        # Enter widget mode and simulate the real Flutter on_resize event that fires
        self._click(ENTER_TOOLTIP)
        self._fire_resize(330.0, 48.0)
        self.conn.send_message.reset_mock()
        # Exit widget mode: must restore WINDOW_SIZE (460, 700), NOT collapse to 380x500!
        ops = self._click(EXIT_TOOLTIP)
        self.assertIn(("width", WINDOW_SIZE[0]), ops)
        self.assertIn(("height", WINDOW_SIZE[1]), ops)
        self.assertEqual(self.page.window.width, WINDOW_SIZE[0])
        self.assertEqual(self.page.window.height, WINDOW_SIZE[1])

    def test_multi_cycle_preserves_dimensions_consistently(self):
        # Cycle 1: Enter mini, Flutter fires resize event
        self._click(ENTER_TOOLTIP)
        self._fire_resize(330.0, 48.0)
        self.assertEqual(self.page.window.width, WIDGET_SIZE[0])
        self.assertEqual(self.page.window.height, WIDGET_SIZE[1])
        # Exit mini, Flutter fires normal resize event
        self._click(EXIT_TOOLTIP)
        self._fire_resize(460.0, 672.0)
        self.assertEqual(self.page.window.width, WINDOW_SIZE[0])
        self.assertEqual(self.page.window.height, WINDOW_SIZE[1])
        # Cycle 2: Enter mini again
        self.conn.send_message.reset_mock()
        ops = self._click(ENTER_TOOLTIP)
        self.assertIn(("width", WIDGET_SIZE[0]), ops)
        self.assertIn(("height", WIDGET_SIZE[1]), ops)
        self.assertEqual(self.page.window.width, WIDGET_SIZE[0])
        self.assertEqual(self.page.window.height, WIDGET_SIZE[1])
        # Exit mini again
        self.conn.send_message.reset_mock()
        ops2 = self._click(EXIT_TOOLTIP)
        self.assertIn(("width", WINDOW_SIZE[0]), ops2)
        self.assertIn(("height", WINDOW_SIZE[1]), ops2)
        self.assertEqual(self.page.window.width, WINDOW_SIZE[0])
        self.assertEqual(self.page.window.height, WINDOW_SIZE[1])

    def test_widget_mode_blocks_user_resize_attempts(self):
        # Enter widget mode
        self._click(ENTER_TOOLTIP)
        # Calibrate chrome
        self._fire_resize(330.0, 48.0)
        self.conn.send_message.reset_mock()

        # Simulate user attempting to drag/resize widget window to 500x200
        self._fire_resize(500.0, 172.0)
        ops = _window_size_ops(
            self.conn.send_message.call_args_list, self.page.window._i
        )
        # Should block and snap back immediately to 330x76:
        self.assertIn(("width", WIDGET_SIZE[0]), ops)
        self.assertIn(("height", WIDGET_SIZE[1]), ops)


QUICK_OPTIONS = [
    "Reply one short",
    "Reply two a bit longer here",
    "Reply three is the longest option of all",
]

MINI_COMPACT_H = 76
MINI_ROW_H = 54
MINI_EXPANDED_3 = MINI_COMPACT_H + 3 * MINI_ROW_H


def _make_quick_payload(options):
    return {
        "sender": "Mini Tester",
        "message": "Are you available?",
        "context_details": "From Mini Tester: Are you available?",
        "trigger_source": "SLACK_INTENT",
        "summary": "Mini Tester asks about availability",
        "options": list(options),
    }


class MiniQuickRepliesTest(unittest.TestCase):
    """Quick-reply buttons below the widget: grow, 1-click answer, collapse."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        old_cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, old_cwd)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            init_db()
            self.conn = MagicMock()
            self.session = Session(self.conn)
            self.page = self.session.page
            create_app(self.page)
            self.session.get_page_patch()
        self.conn.send_message.reset_mock()

    def _worker_manager(self):
        # Deterministic lookup: the manager whose quick-replies callback closes
        # over THIS test's page (gc order is arbitrary across tests).
        for obj in gc.get_objects():
            if not isinstance(obj, WorkerManager):
                continue
            callback = getattr(obj, "on_quick_replies", None)
            cells = getattr(callback, "__closure__", None) or ()
            for cell in cells:
                try:
                    if cell.cell_contents is self.page:
                        return obj
                except ValueError:
                    continue
        self.fail("no WorkerManager found for this test's page")

    def _click_tooltip(self, tooltip):
        handlers = _walk_clickables(self.page).get(tooltip, [])
        self.assertTrue(handlers, f"no clickable found for tooltip {tooltip!r}")
        handlers[0]()

    def _mini_option_handlers(self):
        found = {}
        for tooltip, handlers in _walk_clickables(self.page).items():
            if tooltip in QUICK_OPTIONS:
                found[tooltip] = handlers[0]
        return found

    def _heights(self):
        return [
            value
            for frame in _window_patch_frames(
                self.conn.send_message.call_args_list, self.page.window._i
            )
            for prop, value in frame
            if prop == "height"
        ]

    def _min_heights(self):
        return [
            value
            for frame in _window_patch_frames(
                self.conn.send_message.call_args_list, self.page.window._i
            )
            for prop, value in frame
            if "min" in str(prop).lower() and "height" in str(prop).lower()
        ]

    def test_options_arrival_grows_widget(self):
        self._click_tooltip(ENTER_TOOLTIP)
        self._worker_manager().on_quick_replies(_make_quick_payload(QUICK_OPTIONS))
        self.assertIn(MINI_EXPANDED_3, self._heights())
        self.assertIn(MINI_EXPANDED_3, self._min_heights())
        self.assertEqual(set(self._mini_option_handlers()), set(QUICK_OPTIONS))

    def test_mini_option_click_copies_and_collapses(self):
        self._click_tooltip(ENTER_TOOLTIP)
        self._worker_manager().on_quick_replies(_make_quick_payload(QUICK_OPTIONS))
        handlers = self._mini_option_handlers()
        self.assertEqual(len(handlers), 3)
        self.conn.send_message.reset_mock()
        with (
            patch.object(NotificationService, "notify", return_value=True),
            patch.object(SoundService, "play_done", return_value=None),
            patch("pyperclip.copy", return_value=None),
        ):
            handlers[QUICK_OPTIONS[0]](None)
        self.assertIn(MINI_COMPACT_H, self._heights())
        self.assertEqual(self._mini_option_handlers(), {})
        recent = get_recent_tasks(limit=1)
        self.assertEqual(recent[0].final_response, QUICK_OPTIONS[0])

    def test_enter_widget_with_pending_options_expands(self):
        self._worker_manager().on_quick_replies(_make_quick_payload(QUICK_OPTIONS))
        self.conn.send_message.reset_mock()
        self._click_tooltip(ENTER_TOOLTIP)
        self.assertIn(MINI_EXPANDED_3, self._heights())
        self.assertEqual(set(self._mini_option_handlers()), set(QUICK_OPTIONS))

    def test_dismiss_collapses_mini_options(self):
        self._worker_manager().on_quick_replies(_make_quick_payload(QUICK_OPTIONS))
        # Grab the quick-card close button while the full view is mounted.
        root = self.page.controls[0]
        home_view = root.content.controls[0].controls[1].content.controls[2].content
        quick_card = home_view.controls[6]
        close_btn = quick_card.content.controls[0].controls[1]
        self._click_tooltip(ENTER_TOOLTIP)
        self.assertEqual(len(self._mini_option_handlers()), 3)
        self.conn.send_message.reset_mock()
        close_btn.on_click(None)
        self.assertIn(MINI_COMPACT_H, self._heights())
        self.assertEqual(self._mini_option_handlers(), {})


if __name__ == "__main__":
    unittest.main()
