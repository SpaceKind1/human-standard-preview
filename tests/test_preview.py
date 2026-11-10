"""Participant-flow regressions. Run: python3 -m unittest discover -s tests -v."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import re
import unittest

from playwright.sync_api import expect, sync_playwright


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.server = ThreadingHTTPServer(
            ('127.0.0.1', 0), partial(QuietHandler, directory=str(root))
        )
        cls.server_thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/'
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            executable_path='/usr/bin/chromium', headless=True
        )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()

    def setUp(self):
        self.context = self.browser.new_context(reduced_motion='reduce')
        self.page = self.context.new_page()
        self.page.set_default_timeout(3000)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.goto(self.url)
        self.navigate('The Journey')

    def tearDown(self):
        try:
            self.assertEqual(self.errors, [], 'Uncaught application JavaScript errors')
        finally:
            self.context.close()

    def navigate(self, name):
        self.page.get_by_role('button', name=name, exact=True).click()

    def finish(self, quick):
        self.page.locator('#quick-mode' if quick else '#full-mode').click()
        if not quick:
            self.page.locator('.chapter-chip').nth(4).click()
        for _ in range(3 if quick else 6):
            self.page.locator('#next').click()
        expect(self.page.locator('#session-complete')).to_be_visible()

    def install_speech_recorder(self):
        # Record application speech requests without depending on installed voices.
        self.context.add_init_script('''
            window.spoken = [];
            window.utterances = [];
            window.speechCancelCount = 0;
            Object.defineProperty(window, 'speechSynthesis', {value: {
                cancel() { window.speechCancelCount++; },
                speak(utterance) {
                    window.spoken.push(utterance.text);
                    window.utterances.push(utterance);
                }
            }});
        ''')
        self.page.reload()
        self.navigate('The Journey')

    def test_chapter_selection_replaces_completion(self):
        for quick in (True, False):
            with self.subTest(quick=quick):
                self.finish(quick)
                self.page.locator('.chapter-chip').nth(1).click()
                expect(self.page.locator('#session-complete')).to_be_hidden()
                expect(self.page.locator('#rest-screen')).to_be_hidden()
                expect(self.page.locator('#question-panel')).to_be_visible()
                expect(self.page.locator('#progress-label')).to_have_text(
                    'Question 7 of 30 · Chapter 2 of 5'
                )

    def test_chapter_pause_survives_view_navigation(self):
        for _ in range(6):
            self.page.locator('#next').click()
        expect(self.page.locator('#rest-screen')).to_be_visible()
        self.navigate('The Journey')
        expect(self.page.locator('#rest-screen')).to_be_visible()
        self.navigate('Welcome')
        self.navigate('The Journey')
        expect(self.page.locator('#rest-screen')).to_be_visible()
        expect(self.page.locator('#question-panel')).to_be_hidden()
        self.page.locator('#continue-chapter').click()
        expect(self.page.locator('#progress-label')).to_have_text(
            'Question 7 of 30 · Chapter 2 of 5'
        )

    def test_completion_survives_view_navigation(self):
        for quick in (True, False):
            with self.subTest(quick=quick):
                self.finish(quick)
                message = self.page.locator('#completion-message').inner_text()
                self.navigate('Welcome')
                self.navigate('The Journey')
                expect(self.page.locator('#session-complete')).to_be_visible()
                expect(self.page.locator('#question-panel')).to_be_hidden()
                expect(self.page.locator('#completion-message')).to_have_text(message)

    def test_sample_is_discarded_when_chapter_pauses(self):
        for _ in range(5):
            self.page.locator('#next').click()
        self.page.locator('#reflection').fill('Temporary sample text')
        self.page.locator('#next').click()
        expect(self.page.locator('#rest-screen')).to_be_visible()
        expect(self.page.locator('#reflection')).to_have_value('')
        expect(self.page.locator('#word-hint')).to_have_text(
            '0 words typed · No minimum or maximum'
        )

    def test_sample_is_discarded_on_completion(self):
        for quick in (True, False):
            with self.subTest(quick=quick):
                self.page.locator('#quick-mode' if quick else '#full-mode').click()
                if not quick:
                    self.page.locator('.chapter-chip').nth(4).click()
                for _ in range(2 if quick else 5):
                    self.page.locator('#next').click()
                self.page.locator('#reflection').fill('Temporary sample text')
                self.page.locator('#next').click()
                expect(self.page.locator('#session-complete')).to_be_visible()
                expect(self.page.locator('#reflection')).to_have_value('')
                expect(self.page.locator('#word-hint')).to_have_text(
                    '0 words typed · No minimum or maximum'
                )

    def test_mobile_chapter_navigation_reveals_focused_question(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.locator('.chapter-chip').nth(4).click()
        expect(self.page.locator('#chapter-question')).to_be_focused()
        self.page.wait_for_function('''() => {
            const bounds = document.getElementById('chapter-question').getBoundingClientRect();
            return bounds.top >= 0 && bounds.bottom <= window.innerHeight;
        }''')

    def test_auto_read_does_not_read_a_hidden_completed_question(self):
        self.install_speech_recorder()
        self.finish(quick=True)
        self.page.locator('#auto-read').check()
        self.assertEqual(self.page.evaluate('window.spoken'), [])

    def test_turning_off_auto_read_cancels_scheduled_question(self):
        self.install_speech_recorder()
        self.page.locator('#auto-read').check()
        self.page.locator('#next').click()
        self.page.locator('#auto-read').uncheck()
        self.page.evaluate('window.spoken = []')
        # The app intentionally waits 600ms before speaking with Gentle pause.
        # Wait beyond that boundary to prove disabling it prevents queued speech.
        self.page.wait_for_timeout(750)
        self.assertEqual(self.page.evaluate('window.spoken'), [])

    def test_missing_speech_apis_disable_audio_controls_but_keep_text_usable(self):
        self.context.add_init_script('''
            delete window.speechSynthesis;
            delete window.SpeechSynthesisUtterance;
        ''')
        self.page.reload()
        self.navigate('The Journey')
        self.assertTrue(self.page.evaluate('''
            !('speechSynthesis' in window) && !('SpeechSynthesisUtterance' in window)
        '''))
        for control in ('read-question', 'read-help', 'hear-chapter', 'auto-read',
                        'speech-rate', 'reading-pause'):
            with self.subTest(control=control):
                expect(self.page.locator(f'#{control}')).to_be_disabled()
        expect(self.page.locator('#audio-status')).to_have_text(
            'Read aloud is not supported in this browser. Questions remain available as text.'
        )
        expect(self.page.locator('#audio-status')).to_be_visible()
        self.page.locator('#toggle-prompt').click()
        expect(self.page.locator('#optional-prompt')).to_be_visible()
        self.page.locator('#reflection').fill('Text remains usable')
        expect(self.page.locator('#word-hint')).to_contain_text('3 words typed')
        self.page.locator('#next').click()
        expect(self.page.locator('#chapter-question')).to_have_text(
            'What does integrity look like when nobody is watching?'
        )

    def test_queued_speech_can_be_stopped_before_start_and_ignores_stale_start(self):
        self.install_speech_recorder()
        self.page.locator('#read-question').click()
        self.assertEqual(self.page.evaluate('window.utterances.length'), 1)
        expect(self.page.locator('#stop-reading')).to_be_enabled()
        cancel_count = self.page.evaluate('window.speechCancelCount')
        self.page.locator('#stop-reading').click()
        self.assertGreater(self.page.evaluate('window.speechCancelCount'), cancel_count)
        # A platform may deliver a start callback after the request was cancelled.
        self.page.evaluate('window.utterances[0].onstart()')
        expect(self.page.locator('#audio-status')).to_have_text('Reading stopped.')
        expect(self.page.locator('#stop-reading')).to_be_disabled()

    def test_manual_read_and_stop_cancel_pending_automatic_read(self):
        self.install_speech_recorder()
        self.page.locator('#auto-read').check()
        self.page.locator('#next').click()
        self.page.locator('#read-question').click()
        self.page.evaluate('window.utterances.at(-1).onstart()')
        self.page.locator('#stop-reading').click()
        request_count = self.page.evaluate('window.spoken.length')
        self.page.wait_for_timeout(750)
        self.assertEqual(self.page.evaluate('window.spoken.length'), request_count)
        expect(self.page.locator('#audio-status')).to_have_text('Reading stopped.')

    def test_stop_cancels_automatic_read_during_the_gentle_pause(self):
        self.install_speech_recorder()
        self.page.locator('#auto-read').check()
        self.page.locator('#next').click()
        expect(self.page.locator('#stop-reading')).to_be_enabled()
        request_count = self.page.evaluate('window.spoken.length')
        self.assertEqual(request_count, 1, 'The next question must still be waiting to speak')
        self.page.locator('#stop-reading').click()
        self.page.wait_for_timeout(750)
        self.assertEqual(self.page.evaluate('window.spoken.length'), request_count)
        expect(self.page.locator('#audio-status')).to_have_text('Reading stopped.')

    def test_chapter_introduction_is_available_only_with_a_question(self):
        for _ in range(6):
            self.page.locator('#next').click()
        expect(self.page.locator('#hear-chapter')).to_be_hidden()
        self.page.locator('#continue-chapter').click()
        expect(self.page.locator('#hear-chapter')).to_be_visible()
        self.finish(quick=True)
        expect(self.page.locator('#hear-chapter')).to_be_hidden()
        self.page.locator('#return-full').click()
        expect(self.page.locator('#hear-chapter')).to_be_visible()

    def test_focused_questions_describe_current_full_and_quick_progress(self):
        self.page.locator('#next').click()
        expect(self.page.locator('#chapter-question')).to_be_focused()
        expect(self.page.locator('#chapter-question')).to_have_accessible_description(
            self.page.locator('#progress-label').inner_text()
        )
        self.page.locator('#quick-mode').click()
        self.page.locator('#next').click()
        expect(self.page.locator('#chapter-question')).to_be_focused()
        expect(self.page.locator('#chapter-question')).to_have_accessible_description(
            'Quick reflection 2 of 3 · Sample questions only'
        )

    def test_reflection_describes_discard_guidance_and_current_word_count(self):
        guidance = self.page.get_by_text('Typing is optional.', exact=False).inner_text()
        self.page.locator('#reflection').fill('Sample text only')
        expect(self.page.locator('#reflection')).to_have_accessible_description(
            re.compile(re.escape(guidance))
        )
        expect(self.page.locator('#reflection')).to_have_accessible_description(
            re.compile(re.escape('3 words typed · No minimum or maximum'))
        )
        self.page.locator('#clear-reflection').click()
        expect(self.page.locator('#reflection')).to_be_focused()
        expect(self.page.locator('#reflection')).to_have_accessible_description(
            re.compile(re.escape('0 words typed · No minimum or maximum'))
        )

    def test_focused_pause_and_completion_are_named_explanatory_groups(self):
        for _ in range(6):
            self.page.locator('#next').click()
        rest = self.page.locator('#rest-screen')
        expect(rest).to_be_focused()
        expect(rest).to_have_role('group')
        expect(rest).to_have_accessible_name(self.page.locator('#rest-title').inner_text())
        expect(rest).to_have_accessible_description(
            re.compile(re.escape(self.page.locator('#rest-copy').inner_text()))
        )
        for quick in (True, False):
            with self.subTest(quick=quick):
                self.finish(quick)
                completion = self.page.locator('#session-complete')
                expect(completion).to_be_focused()
                expect(completion).to_have_role('group')
                expect(completion).to_have_accessible_name(
                    self.page.locator('#completion-title').inner_text()
                )
                expect(completion).to_have_accessible_description(
                    re.compile(re.escape(self.page.locator('#completion-message').inner_text()))
                )

    def test_full_question_navigator_jumps_within_current_chapter(self):
        navigator = self.page.locator('#question-list')
        expect(navigator).to_have_role('group')
        buttons = navigator.get_by_role('button')
        expect(buttons).to_have_count(6)
        chapter_one = (
            'What qualities do you value in people?',
            'What does integrity look like when nobody is watching?',
            'What helps you trust someone?',
            'What actions make you lose respect for someone?',
            'How might someone respond after causing harm?',
            'What personal value matters most to you?',
        )
        for number, question in enumerate(chapter_one, start=1):
            expect(buttons.nth(number - 1)).to_have_accessible_name(
                f'Question {number}: {question}'
            )
        expect(buttons.nth(0)).to_have_attribute('aria-current', 'step')
        self.page.locator('#reflection').fill('Temporary navigator sample')
        self.page.locator('#toggle-prompt').click()
        buttons.nth(0).click()
        expect(self.page.locator('#chapter-question')).to_be_focused()
        expect(self.page.locator('#reflection')).to_have_value('Temporary navigator sample')
        expect(self.page.locator('#optional-prompt')).to_be_visible()
        buttons.nth(3).click()
        expect(self.page.locator('#chapter-question')).to_have_text(chapter_one[3])
        expect(self.page.locator('#chapter-question')).to_be_focused()
        expect(self.page.locator('#progress-label')).to_have_text(
            'Question 4 of 30 · Chapter 1 of 5'
        )
        expect(self.page.locator('#reflection')).to_have_value('')
        expect(self.page.locator('#optional-prompt')).to_be_hidden()
        expect(buttons.nth(3)).to_have_attribute('aria-current', 'step')
        expect(navigator.locator('[aria-current="step"]')).to_have_count(1)

        self.page.locator('.chapter-chip').nth(2).click()
        expect(buttons).to_have_count(6)
        expect(buttons.nth(0)).to_have_accessible_name(
            'Question 1: What helps people through hard times?'
        )
        expect(buttons.nth(5)).to_have_accessible_name(
            'Question 6: What helps protect your peace of mind?'
        )
        buttons.nth(2).click()
        expect(self.page.locator('#chapter-question')).to_have_text(
            'What does emotional maturity look like?'
        )
        expect(self.page.locator('#progress-label')).to_have_text(
            'Question 15 of 30 · Chapter 3 of 5'
        )
        buttons.nth(5).click()
        self.page.locator('#next').click()
        expect(self.page.locator('#rest-screen')).to_be_visible()
        buttons.nth(5).click()
        expect(self.page.locator('#rest-screen')).to_be_hidden()
        expect(self.page.locator('#progress-label')).to_have_text(
            'Question 18 of 30 · Chapter 3 of 5'
        )
        self.page.locator('.chapter-chip').nth(4).click()
        buttons.nth(5).click()
        self.page.locator('#next').click()
        expect(self.page.locator('#session-complete')).to_be_visible()
        buttons.nth(5).click()
        expect(self.page.locator('#session-complete')).to_be_hidden()
        expect(self.page.locator('#question-panel')).to_be_visible()
        expect(self.page.locator('#progress-label')).to_have_text(
            'Question 30 of 30 · Chapter 5 of 5'
        )

    def test_quick_question_navigator_preserves_sequence_and_mobile_focus(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.locator('#quick-mode').click()
        navigator = self.page.locator('#question-list')
        buttons = navigator.get_by_role('button')
        expect(buttons).to_have_count(3)
        samples = (
            'What does integrity look like when nobody is watching?',
            'What helps rebuild broken trust?',
            'What makes a person well-developed?',
        )
        for number, question in enumerate(samples, start=1):
            expect(buttons.nth(number - 1)).to_have_accessible_name(
                f'Reflection {number}: {question}'
            )
        self.page.locator('#reflection').fill('Temporary quick sample')
        self.page.locator('#toggle-prompt').click()
        buttons.nth(2).click()
        expect(self.page.locator('#chapter-question')).to_have_text(samples[2])
        expect(self.page.locator('#chapter-question')).to_be_focused()
        expect(self.page.locator('#progress-label')).to_have_text(
            'Quick reflection 3 of 3 · Sample questions only'
        )
        expect(self.page.locator('#reflection')).to_have_value('')
        expect(self.page.locator('#optional-prompt')).to_be_hidden()
        expect(buttons.nth(2)).to_have_attribute('aria-current', 'step')
        expect(navigator.locator('[aria-current="step"]')).to_have_count(1)
        self.page.wait_for_function('''() => {
            const bounds = document.getElementById('chapter-question').getBoundingClientRect();
            return bounds.top >= 0 && bounds.bottom <= window.innerHeight;
        }''')
        self.page.locator('#prev').click()
        expect(self.page.locator('#chapter-question')).to_have_text(samples[1])
        buttons.nth(0).click()
        expect(self.page.locator('#prev')).to_be_disabled()
        self.page.locator('#next').click()
        expect(self.page.locator('#chapter-question')).to_have_text(samples[1])
        buttons.nth(2).click()
        self.page.locator('#next').click()
        expect(self.page.locator('#session-complete')).to_be_visible()
        expect(self.page.locator('#completion-message')).to_contain_text('three sample questions')

    def test_quick_completion_actions_restart_or_return_to_welcome(self):
        self.finish(quick=True)
        expect(self.page.locator('#return-full')).to_have_text('Explore the full journey')
        expect(self.page.locator('#restart-quick')).to_be_visible()
        self.page.locator('#completion-welcome').click()
        expect(self.page.locator('#welcome')).to_be_visible()
        self.navigate('The Journey')
        expect(self.page.locator('#session-complete')).to_be_visible()
        self.page.locator('#restart-quick').click()
        expect(self.page.locator('#session-complete')).to_be_hidden()
        expect(self.page.locator('#chapter-question')).to_be_focused()
        expect(self.page.locator('#quick-mode')).to_have_attribute('aria-pressed', 'true')
        expect(self.page.locator('#progress-label')).to_have_text(
            'Quick reflection 1 of 3 · Sample questions only'
        )
        expect(self.page.locator('#reflection')).to_have_value('')
        expect(self.page.locator('#question-list button').nth(0)).to_have_attribute(
            'aria-current', 'step'
        )

    def test_full_completion_actions_restart_or_return_to_welcome(self):
        self.finish(quick=False)
        expect(self.page.locator('#return-full')).to_have_text('Start the full journey again')
        expect(self.page.locator('#restart-quick')).to_be_hidden()
        self.page.locator('#completion-welcome').click()
        expect(self.page.locator('#welcome')).to_be_visible()
        self.navigate('The Journey')
        expect(self.page.locator('#session-complete')).to_be_visible()
        self.page.locator('#return-full').click()
        expect(self.page.locator('#session-complete')).to_be_hidden()
        expect(self.page.locator('#chapter-question')).to_be_focused()
        expect(self.page.locator('#full-mode')).to_have_attribute('aria-pressed', 'true')
        expect(self.page.locator('#progress-label')).to_have_text(
            'Question 1 of 30 · Chapter 1 of 5'
        )
        expect(self.page.locator('#reflection')).to_have_value('')
        expect(self.page.locator('#prev')).to_be_disabled()
        expect(self.page.locator('#question-list button').nth(0)).to_have_attribute(
            'aria-current', 'step'
        )

if __name__ == '__main__':
    unittest.main()
