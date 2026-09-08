# Codex App Recovery

An **unofficial, experimental Windows recovery utility** for a blank/black Codex app window and stalled in-app browser / local automation capabilities. The UI is currently Japanese.

It runs **outside the Codex app**, so you can operate it while the app UI is unavailable. Neither Codex CLI nor WSL is required to run this utility.

[日本語](README.md) · [MIT License](LICENSE)

## Install

Requirements: Windows, the MSIX `OpenAI.Codex` app, and Python 3.10+ with Tcl/Tk. Python must be available through `py -3` or `python`.

1. Download and extract a ZIP from [Releases](https://github.com/tomhda/codex-app-recovery/releases).
2. Double-click **Setup.bat**. It creates a local `.venv` and installs `websocket-client`. Internet access is required during setup.
3. Optionally add Start menu and desktop shortcuts when prompted.
4. Open **Codex-Recovery.bat** or **Codex App Recovery** from Start.

Keep the folder in its installed location. If you move it, remove the old shortcuts and `.venv`, then run setup again. To pin the shortcut, search for it in Start, right-click, and choose **Pin to Start**.

## Controls

| Japanese label | When to use it | Action |
|---|---|---|
| まず復旧を試す | Black screen or missing browser/automation capabilities | Cancel/refetch selected stalled reads without closing the app |
| 画面を読み直す | The screen is still blank or broken | Confirm, reload the main page, then attempt recovery; save unsent text first |
| Codexを開き直して復旧 | The diagnostic connection is unavailable or the app is closed | Confirm, terminate the current app process tree if necessary, launch with loopback debugging, then attempt recovery |
| 状態だけ調べる | Inspect only | Read current state without recovery, reload or restart |

The shared recovery button does **not** imply a shared cause: browser and automation failures use a common feature-list query; blank-screen recovery additionally handles selected configuration and UI-preparation reads.

## Scope and limitations

This is not an OpenAI product or a permanent fix. It depends on private app internals and may stop working after updates. State inspection and GUI operation have been checked on **Windows 11, Codex 26.901.6511.0**. Other builds are unverified; macOS, Linux and non-MSIX app installations are unsupported.

The original manual recovery restored a black window **from an external Codex CLI session**, through an existing diagnostic connection, without restarting the app. Manual feature-list recovery also restored browser/automation capabilities and an actual scheduled run. Recurrence in another app process was observed. The packaged utility has passed mock recovery tests and real-app inspection, but **recovery of a fresh real black-screen recurrence and its app-termination/relaunch path have not been end-to-end tested**.

Cancelling a stuck configuration read can let the app render with fallback defaults. A restored screen does not mean all settings were loaded. If partial settings are reported, verify your model, permissions and workspace before important operations. Enabled capability flags do not prove browsing or scheduled execution; check both in the app.

Only known reads that remain pending/fetching across observations are eligible. Five seconds is a heuristic, not proof of a hang. Use recovery when symptoms are present. The tool does not edit authentication, history, automation definitions, permission files or app binaries. Recovering capabilities may allow overdue automations to resume.

## Debugging connection and privacy

If necessary, the tool starts the current MSIX executable with:

```text
--remote-debugging-address=127.0.0.1 --remote-debugging-port=9222
```

Closing the app interrupts its running tasks. The UI requests confirmation first. Builds that do not expose debugging or whose query client cannot be identified are not repaired.

**Never expose port 9222 to a network.** CDP can control the signed-in app. The tool checks that the listener belongs to the current Codex executable and is loopback-only. The endpoint remains available until that app process exits. A normal launch may require diagnostic preparation again.

No telemetry or diagnostic uploads are implemented. The app itself performs normal requests during refetch/recovery. Local logs under `%LOCALAPPDATA%\CodexAppRecovery\logs` omit query arguments and error details; they contain operational states, not credentials, settings bodies, conversation content, page text or screenshots. Review logs before attaching them to an issue.

## Development

```powershell
py -3 setup_recovery.py --no-shortcuts
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/test_engine.cjs
.\.venv\Scripts\python.exe recovery.py --gui-smoke
.\.venv\Scripts\python.exe recovery.py --check
```

Node.js is only required for the mock JavaScript tests. CI tests do not terminate or manipulate a real Codex app. Include OS/app versions, symptoms, selected action and results when reporting an issue; do not upload private information.

MIT License. Not affiliated with or endorsed by OpenAI.
