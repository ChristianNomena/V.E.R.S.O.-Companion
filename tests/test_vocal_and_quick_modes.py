"""
Tests for Voice Activated / Deactivated Mode and Window Behavior in V.E.R.S.O.
"""

import unittest
from unittest.mock import MagicMock, patch
import flet as ft

from verso.database import get_recent_tasks, insert_task
from verso.sentinel.sentinel import Sentinel
from verso.ui.app import create_app
from verso.workers.workers import WorkerManager


class TestVocalAndQuickModes(unittest.TestCase):
    def setUp(self):
        def fake_start(s):
            s._is_running = True
            if s.on_state_change:
                s.on_state_change(True)
            return True, ""

        def fake_stop(s):
            s._is_running = False
            if s.on_state_change:
                s.on_state_change(False)

        patch_start = patch.object(Sentinel, "start", fake_start)
        patch_stop = patch.object(Sentinel, "stop", fake_stop)
        patch_start.start()
        patch_stop.start()
        self.addCleanup(patch_start.stop)
        self.addCleanup(patch_stop.stop)

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
        self.content_area = self.main_col.controls[3]  # [top_bar, toolbar, alert, content]
        self.home_view = self.content_area.content
        self.quick_replies_card = self.home_view.controls[6]
        self.response_card = self.home_view.controls[7]
        self.voice_btn = self.top_bar.content.controls[2].controls[1]
        self.wm = getattr(self.page, "_worker_manager", None)
        # Neutralize companion speech: answers must never speak aloud during tests.
        speak_patch = patch("verso.ui.app.TTSService.speak")
        self.mock_speak = speak_patch.start()
        self.addCleanup(speak_patch.stop)

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
        wm = self.wm
        if wm is None:
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

    def test_top_bar_action_buttons_consolidation(self):
        # Left group: History and Home
        left_group = self.top_bar.content.controls[0]
        self.assertEqual(len(left_group.controls), 2)
        history_btn = left_group.controls[0]
        home_btn = left_group.controls[1]
        self.assertEqual(history_btn.width, 34)
        self.assertEqual(history_btn.height, 34)
        self.assertEqual(home_btn.width, 34)
        self.assertEqual(home_btn.height, 34)

        # Right group: All 9 action & utility buttons, all the same 34x34 size
        right_group = self.top_bar.content.controls[2]
        self.assertEqual(len(right_group.controls), 9)
        compact_btn = right_group.controls[0]
        voice_btn = right_group.controls[1]
        observe_btn = right_group.controls[2]
        spontaneity_btn = right_group.controls[3]
        ask_btn = right_group.controls[4]
        chat_btn = right_group.controls[5]
        pin_btn = right_group.controls[6]
        widget_btn = right_group.controls[7]
        theme_btn = right_group.controls[8]

        for btn in right_group.controls:
            self.assertEqual(btn.width, 34)
            self.assertEqual(btn.height, 34)

        # Ask is now a standard action button matching the top-bar button style and icon
        self.assertIsInstance(ask_btn.content, ft.Icon)
        self.assertEqual(ask_btn.content.icon, ft.Icons.QUESTION_MARK_ROUNDED)
        self.assertIsInstance(chat_btn.content, ft.Icon)
        self.assertEqual(chat_btn.content.icon, ft.Icons.FORUM_ROUNDED)
        self.assertIn("Chat with V.E.R.S.O.", chat_btn.tooltip)

        # Pin toggle (window mode only; widget is always pinned by design)
        self.assertIn("Pin Window on Top", pin_btn.tooltip)
        pin_btn.on_click(None)
        self.assertTrue(self.page.window.always_on_top)
        self.assertIn("click to unpin", pin_btn.tooltip)
        pin_btn.on_click(None)
        self.assertFalse(self.page.window.always_on_top)
        self.assertIn("Pin Window on Top", pin_btn.tooltip)

        # Spontaneity toggle
        self.assertIn("ON", spontaneity_btn.tooltip)
        spontaneity_btn.on_click(None)
        self.assertIn("OFF", spontaneity_btn.tooltip)
        spontaneity_btn.on_click(None)
        self.assertIn("ON", spontaneity_btn.tooltip)

        # Body is decluttered: controls_toolbar has height 0 and visible False
        toolbar = self.main_col.controls[1]
        self.assertFalse(toolbar.visible)
        self.assertEqual(toolbar.height, 0)

    def test_companion_chat_panel_open_and_bubbles_rendering(self):
        # Message button is at right_group.controls[5], next to Ask [4]
        from verso.companion.observer import CompanionObserver

        right_group = self.top_bar.content.controls[2]
        chat_btn = right_group.controls[5]
        chat_drawer = self.full_stack.controls[3]
        chat_docked_pane = self.main_layout.controls[2]

        # 1. Before clicking PLAY, companion chat is blocked
        chat_btn.on_click(None)
        self.assertFalse(chat_docked_pane.visible)
        self.assertLess(chat_drawer.right, 0)

        # 2. Click central PLAY button to start listening (toggle_container is at index 3)
        play_btn = self.home_view.controls[3]
        play_btn.on_click(None)

        # 3. Message button opens the chat drawer WITHOUT asking anything
        with patch.object(CompanionObserver, "ask", return_value="must not be used") as mock_ask:
            chat_btn.on_click(None)
            mock_ask.assert_not_called()
        self.assertEqual(chat_drawer.right, 0)

        chat_body = chat_drawer.content.content
        chat_history = chat_body.controls[1]
        chat_col = chat_history.content
        self.assertEqual(len(chat_col.controls), 0)

        # Quick-ask button sits above the input row and triggers the question on click
        quick_row = chat_body.controls[2]
        quick_btn = quick_row.controls[0]
        self.assertEqual("What do you think?", quick_btn.content.value)
        # Clearly clickable: filled accent background, white bold label.
        self.assertEqual(quick_btn.bgcolor, "#0284C7")
        self.assertEqual(quick_btn.content.color, "#FFFFFF")
        before = len(chat_col.controls)
        quick_btn.on_click(None)
        self.assertGreaterEqual(len(chat_col.controls), before + 1)

        # Test sending a message
        input_row = chat_body.controls[3]
        chat_input = input_row.controls[0]
        send_btn = input_row.controls[1]

        chat_input.value = "Hello V.E.R.S.O."
        send_btn.on_click(None)
        self.assertGreaterEqual(len(chat_col.controls), 2)

    def test_companion_answer_spoken_only_when_voice_replies_on(self):
        import time as time_module

        right_group = self.top_bar.content.controls[2]
        ask_btn = right_group.controls[4]
        play_btn = self.home_view.controls[3]
        play_btn.on_click(None)
        ask_btn.on_click(None)

        chat_drawer = self.full_stack.controls[3]
        chat_body = chat_drawer.content.content
        chat_input = chat_body.controls[3].controls[0]
        send_btn = chat_body.controls[3].controls[1]

        def wait_until_idle():
            deadline = time_module.time() + 5.0
            while send_btn.disabled and time_module.time() < deadline:
                time_module.sleep(0.05)
            self.assertFalse(send_btn.disabled)

        # Voice replies ON: the answer is spoken aloud
        with patch("verso.companion.observer.CompanionObserver.ask", return_value="Mocked spoken answer"):
            chat_input.value = "Hello"
            send_btn.on_click(None)
            wait_until_idle()
        self.assertTrue(self.mock_speak.called)
        self.assertIn("Mocked spoken answer", self.mock_speak.call_args.args[0])

        # Silent mode: answers are not spoken
        self.mock_speak.reset_mock()
        self.voice_btn.on_click(None)
        with patch("verso.companion.observer.CompanionObserver.ask", return_value="Mocked silent answer"):
            chat_input.value = "Hello again"
            send_btn.on_click(None)
            wait_until_idle()
        self.mock_speak.assert_not_called()

    def test_ask_shortcut_asks_with_loading_spinner(self):
        import threading as threading_module
        import time as time_module
        from unittest.mock import PropertyMock

        from verso.companion.observer import CompanionObserver

        right_group = self.top_bar.content.controls[2]
        ask_btn = right_group.controls[4]
        play_btn = self.home_view.controls[3]
        play_btn.on_click(None)

        release = threading_module.Event()
        asked = []

        def slow_ask(question, on_delta=None):
            asked.append(question)
            release.wait(timeout=5.0)
            return "Slow answer"

        with patch.object(CompanionObserver, "is_observing", new_callable=PropertyMock, return_value=True), \
             patch.object(CompanionObserver, "ask", side_effect=slow_ask):
            ask_btn.on_click(None)
            # Loading spinner shows synchronously right after the press
            self.assertIsInstance(ask_btn.content, ft.ProgressRing)
            chat_drawer = self.full_stack.controls[3]
            self.assertEqual(chat_drawer.right, 0)
            release.set()
            chat_body = chat_drawer.content.content
            send_btn = chat_body.controls[3].controls[1]
            deadline = time_module.time() + 5.0
            while send_btn.disabled and time_module.time() < deadline:
                time_module.sleep(0.05)
            self.assertFalse(send_btn.disabled)
        self.assertEqual(asked, ["What do you think?"])
        self.assertIsInstance(ask_btn.content, ft.Icon)
        self.assertEqual(ask_btn.content.icon, ft.Icons.QUESTION_MARK_ROUNDED)

    def test_ask_shortcut_asks_even_without_observation(self):
        import threading as threading_module
        import time as time_module

        from verso.companion.observer import CompanionObserver

        right_group = self.top_bar.content.controls[2]
        ask_btn = right_group.controls[4]
        play_btn = self.home_view.controls[3]
        play_btn.on_click(None)

        release = threading_module.Event()
        asked = []

        def slow_ask(question, on_delta=None):
            asked.append(question)
            release.wait(timeout=5.0)
            return "Answer without observation"

        # Observation is NOT running: the shortcut must still ask and spin.
        with patch.object(CompanionObserver, "ask", side_effect=slow_ask):
            ask_btn.on_click(None)
            self.assertIsInstance(ask_btn.content, ft.ProgressRing)
            release.set()
            chat_drawer = self.full_stack.controls[3]
            chat_body = chat_drawer.content.content
            send_btn = chat_body.controls[3].controls[1]
            deadline = time_module.time() + 5.0
            while send_btn.disabled and time_module.time() < deadline:
                time_module.sleep(0.05)
            self.assertFalse(send_btn.disabled)
        self.assertEqual(asked, ["What do you think?"])
        self.assertIsInstance(ask_btn.content, ft.Icon)
        self.assertEqual(ask_btn.content.icon, ft.Icons.QUESTION_MARK_ROUNDED)

    def test_companion_answer_streams_into_bubble_before_completion(self):
        import threading as threading_module
        import time as time_module

        from verso.companion.observer import CompanionObserver

        right_group = self.top_bar.content.controls[2]
        ask_btn = right_group.controls[4]
        play_btn = self.home_view.controls[3]
        play_btn.on_click(None)

        release = threading_module.Event()
        partial_seen = threading_module.Event()

        def streaming_ask(question, on_delta=None):
            if on_delta is not None:
                on_delta("Partial streamed ")
                partial_seen.set()
            release.wait(timeout=5.0)
            if on_delta is not None:
                on_delta("answer")
            return "Partial streamed answer"

        with patch.object(CompanionObserver, "ask", side_effect=streaming_ask):
            ask_btn.on_click(None)
            self.assertTrue(partial_seen.wait(timeout=5.0))
            # While generation is still running, the partial text is visible
            # and the Ask spinner is still showing.
            chat_drawer = self.full_stack.controls[3]
            chat_body = chat_drawer.content.content
            chat_col = chat_body.controls[1].content
            bubble_texts = [
                ctrl.content.value
                for row in chat_col.controls
                for ctrl in row.controls
                if isinstance(getattr(ctrl, "content", None), ft.Text)
            ]
            self.assertTrue(any("Partial streamed" in t for t in bubble_texts))
            self.assertIsInstance(ask_btn.content, ft.ProgressRing)
            release.set()
            send_btn = chat_body.controls[3].controls[1]
            deadline = time_module.time() + 5.0
            while send_btn.disabled and time_module.time() < deadline:
                time_module.sleep(0.05)
            self.assertFalse(send_btn.disabled)
        # Loading ends with generation, before/without waiting for speech.
        self.assertIsInstance(ask_btn.content, ft.Icon)
        self.assertEqual(ask_btn.content.icon, ft.Icons.QUESTION_MARK_ROUNDED)

    def test_stop_button_stops_tts_stt_and_worker(self):
        play_btn = self.home_view.controls[3]
        play_btn.on_click(None)  # start listening

        wm = self.wm
        if wm is None:
            import gc

            wms = [obj for obj in gc.get_objects() if isinstance(obj, WorkerManager)]
            wm = wms[-1]

        with patch("verso.ui.app.TTSService.stop") as mock_tts_stop, patch(
            "verso.ui.app.STTService.stop"
        ) as mock_stt_stop:
            play_btn.on_click(None)  # STOP: everything must halt, TTS included
            mock_tts_stop.assert_called()
            mock_stt_stop.assert_called()
        self.assertTrue(wm._cancel_event.is_set())

    def test_observation_requires_play_button_and_stops_with_play(self):
        # observe_btn is at right_group.controls[2]
        right_group = self.top_bar.content.controls[2]
        observe_btn = right_group.controls[2]
        companion_section = self.home_view.controls[8]
        companion_status_text = companion_section.controls[0].content.controls[1]
        play_btn = self.home_view.controls[3]

        # 1. Before clicking PLAY, observation is blocked
        observe_btn.on_click(None)
        self.assertIn("Click PLAY first", companion_status_text.value)

        # 2. Click central PLAY button to start listening
        play_btn.on_click(None)

        # 3. Now observation starts successfully
        def fake_obs_start(s):
            s._is_observing = True
            return True, ""

        def fake_obs_stop(s, purge=True):
            s._is_observing = False

        with patch("verso.companion.observer.CompanionObserver.start", fake_obs_start), \
             patch("verso.companion.observer.CompanionObserver.stop", fake_obs_stop):
            observe_btn.on_click(None)
            self.assertIn("Observation running", companion_status_text.value)

            # 4. Pausing listening (clicking PLAY button again) automatically stops observation
            play_btn.on_click(None)
            self.assertIn("Partner idle", companion_status_text.value)

    def test_widget_mode_action_buttons_and_exclusions(self):
        from types import SimpleNamespace

        # Switch to widget mode via widget_mode_btn
        widget_btn = self.top_bar.content.controls[2].controls[7]
        widget_btn.on_click(None)

        mini_widget_view = self.root.content
        mini_widget_row = mini_widget_view.content.controls[0]
        mini_home_zone = mini_widget_row.controls[0]
        mini_status_label = mini_home_zone.content.controls[2].controls[1]
        mini_actions_row = mini_widget_row.controls[2]

        # 1. Total buttons in mini_actions_row: 7 buttons (no theme toggle in widget mode)
        # [mini_copy_btn, mini_sentinel_btn, mini_voice_btn, mini_observe_btn,
        #  mini_spontaneity_btn, mini_ask_btn, mini_expand_btn]
        self.assertEqual(len(mini_actions_row.controls), 7)

        mini_copy_btn = mini_actions_row.controls[0]
        mini_sentinel_btn = mini_actions_row.controls[1]
        mini_voice_btn = mini_actions_row.controls[2]
        mini_observe_btn = mini_actions_row.controls[3]
        mini_spontaneity_btn = mini_actions_row.controls[4]
        mini_ask_btn = mini_actions_row.controls[5]
        mini_expand_btn = mini_actions_row.controls[6]

        # Check dimensions: 26x26 for compact widget footprint
        for btn in mini_actions_row.controls:
            self.assertEqual(btn.width, 26)
            self.assertEqual(btn.height, 26)

        # Tooltips inspection
        tooltips = [btn.tooltip for btn in mini_actions_row.controls if btn.tooltip]
        self.assertTrue(any("listening" in t.lower() for t in tooltips))
        self.assertTrue(any("Voice replies" in t for t in tooltips))
        self.assertTrue(any("consented observation" in t.lower() for t in tooltips))
        self.assertTrue(any("Spontaneous suggestions" in t for t in tooltips))
        self.assertTrue(any("Ask V.E.R.S.O." in t for t in tooltips))
        self.assertTrue(any("Back to full window" in t for t in tooltips))
        self.assertEqual(mini_ask_btn.content.icon, ft.Icons.QUESTION_MARK_ROUNDED)

        # Explicit Exclusion: NO light/dark theme toggle in widget mode
        self.assertFalse(any("Light Mode" in t or "Dark Mode" in t for t in tooltips))

        # Explicit Exclusion 1: NO pin button in widget mode
        self.assertFalse(any("pin" in (btn.tooltip or "").lower() for btn in mini_actions_row.controls))

        # Explicit Exclusion 2: NO exit/close button in widget mode
        self.assertFalse(any("exit" in (btn.tooltip or "").lower() or "close" in (btn.tooltip or "").lower() for btn in mini_actions_row.controls))

        # 2. Test Hover hints display dynamically on mini_status_label
        mock_hover_in = SimpleNamespace(data="true")
        mock_hover_out = SimpleNamespace(data="false")

        mini_sentinel_btn.on_hover(mock_hover_in)
        self.assertEqual(mini_status_label.value, "Start listening")
        mini_sentinel_btn.on_hover(mock_hover_out)
        self.assertEqual(mini_status_label.value, "Idle")

        mini_observe_btn.on_hover(mock_hover_in)
        self.assertEqual(mini_status_label.value, "Needs PLAY")
        mini_observe_btn.on_hover(mock_hover_out)
        self.assertEqual(mini_status_label.value, "Idle")

        # 3. Before clicking PLAY: observation and chat are BLOCKED
        mini_observe_btn.on_click(None)
        self.assertEqual(mini_status_label.value, "Click PLAY first")

        mini_ask_btn.on_click(None)
        self.assertEqual(mini_status_label.value, "Click PLAY first")
        # Stays in widget mode because PLAY was not clicked
        self.assertNotEqual(self.root.content, self.full_stack)

        # 4. Test mini_spontaneity_btn toggles
        self.assertIn("ON", mini_spontaneity_btn.tooltip)
        mini_spontaneity_btn.on_click(None)
        self.assertIn("OFF", mini_spontaneity_btn.tooltip)
        mini_spontaneity_btn.on_click(None)
        self.assertIn("ON", mini_spontaneity_btn.tooltip)

        # 5. Theme stays untouched in widget mode (no theme button there)
        self.assertEqual(self.page.theme_mode, ft.ThemeMode.DARK)

        # 6. Click PLAY in widget mode (mini_sentinel_btn)
        mini_sentinel_btn.on_click(None)
        self.assertEqual(mini_status_label.value, "Listening")

        # Now hover hints reflect active listening state
        mini_sentinel_btn.on_hover(mock_hover_in)
        self.assertEqual(mini_status_label.value, "Pause listening")
        mini_sentinel_btn.on_hover(mock_hover_out)

        mini_observe_btn.on_hover(mock_hover_in)
        self.assertEqual(mini_status_label.value, "Start observe")
        mini_observe_btn.on_hover(mock_hover_out)

        # 7. Hover on mini_ask_btn reflects "Ask AI" when listening
        mini_ask_btn.on_hover(mock_hover_in)
        self.assertEqual(mini_status_label.value, "Ask AI")
        mini_ask_btn.on_hover(mock_hover_out)

        # 8. Now that PLAY is active, mini_ask_btn triggers Ask directly in widget mode
        with patch("verso.companion.observer.CompanionObserver.ask", return_value="Widget advice"):
            mini_ask_btn.on_click(None)
        # Stays in widget mode (does not kick user to full window chat)
        self.assertNotEqual(self.root.content, self.full_stack)
        self.assertIn(mini_status_label.value, ["Thinking...", "Ready (Cmd+V)", "Listening"])

    def test_voice_speaking_state_wave_and_contour(self):
        # 1. Switch to widget mode so we can inspect both full window and widget controls
        widget_btn = self.top_bar.content.controls[2].controls[7]
        widget_btn.on_click(None)

        mini_widget_view = self.root.content
        mini_widget_row = mini_widget_view.content.controls[0]
        mini_home_zone = mini_widget_row.controls[0]
        mini_status_label = mini_home_zone.content.controls[2].controls[1]
        mini_actions_row = mini_widget_row.controls[2]
        mini_sentinel_btn = mini_actions_row.controls[1]
        mini_sentinel_icon = mini_sentinel_btn.content

        toggle_container = self.home_view.controls[3]
        btn_icon = toggle_container.content

        # Initial state (idle)
        self.assertEqual(btn_icon.icon, ft.Icons.PLAY_ARROW_ROUNDED)
        self.assertEqual(mini_sentinel_icon.icon, ft.Icons.PLAY_ARROW_ROUNDED)

        # 2. Listening starts (waiting for speech): mic icon appears on both buttons
        self.page._set_voice_speaking_state(True, False)
        self.assertEqual(btn_icon.icon, ft.Icons.MIC_ROUNDED)
        self.assertEqual(mini_sentinel_icon.icon, ft.Icons.MIC_ROUNDED)
        self.assertEqual(mini_status_label.value, "Speak now 🎙️")

        # 3. User is actively speaking: wave around central button, contour on widget button
        self.page._set_voice_speaking_state(True, True)
        self.assertEqual(btn_icon.icon, ft.Icons.MIC_ROUNDED)
        self.assertEqual(btn_icon.color, "#38BDF8")
        self.assertGreaterEqual(toggle_container.border.top.width, 3.0)
        self.assertEqual(toggle_container.border.top.color, "#38BDF8")
        # Sonic wave shadows around central button
        self.assertIsInstance(toggle_container.shadow, list)
        self.assertGreaterEqual(len(toggle_container.shadow), 2)
        self.assertGreaterEqual(toggle_container.shadow[0].spread_radius, 5)

        # Widget mode button: mic icon + highlighted contour
        self.assertEqual(mini_sentinel_icon.icon, ft.Icons.MIC_ROUNDED)
        self.assertEqual(mini_sentinel_icon.color, "#38BDF8")
        self.assertGreaterEqual(mini_sentinel_btn.border.top.width, 2.0)
        self.assertEqual(mini_sentinel_btn.border.top.color, "#38BDF8")
        self.assertIsNotNone(mini_sentinel_btn.shadow)
        self.assertEqual(mini_status_label.value, "Speaking... 🎙️")
        self.assertEqual(mini_status_label.color, "#38BDF8")

        # 4. Vocal reply completes (is_listening=False, is_speaking=False)
        self.page._set_voice_speaking_state(False, False)
        self.assertEqual(btn_icon.icon, ft.Icons.PLAY_ARROW_ROUNDED)
        self.assertEqual(mini_sentinel_icon.icon, ft.Icons.PLAY_ARROW_ROUNDED)
        self.assertIsNone(mini_sentinel_btn.shadow)

    def test_worker_manager_speech_state_callback(self):
        speech_states = []

        def track_speech(is_listening: bool, is_speaking: bool):
            speech_states.append((is_listening, is_speaking))

        wm = WorkerManager(
            on_speech_state=track_speech,
            voice_enabled=True,
        )

        with patch("verso.services.tts_service.TTSService.speak", side_effect=lambda text, on_complete=None: on_complete() if on_complete else None), \
             patch("verso.services.stt_service.STTService.listen") as mock_stt, \
             patch("verso.services.muse_client.MuseClient.finalize_response", return_value="Drafted response"):

            def fake_listen(duration=4.0, on_speech_detected=None, on_transcribed=None):
                if on_speech_detected:
                    on_speech_detected(True)
                if on_transcribed:
                    on_transcribed("Yes please")

            mock_stt.side_effect = fake_listen
            wm._run_task("Slack", "From Bob: Are you free?")

        self.assertIn((True, False), speech_states)
        self.assertIn((True, True), speech_states)
        self.assertIn((False, False), speech_states)

    def test_stt_vad_rms_and_speech_detection(self):
        import struct
        from verso.services.stt_service import STTService, _calculate_rms

        # Silence chunk (16-bit PCM all zeros)
        silence = bytes(3200)
        self.assertEqual(_calculate_rms(silence), 0)

        # Loud tone chunk (sinusoid / high amplitude 16-bit PCM)
        loud_pcm = struct.pack("<1600h", *([12000, -12000] * 800))
        loud_rms = _calculate_rms(loud_pcm)
        self.assertGreater(loud_rms, STTService.SPEECH_RMS_THRESHOLD)


if __name__ == "__main__":
    unittest.main()
