"""Participant-flow regressions. Run: python3 -m unittest discover -s tests -v."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import unquote_plus, urlsplit
import os
import re
import shutil
import unittest

from playwright.sync_api import Error as PlaywrightError, expect, sync_playwright


def chromium_launch_options():
    """Use an explicit or system Chromium, falling back to Playwright's browser."""
    override = os.environ.get('PREVIEW_BROWSER_EXECUTABLE')
    if override:
        executable = Path(override).expanduser()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise RuntimeError(
                'PREVIEW_BROWSER_EXECUTABLE must point to an executable Chromium '
                f'browser: {override}'
            )
        return {'executable_path': str(executable.resolve()), 'headless': True}
    for name in ('chromium', 'chromium-browser'):
        executable = shutil.which(name)
        if executable:
            return {'executable_path': executable, 'headless': True}
    return {'headless': True}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        launch_options = chromium_launch_options()
        root = Path(__file__).resolve().parents[1]
        cls.server = ThreadingHTTPServer(
            ('127.0.0.1', 0), partial(QuietHandler, directory=str(root))
        )
        cls.addClassCleanup(cls.server.server_close)
        cls.server_thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.addClassCleanup(cls.server_thread.join)
        cls.addClassCleanup(cls.server.shutdown)
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/'
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        try:
            cls.browser = cls.playwright.chromium.launch(**launch_options)
        except PlaywrightError as error:
            raise RuntimeError(
                'Could not launch Chromium. Install a managed browser with '
                '"python -m playwright install chromium", or set '
                'PREVIEW_BROWSER_EXECUTABLE to an installed Chromium executable.'
            ) from error
        cls.addClassCleanup(cls.browser.close)

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
        if quick:
            self.page.locator('#question-list button').nth(0).click()
        else:
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

    def test_document_history_does_not_restore_discarded_sample_text(self):
        readme_url = self.url + 'README.md'
        for direction in ('back', 'forward'):
            with self.subTest(direction=direction):
                if direction == 'forward':
                    self.page.goto(readme_url)
                    self.page.goto(self.url)
                    self.navigate('The Journey')
                self.page.locator('#reflection').fill('Temporary document history sample')
                expect(self.page.locator('#word-hint')).to_contain_text('4 words typed')
                if direction == 'back':
                    self.page.goto(readme_url)
                    self.page.go_back()
                else:
                    self.page.go_back()
                    self.page.go_forward()
                expect(self.page).to_have_url(self.url)
                self.navigate('The Journey')
                expect(self.page.locator('#reflection')).to_have_value('')
                expect(self.page.locator('#word-hint')).to_have_text(
                    '0 words typed · No minimum or maximum'
                )

    def test_page_lifecycle_cancels_active_and_pending_speech(self):
        self.install_speech_recorder()
        for event_name in ('pagehide', 'pageshow'):
            for state in ('active', 'pending'):
                with self.subTest(event=event_name, state=state):
                    self.page.goto(self.url)
                    self.navigate('The Journey')
                    if state == 'active':
                        self.page.locator('#read-question').click()
                        self.page.evaluate('window.utterances.at(-1).onstart()')
                    else:
                        self.page.locator('#auto-read').check()
                        self.page.locator('#next').click()
                        self.assertEqual(self.page.evaluate('window.spoken.length'), 1)
                    self.page.locator('#reflection').fill('Temporary lifecycle sample')
                    expect(self.page.locator('#stop-reading')).to_be_enabled()
                    cancel_count = self.page.evaluate('window.speechCancelCount')
                    speech_count = self.page.evaluate('window.spoken.length')
                    # Dispatch before document destruction so we can inspect the
                    # handler and queued timer. Native Back/Forward is covered above.
                    self.page.evaluate("""eventName => {
                        window.dispatchEvent(new PageTransitionEvent(eventName, {
                            persisted: true
                        }));
                    }""", event_name)
                    expect(self.page.locator('#stop-reading')).to_be_disabled()
                    self.assertGreater(self.page.evaluate('window.speechCancelCount'), cancel_count)
                    expect(self.page.locator('#reflection')).to_have_value('')
                    expect(self.page.locator('#word-hint')).to_have_text(
                        '0 words typed · No minimum or maximum'
                    )
                    if state == 'pending':
                        self.page.wait_for_timeout(750)
                        self.assertEqual(self.page.evaluate('window.spoken.length'), speech_count)

    def test_navigation_resets_cancelled_speech_status(self):
        self.install_speech_recorder()
        self.page.locator('#read-question').click()
        self.page.evaluate('window.utterances.at(-1).onstart()')
        expect(self.page.locator('#audio-status')).to_have_text('Reading aloud…')
        self.navigate('Welcome')
        self.navigate('The Journey')
        expect(self.page.locator('#stop-reading')).to_be_disabled()
        expect(self.page.locator('#audio-status')).to_have_text(
            'Audio is optional. Use Read aloud if your browser supports it. Nothing is recorded.'
        )

    def test_mobile_chapter_introduction_has_visible_working_stop(self):
        self.install_speech_recorder()
        self.page.set_viewport_size({'width': 320, 'height': 740})
        self.page.locator('#hear-chapter').click()
        self.page.evaluate('window.utterances.at(-1).onstart()')
        stop = self.page.locator('#stop-introduction')
        expect(stop).to_be_visible()
        expect(stop).to_be_enabled()
        self.page.wait_for_function('''() => {
            const bounds = document.getElementById('stop-introduction').getBoundingClientRect();
            return bounds.top >= 0 && bounds.bottom <= window.innerHeight;
        }''')
        cancel_count = self.page.evaluate('window.speechCancelCount')
        stop.click()
        self.assertGreater(self.page.evaluate('window.speechCancelCount'), cancel_count)
        expect(stop).to_be_disabled()
        expect(self.page.locator('#stop-reading')).to_be_disabled()
        expect(self.page.locator('#audio-status')).to_have_text('Reading stopped.')

    def test_complete_journey_visits_all_questions_and_four_chapter_pauses(self):
        self.page.locator('#full-mode').click()
        visited_questions = []
        pauses = 0
        for number in range(1, 31):
            chapter = (number - 1) // 6 + 1
            expect(self.page.locator('#progress-label')).to_have_text(
                f'Question {number} of 30 · Chapter {chapter} of 5'
            )
            expect(self.page.locator('#question-count')).to_have_text(
                f'Question {(number - 1) % 6 + 1} of 6'
            )
            question = self.page.locator('#chapter-question').inner_text().strip()
            self.assertTrue(question, 'Each journey step must present a question')
            visited_questions.append(question)
            self.page.locator('#reflection').fill(f'Temporary sample {number}')
            self.page.locator('#next' if number % 2 else '#skip').click()
            expect(self.page.locator('#reflection')).to_have_value('')
            expect(self.page.locator('#word-hint')).to_have_text(
                '0 words typed · No minimum or maximum'
            )
            if number % 6 == 0 and number < 30:
                pauses += 1
                expect(self.page.locator('#rest-screen')).to_be_visible()
                expect(self.page.locator('#rest-title')).to_have_text(
                    f'Chapter {chapter} complete'
                )
                expect(self.page.locator('#question-panel')).to_be_hidden()
                self.page.locator('#continue-chapter').click()
                expect(self.page.locator('#rest-screen')).to_be_hidden()
                expect(self.page.locator('#chapter-question')).to_be_focused()
        self.assertEqual(pauses, 4)
        self.assertEqual(len(set(visited_questions)), 30)
        expect(self.page.locator('#session-complete')).to_be_visible()
        expect(self.page.locator('#question-panel')).to_be_hidden()
        expect(self.page.locator('#completion-message')).to_contain_text(
            '30-question experience preview'
        )

    def test_preview_keeps_responses_off_network_and_out_of_browser_storage(self):
        origin = urlsplit(self.url)
        requests, external_requests, write_requests = [], [], []
        request_payloads, samples = [], []

        def record_request(request):
            target = urlsplit(request.url)
            requests.append((request.method, request.url))
            request_payloads.append(unquote_plus(request.url) + (request.post_data or ''))
            if target.scheme in ('http', 'https') and (
                target.scheme, target.netloc
            ) != (origin.scheme, origin.netloc):
                external_requests.append(request.url)
            if request.method not in ('GET', 'HEAD'):
                write_requests.append((request.method, request.url))

        def assert_no_saved_responses():
            self.assertEqual(self.page.evaluate('''() => ({
                local: localStorage.length,
                session: sessionStorage.length
            })'''), {'local': 0, 'session': 0})
            self.assertEqual(self.context.cookies(), [])

        def type_sample(text):
            samples.append(text)
            self.page.locator('#reflection').fill(text)
            assert_no_saved_responses()

        self.page.on('request', record_request)
        self.page.reload()
        expect(self.page.locator('#welcome')).to_be_visible()
        self.assertIn(('GET', self.url), requests, 'Initial document load must be observed')
        assert_no_saved_responses()
        self.navigate('The Journey')
        type_sample('Privacy full sample')
        self.page.locator('#next').click()
        expect(self.page.locator('#reflection')).to_have_value('')
        type_sample('Privacy mode switch sample')
        self.page.locator('#quick-mode').click()
        expect(self.page.locator('#reflection')).to_have_value('')
        type_sample('Privacy quick sample')
        self.page.locator('#next').click()
        expect(self.page.locator('#reflection')).to_have_value('')
        type_sample('Privacy full return sample')
        self.page.locator('#full-mode').click()
        expect(self.page.locator('#reflection')).to_have_value('')
        type_sample('Privacy view navigation sample')
        self.navigate('Welcome')
        self.navigate('The Journey')
        expect(self.page.locator('#reflection')).to_have_value('')
        type_sample('Privacy reload sample')
        self.page.reload()
        expect(self.page.locator('#welcome')).to_be_visible()
        self.navigate('The Journey')
        expect(self.page.locator('#reflection')).to_have_value('')
        expect(self.page.locator('#word-hint')).to_have_text(
            '0 words typed · No minimum or maximum'
        )
        assert_no_saved_responses()
        self.assertEqual(external_requests, [])
        self.assertEqual(write_requests, [])
        allowed_urls = {self.url, self.url + 'favicon.ico'}
        self.assertEqual([
            request for request in requests if request[1] not in allowed_urls
        ], [], 'This standalone preview must not make additional requests or send query data')
        self.assertFalse(any(
            sample in payload for sample in samples for payload in request_payloads
        ), 'Sample text must not be transmitted in request URLs or bodies')

    def test_keyboard_chapter_jump_focuses_only_the_requested_question(self):
        self.page.locator('#quick-mode').click()
        self.page.evaluate('''() => {
            window.focusedQuestions = [];
            document.getElementById('chapter-question').addEventListener('focusin', event => {
                window.focusedQuestions.push(event.target.textContent);
            });
        }''')
        chapter = self.page.locator('.chapter-chip').nth(3)
        chapter.focus()
        chapter.press('Enter')
        target = 'What gives life a sense of purpose?'
        expect(self.page.locator('#chapter-question')).to_have_text(target)
        expect(self.page.locator('#chapter-question')).to_be_focused()
        expect(self.page.locator('#progress-label')).to_have_text(
            'Question 19 of 30 · Chapter 4 of 5'
        )
        self.assertEqual(self.page.evaluate('window.focusedQuestions'), [target])

    def test_reselecting_current_session_mode_preserves_the_current_experience(self):
        for quick in (False, True):
            mode = self.page.locator('#quick-mode' if quick else '#full-mode')
            mode.click()
            for key in ('Enter', 'Space'):
                with self.subTest(quick=quick, key=key):
                    self.page.locator('#question-list button').nth(2 if quick else 3).click()
                    self.page.locator('#reflection').fill('Keep this mode sample')
                    if self.page.locator('#optional-prompt').is_hidden():
                        self.page.locator('#toggle-prompt').click()
                    progress = self.page.locator('#progress-label').inner_text()
                    mode.focus()
                    mode.press(key)
                    expect(self.page.locator('#progress-label')).to_have_text(progress)
                    expect(self.page.locator('#reflection')).to_have_value('Keep this mode sample')
                    expect(self.page.locator('#optional-prompt')).to_be_visible()
        self.page.locator('#full-mode').click()
        self.page.locator('.chapter-chip').nth(0).click()
        self.page.locator('#question-list button').nth(5).click()
        self.page.locator('#next').click()
        with self.subTest(state='chapter pause'):
            self.page.locator('#full-mode').press('Enter')
            expect(self.page.locator('#rest-screen')).to_be_visible()
            expect(self.page.locator('#question-panel')).to_be_hidden()
        for quick in (False, True):
            with self.subTest(state='completion', quick=quick):
                self.finish(quick)
                message = self.page.locator('#completion-message').inner_text()
                self.page.locator('#quick-mode' if quick else '#full-mode').press('Space')
                expect(self.page.locator('#session-complete')).to_be_visible()
                expect(self.page.locator('#completion-message')).to_have_text(message)
                expect(self.page.locator('#question-panel')).to_be_hidden()

    def test_mobile_200_percent_text_reflows_and_keeps_reading_start_visible(self):
        self.page.set_viewport_size({'width': 320, 'height': 740})
        self.page.locator('#large-type').check()
        # Snapshot first so inherited sizes are doubled once, rather than
        # compounding ancestor/descendant changes. This models text enlargement,
        # not a higher-resolution device screenshot or CSS zoom.
        self.page.evaluate('''() => {
            const originalSizes = Array.from(document.querySelectorAll('body, body *'),
                element => [element, parseFloat(getComputedStyle(element).fontSize)]);
            for (const [element, size] of originalSizes) {
                element.style.fontSize = `${size * 2}px`;
            }
        }''')

        def assert_no_horizontal_scroll():
            self.assertLessEqual(
                self.page.evaluate('document.documentElement.scrollWidth'), 320
            )

        def assert_reading_start_visible(selector):
            self.page.wait_for_function('''selector => {
                const bounds = document.querySelector(selector).getBoundingClientRect();
                return bounds.top >= 0 && bounds.top < window.innerHeight;
            }''', arg=selector)

        for view in ('Welcome', 'Before You Begin', 'The Journey'):
            with self.subTest(view=view):
                self.navigate(view)
                assert_no_horizontal_scroll()
        self.page.locator('.chapter-chip').nth(4).click()
        self.page.locator('#question-list button').nth(5).click()
        with self.subTest(view='long final question'):
            assert_no_horizontal_scroll()
            expect(self.page.locator('#chapter-question')).to_be_focused()
            assert_reading_start_visible('#chapter-question')
        self.page.locator('#next').click()
        with self.subTest(view='completion'):
            assert_no_horizontal_scroll()
            expect(self.page.locator('#session-complete')).to_be_focused()
            assert_reading_start_visible('#session-complete')
            assert_reading_start_visible('#completion-title')


if __name__ == '__main__':
    unittest.main()
