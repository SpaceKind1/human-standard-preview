# human-standard-preview
Human Standard Project — Public Participant Testing Preview

This standalone preview uses inline HTML, CSS, and JavaScript. It needs no build
step, package installation, API keys, or backend. Sample responses are discarded
when you leave a question; nothing is submitted or saved to browser storage.

## Run locally

From the repository root:

```sh
python3 -m http.server 8000 --bind 127.0.0.1
```

Open the served page in your local browser. The preview includes a full
30-question journey, a three-question quick reflection, optional prompts, larger
text, and optional read-aloud. Audio requires browser support and available
device voices. Stop cancels both queued and active reading. Browsers without
speech support keep the text experience available and disable audio controls.
Questions expose their current journey position to screen readers; sample-text
guidance and chapter pause/completion messages are also described accessibly.

Use the numbered shortcuts beneath the chapter list to revisit any question in
the current chapter, or any of the three quick-reflection samples. Changing
questions clears sample text; selecting the current question keeps it intact.
At completion, you can restart, explore the full journey, or return to Welcome.

## Browser regression checks

The prepared cloud environment includes Python, the Python Playwright package,
and Chromium. From the repository root, run:

```sh
python3 -m unittest discover -s tests -v
```

The tests start their own temporary HTTP server and browser. They check chapter
and completion transitions, sample-text clearing, mobile keyboard focus,
accessible descriptions, unsupported speech, and cancellation of queued and
automatic reading, plus numbered question navigation and completion actions.
Speech scheduling tests use a controlled browser speech
stub; they do not verify audible playback.
