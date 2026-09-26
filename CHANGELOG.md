# Changelog

## 0.3.1 — 2026-09-26

- Launch the installed Windows package through `IApplicationActivationManager`, preserving package identity. Resolve the application ID from its executable and compile the activation helper before closing Codex. This addresses the “process has no package identity” failure observed with direct executable launch in Codex 26.924.2738.0.
- If repeated observations show only an empty startup spinner, no editor (including hidden editors), and successfully loaded settings and local features, reload the main page once during recovery. Check-only mode remains read-only; explicit reload never triggers a second automatic reload.
- Observe the result after reconnecting, with a bounded wait and no reload loop. Leave authentication, configuration, and conversation files intact.
- Add spinner/draft detection, reload limits, changed-document guards, and Windows activation preflight tests. The activation and screen-reload sequence was confirmed manually on the affected machine; automated destructive relaunch of a healthy live app is not part of the tests.

## 0.3.0 — 2026-09-15

- Re-discover the current Codex main page and retry transient local diagnostic connection failures after reload, while stopping immediately for a foreign or non-loopback listener.
- Report missing model, effort, and context-usage controls on a visible project-chat screen and recover only same-workspace config dependencies or subscribed local model reads in that degraded state. General preparation reads remain limited to blank-screen recovery.
- Ask once before reopening Codex when the diagnostic listener is unavailable, and preserve the selected recovery mode.


## 0.2.1 — 2026-09-09

- Explain that the feature-list identification error may be followed by delayed app recovery, based on a user report.
- Show a 30–60 second wait-and-check suggestion for that error instead of generic restart guidance, in English and Japanese.
- No automatic retry or changes to recovery behavior; the delay is not guaranteed.

## 0.2.0 — 2026-09-08

- English and Japanese UI: actions, instructions, progress, confirmations, results and app-defined errors.
- Saved language selector, Windows display-language detection and one-launch `--lang` override.
- English default README and full Japanese README, with screenshots in both languages.
- Setup confirmation dialogs follow the selected language.
- Localization coverage and preference tests; GUI smoke tests in both languages.

Recovery scope and experimental limitations are unchanged.

## 0.1.0 — 2026-09-08

- Independent Windows recovery window with symptom-based actions.
- Targeted recovery of stalled browser/automation feature reads and blank-screen preparation reads.
- Main-page reload and confirmed diagnostic relaunch.
- Portable setup, isolated Python environment, optional Start/desktop shortcuts.
- Local diagnostic logs with query arguments and error details removed.
- Python and JavaScript tests, Windows/Linux CI.

Experimental initial release. Fresh real-world recurrence recovery and the terminating relaunch path still require end-to-end validation.
