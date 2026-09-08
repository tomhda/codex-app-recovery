# Changelog

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
