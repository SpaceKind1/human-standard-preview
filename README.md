# human-standard-preview
Human Standard Project — Public Participant Testing Preview

This standalone preview uses inline HTML, CSS, and JavaScript. It needs no build
step, package installation, API keys, or backend. Sample responses are discarded
when you leave a question; nothing is submitted or saved to browser storage.

## Run locally

For the simplest option, save `index.html` to your computer and open it with a
full browser such as Microsoft Edge, Chrome, Firefox, or Safari. Everything is
inside that one file. The app does not need installation or a server.

An archive viewer cannot run the preview. If you have a ZIP download, extract it
first, then open the extracted `index.html`. If a chat/file preview only shows
source code or an unsupported-preview message, save the HTML locally and open
the saved file in your browser instead.

For development over local HTTP, use Python 3.10 or newer. From the repository root:

```sh
python3 -m http.server 8000 --bind 127.0.0.1
```

On Windows, use `python` if `python3` is unavailable. Open the server's loopback
address on your own computer. This development command does not deploy the site.

The preview includes a full
30-question journey, a three-question quick reflection, optional prompts, larger
text, and optional read-aloud. Audio requires browser support and available
device voices. Stop cancels both queued and active reading. Browsers without
speech support keep the text experience available and disable audio controls.
The chapter introduction has its own nearby Stop control for small screens.
Questions expose their current journey position to screen readers; sample-text
guidance and chapter pause/completion messages are also described accessibly.

Use the numbered shortcuts beneath the chapter list to revisit any question in
the current chapter, or any of the three quick-reflection samples. Changing
questions clears sample text; selecting the current question keeps it intact.
At completion, you can restart, explore the full journey, or return to Welcome.
Sample text and narration are also cleared when leaving or returning through
browser history; browser form restoration must not bring an old response back.

## Browser regression checks

The prepared cloud environment already includes Python, Playwright, and Chromium.
To reproduce the test tools elsewhere, create a virtual environment with Python
3.10 or newer (CI uses 3.12):

```sh
python -m venv .venv
```

Activate it using `.\.venv\Scripts\Activate.ps1` in Windows PowerShell, or
`source .venv/bin/activate` on macOS/Linux. Then install the pinned test tools and
Playwright's Chromium:

```sh
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

Linux machines may also need browser system libraries; Playwright's supported
installer is `python -m playwright install --with-deps chromium`.

From the repository root, run:

```sh
python3 -m unittest discover -s tests -v
```

The tests start their own temporary HTTP server and browser. They check chapter
and completion transitions, sample-text clearing, mobile keyboard focus,
accessible descriptions, unsupported speech, and cancellation of queued and
automatic reading, plus numbered question navigation and completion actions.
Speech scheduling tests use a controlled browser speech
stub; they do not verify audible playback.

Tests use `PREVIEW_BROWSER_EXECUTABLE` when it is set to an executable browser
path, otherwise system `chromium`/`chromium-browser` when available, otherwise
Playwright's installed Chromium. Invalid overrides fail with an explanation.
The HTTP server and browser are cleaned up even when startup fails.

The Browser checks GitHub Actions workflow runs the same suite on Windows and
Linux for pushes to `main` and `codex/**` branches and for pull requests. It selects
Playwright's installed Chromium explicitly. The workflow only tests the preview;
it does not deploy or publish it.
