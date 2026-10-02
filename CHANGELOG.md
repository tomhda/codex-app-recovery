# Changelog

## 1.0.1 — 2026-10-02

- Enable the Resume and startup corrections on Codex 26.928.4866.0 (internal version 26.928.40906). Both app bugs are unchanged in that version, and the parts the corrections use were confirmed there. The first cold start after the update stopped on the logo again and opened once the initialization snapshot was requested.
- Fix **Check now** failing with `evaluate_failed`: it called a guard method that no longer exists.
- Fix the self-heal guard showing as "Starting" while the helper runs: the helper check locked the end of the lock file instead of byte 0.
- Guard 2.0.1, so a running window takes the new version list after deploying.
- Add tests for the guard methods the Python side calls and for detecting the helper's lock on a non-empty lock file.
- `--gui-smoke` no longer stops at the "already open" message when the recovery window is open.

## 1.0.0 — 2026-10-02

- Replace the symptom-by-symptom recovery buttons with one status window: Codex, self-heal guard and window state refresh every 5 seconds, and one main button (Start Codex / Restart with guard / Check now). Add **Reload window** and a list of recent automatic fixes.
- Add the self-heal guard (`guard.js` 2.0.0, `guard_daemon.py`). It watches the app's own message events and re-sends only an exact list of read requests whose reply never arrived (45 s app-server / 30 s internal, at most 3 times, as originally sent; replies go only to the same request generation and host; late original replies are dropped). On the verified app version it corrects Resume after an interrupt in app-server queues (once per chat at a time; restored when the guard stops) and asks for the initialization snapshot when a cold start misses it. Write requests are never re-sent or failed. The helper never reloads or restarts Codex.
- Add `recovery.py --launch` and the **Codex (guarded)** Start-menu entry. Quitting uses Codex's own quit request; forcing Codex to close needs its own confirmation and closes only the processes present at that point.
- Remove the query re-fetch engine, the queue recovery/reset tools and their tests; the guard covers these cases. Rename the chat tab to **Backup chat**.
- Add `scripts/deploy_local.py` for installing without a virtual environment, and `--status` / `--checkup` command-line options.
- Verified on Codex 26.928.3736.0: new send, follow-ups queued during a running turn, stop, delete, send now and Resume (Resume fails without the guard and works with it; a double click sends once), recovery of a lost queue read and internal reads, and cold starts that missed the initialization message and were corrected without reloading. An external review (GPT-6 Pro) of the first guard led to the 2.0.0 changes above.

## 0.5.0 — 2026-10-01

- Add an independent **Chat with Codex** tab using official app-server stdio and the existing login, with exact gpt-6.1-sol/high, streaming, follow-ups, interrupt, explicit retry, conversation restoration, and connection diagnostics.
- Start read-only with on-request/user approvals, verify the returned policy, display official approval/input requests, and reject persistent grants, unsupported permission requests, and new authentication flows.
- Persist receipt IDs before sending. Bound requests and inactive turns; retain unknown outcomes and reconcile before allowing retries. Handle native turn activation before interruption.
- Broaden read-only queue observations beyond the known orphaned-resume repair signature, show waiting/stalled counts, and report unverified follow-up health as unknown. Do not broaden automatic repair.
- Verify real initial/follow-up responses, interruption/retry, restart restoration, a read-only shell operation, and a dedicated child-process disconnect/reconciliation. Add stdio peer and Windows chat UI tests. No live desktop queues were changed during verification.

## 0.4.0 — 2026-09-30

- Add **Recover message queue** for follow-ups to finished local chats stuck behind orphaned resume promises and zero-timeout reads. Detect the same old queue and resume attempt twice, check fresh backend execution state and server queue, and save/read back private messages and drafts before any repair.
- Expire only stale read-only target history/queue requests and shared config/app reads through the app's timeout handler. Replace only the verified target resume attempts with existing permissions preserved, then reload the main renderer once to retire orphaned workers. Original messages use the app's normal submission path.
- Verify receipt by matching original client message IDs in backend history as well as an empty local queue. Refuse active chats, changed drafts/queues, unknown send outcomes, incompatible internals, or failed backup. Never repeat a possibly delivered reload or resume repair.
- Include queue diagnostics in **Check status only**, with read-only `--queue-check` and external `--repair-queue` options. Add English/Japanese UI and queue-engine/orchestration/GUI tests.
- The source procedure restored two affected chats on Codex 26.928.1915.0, including actual replies. The packaged adapter was checked against their original IDs, healthy live state, and isolated stalled-state tests; a fresh real-world recurrence through the finished GUI has not yet occurred.

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
