# Codex App Recovery

**English** | [日本語](README.ja.md)

An **unofficial, experimental Windows recovery utility** for a blank/black Codex app window and stalled in-app browser / local automation capabilities. Both **English and Japanese** are supported throughout the app.

It runs **outside the Codex app**, so you can operate it while the app UI is unavailable. Neither Codex CLI nor WSL is required to run this utility.

[MIT License](LICENSE)

![English recovery window](docs/screenshot-en.png)

## Language

Use the **Language / 言語** selector at the top right to switch between English and Japanese. The selection is saved for the next launch. On first launch, a Japanese Windows display language selects Japanese; other display languages select English.

Buttons, explanations, progress, confirmation dialogs, results and app-defined errors follow your choice. The selector is disabled during recovery. Switching languages redraws the window and clears the displayed result; diagnostic logs are retained. Windows/package-manager error details may remain in their original language.

The choice is stored in `%LOCALAPPDATA%\CodexAppRecovery\settings.json`, separately from Codex settings. To override it for one launch without changing the saved choice:

```powershell
.\.venv\Scripts\python.exe recovery.py --lang en
.\.venv\Scripts\python.exe recovery.py --check --lang ja
```

Setup dialogs use the saved choice or Windows display language; `py -3 setup_recovery.py --lang en` overrides it for setup.

## Install

Requirements: Windows, the MSIX `OpenAI.Codex` app, and Python 3.10+ with Tcl/Tk. Python must be available through `py -3` or `python`.

1. Download and extract a ZIP from [Releases](https://github.com/tomhda/codex-app-recovery/releases).
2. Double-click **Setup.bat**. It creates a local `.venv` and installs `websocket-client`. Internet access is required during setup.
3. Optionally add Start menu and desktop shortcuts when prompted.
4. Open **Codex-Recovery.bat** or **Codex App Recovery** from Start.

Keep the folder in its installed location. If you move it, remove the old shortcuts and `.venv`, then run setup again. To pin the shortcut, search for it in Start, right-click, and choose **Pin to Start**.

## Controls

| Button (English / Japanese) | When to use it | Action |
|---|---|---|
| Try recovery / まず復旧を試す | Black screen or missing browser/automation capabilities | With a connection, cancel/refetch selected stalled reads. Without one, ask once before reopening Codex with diagnostics and continue the selected action |
| Reload screen / 画面を読み直す | The screen is still blank or broken | If connected, confirm once, reload the main page, then attempt recovery. Without one, ask once before reopening Codex and continue reload/recovery |
| Reopen and recover / Codexを開き直して復旧 | The diagnostic connection is unavailable or the app is closed | Confirm, terminate the current app process tree if necessary, launch with loopback debugging, then attempt recovery |
| Check status only / 状態だけ調べる | Inspect only | Read current state without recovery, reload or restart |

After a reload, the utility re-discovers the current main page and retries transient local diagnostic connection failures for a bounded period. A normal Codex launch without the diagnostic port requires one confirmation before the utility reopens Codex and continues the selected recovery or reload action; it never restarts silently.

Since v0.3.1, reopening uses Windows package activation instead of launching `ChatGPT.exe` directly, addressing the “process has no package identity” error seen after an app update. **Try recovery** also handles a persistent startup spinner: after repeated checks show an empty spinner screen with no editor and successfully loaded settings and local features, it reloads the main screen once. It does not force gateway/authentication readiness, clear data, or keep reloading. A visible or hidden editor prevents this automatic fallback; **Check status only** never reloads.

When a project chat has a composer but the model picker, effort picker, or context-usage indicator is missing, the status snapshot reports the missing controls. Only a stalled config dependency for the same local workspace or an observed local model-list query with subscribers is eligible in this visible degraded state. General preparation reads are limited to a blank screen; a healthy visible screen is left unchanged.

The shared recovery button does **not** imply a shared cause: browser and automation failures use a common feature-list query; blank-screen recovery additionally handles selected configuration and UI-preparation reads.

## Scope and limitations

### The feature-list error can be followed by delayed recovery

If **“Could not uniquely identify the feature-list client. Stopped without changes.”** appears, first wait about **30–60 seconds** and check the Codex window. A user reported on September 9, 2026 that the app recovered tens of seconds after this message.

If the screen returns, use **Check status only** and verify the browser and automation behavior. If it does not return, try **Try recovery** once more. Avoid repeated restarts just because this message appeared.

The message means that the tool could not identify a unique recovery target at that moment and stopped additional query repair. It does not establish that the app cannot recover, or undo an earlier reload/relaunch. The delay is an observation, not a proven cause or a guaranteed recovery time. v0.3.0 shows this guidance directly in the result area; it does not automatically wait or retry.

This is not an OpenAI product or a permanent fix. It depends on private app internals and may stop working after updates. State inspection and GUI operation have been checked on **Windows 11, Codex 26.901.6511.0 and 26.924.2738.0**. On September 26, package activation followed by a main-screen reload manually restored the latter build, with user confirmation. The updated utility passed Windows tests, GUI smoke tests, and read-only live inspection; its full restart-and-repair flow has not been rerun against the now-healthy app. Other builds are unverified; macOS, Linux and non-MSIX app installations are unsupported.

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
npm ci --ignore-scripts
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm test
.\.venv\Scripts\python.exe recovery.py --gui-smoke
.\.venv\Scripts\python.exe recovery.py --check
```

Node.js is only required for the mock JavaScript tests. CI tests do not terminate or manipulate a real Codex app. Include OS/app versions, symptoms, selected action and results when reporting an issue; do not upload private information.

MIT License. Not affiliated with or endorsed by OpenAI.
