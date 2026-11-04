"""
Tests for Voice Activated / Deactivated Mode and Window Behavior in V.E.R.S.O.
"""

import unittest
from unittest.mock import MagicMock
import flet as ft

from verso.database import get_recent_tasks, insert_task
from verso.ui.app import create_app
from verso.workers.workers import WorkerManager


class TestVocalAndQuickModes(unittest.TestCase):
    def setUp(self):
        self.page = MagicMock(spec=ft.Page)
        self.page.window = MagicMock()
        self.page.window.width = 460
        self.page.window.height = 700
        self.page.window.always_on_top = False
        self.controls_added = []
        self.page.add = lambda *c: self.controls_added.extend(c)
        create_app(self.page)
        self.root = self.controls_added[0]
        self.full_stack = self.root.content
        self.main_layout = self.full_stack.controls[0]
        self.main_view = self.main_layout.controls[1]
        self.main_col = self.main_view.content
        self.top_bar = self.main_col.controls[0]
        self.content_area = self.main_col.controls[2]
        self.home_view = self.content_area.content
        self.quick_replies_card = self.home_view.controls[6]
        self.response_card = self.home_view.controls[7]
        self.voice_btn = self.top_bar.content.controls[2].controls[1]

    def test_voice_toggle_visual_and_state(self):
        # Default is active
        self.assertIn("Active", self.voice_btn.tooltip)

        # Toggle to deactivated
        self.voice_btn.on_click(None)
        self.assertIn("Deactivated", self.voice_btn.tooltip)

        # Toggle back to active
        self.voice_btn.on_click(None)
        self.assertIn("Active", self.voice_btn.tooltip)

    def test_quick_replies_card_selection_and_db_persistence(self):
        # Deactivate voice mode
        self.voice_btn.on_click(None)

        # Mock WorkerManager with on_quick_replies
        import gc
        wms = [obj for obj in gc.get_objects() if isinstance(obj, WorkerManager)]
        wm = wms[-1]
        self.assertFalse(wm.voice_enabled)

        payload = {
            "sender": "Claire Redfield",
            "message": "Can you check the server logs?",
            "context_details": "Claire Redfield: Can you check the server logs?",
            "trigger_source": "SLACK_INTENT",
            "summary": "Claire requested server log inspection",
            "options": [
                "I am checking the server logs right now and will update you.",
                "Currently in a deployment, will check them in 15 minutes.",
                "Server logs show all services operating normally.",
            ],
        }

        wm.on_quick_replies(payload)

        # Quick replies card becomes visible
        self.assertTrue(self.quick_replies_card.visible)
        q_col = self.quick_replies_card.content
        quick_options_col = q_col.controls[3]
        self.assertEqual(len(quick_options_col.controls), 3)

        # Simulate clicking option 1
        option_1_btn = quick_options_col.controls[0]
        option_1_btn.on_click(None)

        # Card is hidden, response card is visible
        self.assertFalse(self.quick_replies_card.visible)
        self.assertTrue(self.response_card.visible)

        # Task persisted in database
        recent = get_recent_tasks(limit=1)
        self.assertEqual(recent[0].action_title, "Claire Redfield")
        self.assertIn("checking the server logs", recent[0].final_response)

    def test_window_close_interception_to_widget_mode(self):
        mock_close_event = MagicMock()
        mock_close_event.data = "close"

        # First close attempt from normal mode: switches to widget mode (always on top)
        self.page.window.on_event(mock_close_event)
        self.assertTrue(self.page.window.always_on_top)

        # Second close attempt from widget mode: actually exits
        self.page.window.on_event(mock_close_event)
        self.assertFalse(self.page.window.prevent_close)

    def test_status_text_wrapping_configuration(self):
        # Index 5 in home_view is status_row (now a container wrapping the row)
        status_container = self.home_view.controls[5]
        self.assertIsInstance(status_container, ft.Container)
        inner_row = status_container.content
        self.assertIsInstance(inner_row, ft.Row)
        self.assertTrue(inner_row.wrap)

        status_text = inner_row.controls[1]
        self.assertIsInstance(status_text, ft.Text)
        self.assertFalse(status_text.no_wrap)
        self.assertEqual(status_text.text_align, ft.TextAlign.CENTER)


if __name__ == "__main__":
    unittest.main()
