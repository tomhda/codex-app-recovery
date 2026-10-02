"""Codex Recovery: start Codex with the self-heal guard and see what it fixed."""
from __future__ import annotations

import argparse
import concurrent.futures
import queue
import sys

import codex_control as control
import guard_events
from i18n import tr, get_language, set_language, resolve_language, save_language

APP_VERSION = '1.0.0'
REFRESH_MS = 5000


def error_text(error: Exception) -> str:
    code = getattr(error, 'code', '')
    messages = {
        'package_missing': 'Codexアプリが見つかりません。Microsoft StoreでChatGPTをインストールしてください。',
        'port_in_use': '診断用のポート9222を別のプログラムが使っています。そのプログラムを終了してから、もう一度お試しください。',
        'port_not_ready': 'Codexは起動しましたが、ガードを接続できませんでした。もう一度「Codexを起動」を押してください。',
        'quit_needs_force': 'Codexを終了できませんでした。通知領域のCodexアイコンから終了してから、もう一度お試しください。',
        'quit_failed': 'Codexを終了できませんでした。通知領域のCodexアイコンから終了してから、もう一度お試しください。',
        'not_running': 'Codexが起動していません。「Codexを起動」を押してください。',
        'no_port': 'Codexがガードなしで起動しています。「ガード付きで開き直す」を押してください。',
        'main_page_missing': 'Codexのメイン画面が見つかりません。少し待ってから、もう一度お試しください。',
        'main_page_ambiguous': 'Codexのメイン画面を特定できません。少し待ってから、もう一度お試しください。',
        'quit_declined': '開き直しを取りやめました。',
    }
    if code in messages:
        return tr(messages[code])
    return tr('操作を完了できませんでした。') + f'\n({type(error).__name__}: {str(error)[:200]})'


def progress_text(step: str) -> str:
    return tr({
        'starting': 'Codexをガード付きで起動しています…',
        'quit_requested': 'Codexを終了しています…',
        'force_quit': 'Codexが応答しないため、強制的に終了しています…',
        'checking': '画面とガードを点検しています…',
        'reloaded': '画面を読み直しました。表示を待っています…',
    }.get(step, '処理しています…'))


def describe_overview(info: dict) -> dict:
    """Status rows and the primary action for the current state."""
    if not info.get('installed'):
        return {'codex': tr('見つかりません'), 'guard': '—', 'screen': '—', 'action': None}
    if not info['running']:
        return {'codex': tr('起動していません'), 'guard': '—', 'screen': '—', 'action': 'launch'}
    codex = tr('起動中')
    if info.get('portForeign'):
        return {'codex': codex, 'guard': tr('使えません（ポート9222が他のプログラムに使われています）'), 'screen': '—', 'action': None}
    if not info['port']:
        return {'codex': codex, 'guard': tr('無効（ガードなしで起動しています）'), 'screen': '—', 'action': 'restart'}
    page = info.get('page') or {}
    guard_on = bool(page.get('guard')) and info.get('daemon')
    guard = tr('有効') if guard_on else tr('準備中（「今すぐ点検」で有効にします）')
    if not page:
        screen = tr('確認できません')
    elif page.get('blank'):
        screen = tr('起動画面のまま（{seconds}秒）').format(seconds=page.get('ageMs', 0) // 1000)
    else:
        screen = tr('表示中')
    return {'codex': codex, 'guard': guard, 'screen': screen, 'action': 'checkup'}


def checkup_text(summary: dict) -> str:
    status = summary.get('status') or {}
    guard = status.get('guard') or {}
    lines = [tr('点検が終わりました。')]
    lines.append(tr('・ガード：有効') + (tr('（常駐プロセスを起動しました）') if summary.get('daemonStarted') else ''))
    if summary.get('reloaded'):
        lines.append(tr('・画面：起動画面のまま止まっていたため、読み直しました'))
    lines.append(tr('・画面：起動画面のまま止まっています') if status.get('blank') else tr('・画面：表示中'))
    waiting = guard.get('pendingMcp', 0) + guard.get('pendingFetch', 0)
    lines.append(tr('・応答待ち：{count}件（届かない応答はガードが自動で取り直します）').format(count=waiting) if waiting else tr('・応答待ち：なし'))
    return '\n'.join(lines)


# --- Window ---------------------------------------------------------------------

def gui(smoke_test=False, smoke_ms=1500):
    while _gui_once(smoke_test, smoke_ms):
        pass


def _gui_once(smoke_test=False, smoke_ms=1500):
    import tkinter as tk
    from tkinter import messagebox, ttk
    from chat_ui import ChatPanel

    app = tk.Tk()
    app.title(tr('Codex 復旧') + ' v' + APP_VERSION)
    app.geometry('760x720')
    app.minsize(700, 640)
    style = ttk.Style()
    style.theme_use('vista')
    style.configure('TButton', font=('Yu Gothic UI', 11), padding=(12, 8))
    style.configure('Primary.TButton', font=('Yu Gothic UI', 12, 'bold'), padding=(18, 10))
    style.configure('TLabel', font=('Yu Gothic UI', 11))
    notebook = ttk.Notebook(app)
    notebook.pack(fill='both', expand=True)
    frame = ttk.Frame(notebook, padding=24)
    notebook.add(frame, text=tr('状態と修復'))
    chat = ChatPanel(notebook)
    notebook.add(chat, text=tr('予備チャット'))

    header = ttk.Frame(frame)
    header.pack(fill='x')
    ttk.Label(header, text=tr('Codex 復旧'), font=('Yu Gothic UI', 20, 'bold')).pack(side='left')
    language = ttk.Combobox(header, values=('日本語', 'English'), state='readonly', width=10)
    language.set('日本語' if get_language() == 'ja' else 'English')
    language.pack(side='right')
    ttk.Label(header, text='Language / 言語', font=('Yu Gothic UI', 9), padding=(0, 0, 8, 0)).pack(side='right')

    status_box = ttk.Frame(frame, padding=(14, 12), relief='solid', borderwidth=1)
    status_box.pack(fill='x', pady=(14, 12))
    status_box.columnconfigure(1, weight=1)
    rows = {}
    for row, (key, title) in enumerate((('codex', 'Codex'), ('guard', '自己修復ガード'), ('screen', '画面'), ('today', '今日の自動修復'))):
        ttk.Label(status_box, text=tr(title), foreground='#526078').grid(row=row, column=0, sticky='w', padx=(0, 18), pady=2)
        var = tk.StringVar(value='…')
        ttk.Label(status_box, textvariable=var, font=('Yu Gothic UI', 11, 'bold'), wraplength=470).grid(row=row, column=1, sticky='w', pady=2)
        rows[key] = var

    actions = ttk.Frame(frame)
    actions.pack(fill='x')
    primary = ttk.Button(actions, text=tr('状態を確認しています…'), style='Primary.TButton', state='disabled')
    primary.pack(side='left')
    reload_button = ttk.Button(actions, text=tr('画面を読み直す'), state='disabled')
    reload_button.pack(side='right')

    output = tk.Text(frame, height=6, wrap='word', font=('Yu Gothic UI', 10), relief='flat', padx=12, pady=10, background='#f3f4f6')
    output.pack(fill='x', pady=(12, 12))

    ttk.Label(frame, text=tr('最近の自動修復'), font=('Yu Gothic UI', 11, 'bold')).pack(anchor='w')
    history = tk.Text(frame, height=9, wrap='word', font=('Yu Gothic UI', 10), relief='flat', padx=12, pady=8, background='#fafafa')
    history.pack(fill='both', expand=True, pady=(6, 8))
    ttk.Label(frame, text=tr('普段はスタートメニューの「Codex（ガード付き）」から起動してください。通常のChatGPTアイコンから起動するとガードは働きません。'),
              foreground='#555555', font=('Yu Gothic UI', 9), wraplength=680).pack(anchor='w')

    def set_text(widget, text):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', text)
        widget.configure(state='disabled')

    set_text(output, tr('ここに操作の結果を表示します。'))
    messages: queue.Queue = queue.Queue()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    state = {'busy': False, 'action': None, 'refreshing': False, 'restart': False, 'timer': None, 'closed': False}

    def ask(title, text):
        """Ask on the UI thread from a worker and wait for the answer."""
        reply: queue.Queue = queue.Queue()
        messages.put(('ask', (title, text, reply)))
        return reply.get()

    def refresh():
        if state['refreshing'] or state['closed']:
            return
        state['refreshing'] = True

        def work():
            try:
                info = control.overview()
                described = describe_overview(info)
            except Exception:
                described = {'codex': tr('確認できません'), 'guard': '—', 'screen': '—', 'action': None}
            try:
                events = guard_events.recent(limit=30)
                today = guard_events.count_today()
            except Exception:
                events, today = [], 0
            messages.put(('overview', (described, events, today)))
        pool.submit(work)

    def run(kind):
        if state['busy']:
            return
        if kind == 'restart' and not messagebox.askyesno(tr('ガード付きで開き直す'), tr('Codexをいったん終了して、ガード付きで起動し直します。\n実行中の作業は中断されます。入力中の文章を控え、作業の区切りを確認してから続けてください。\n\n続けますか？'), parent=app):
            return
        if kind == 'reload' and not messagebox.askyesno(tr('画面を読み直す'), tr('Codexの画面を読み直します。実行中の作業は続きますが、入力中の未送信の文章は消えることがあります。\n\n続けますか？'), parent=app):
            return
        state['busy'] = True
        primary.configure(state='disabled')
        reload_button.configure(state='disabled')
        language.configure(state='disabled')
        report = lambda step: messages.put(('progress', progress_text(step)))

        def work():
            try:
                if kind in ('launch', 'restart'):
                    confirm = (lambda: True) if kind == 'restart' else (lambda: ask(tr('ガード付きで開き直す'), tr('Codexがガードなしで起動しています。いったん終了して、ガード付きで起動し直しますか？実行中の作業は中断されます。')))
                    force = lambda: ask(tr('強制終了の確認'), tr('Codexが終了の要求に応答しません。強制的に終了すると、未保存の作業や実行中の処理が失われることがあります。\n\n強制的に終了して、ガード付きで起動し直しますか？'))
                    result = control.launch(report, confirm_restart=confirm, confirm_force=force)
                    if result == 'declined':
                        messages.put(('done', tr('開き直しを取りやめました。')))
                        return
                    text = tr('Codexをガード付きで起動しました。') if result == 'started' else tr('Codexはガード付きで起動しています。')
                elif kind == 'reload':
                    control.reload_main(report)
                    text = tr('画面を読み直しました。')
                else:
                    summary = control.checkup(report, confirm_reload=lambda: ask(tr('画面を読み直す'), tr('Codexが起動画面のまま止まっています。画面を一度読み直しますか？')))
                    text = checkup_text(summary)
            except Exception as error:
                text = error_text(error)
            messages.put(('done', text))
        pool.submit(work)

    def on_primary():
        if state['action']:
            run(state['action'])

    primary.configure(command=on_primary)
    reload_button.configure(command=lambda: run('reload'))
    action_labels = {'launch': 'Codexを起動', 'restart': 'ガード付きで開き直す', 'checkup': '今すぐ点検'}

    def poll():
        while True:
            try:
                event, payload = messages.get_nowait()
            except queue.Empty:
                break
            if event == 'overview':
                state['refreshing'] = False
                described, events, today = payload
                for key in ('codex', 'guard', 'screen'):
                    rows[key].set(described[key])
                rows['today'].set(tr('{count}件').format(count=today))
                set_text(history, '\n'.join(f'{when:%m/%d %H:%M}  {text}' for when, text in events) or tr('まだありません。'))
                state['action'] = described['action']
                if not state['busy']:
                    action = described['action']
                    primary.configure(text=tr(action_labels.get(action, '操作できません')), state='normal' if action else 'disabled')
                    reload_button.configure(state='normal' if action == 'checkup' else 'disabled')
            elif event == 'ask':
                title, text, reply = payload
                reply.put(messagebox.askyesno(title, text, parent=app))
            elif event == 'progress':
                set_text(output, payload)
            elif event == 'done':
                set_text(output, payload)
                state['busy'] = False
                language.configure(state='readonly')
                refresh()
        state['timer'] = app.after(100, poll)

    def tick():
        refresh()
        state['refresh_timer'] = app.after(REFRESH_MS, tick)

    def close():
        if state['busy']:
            messagebox.showinfo(tr('Codex 復旧'), tr('処理が終わるまで、このウィンドウを開いておいてください。'), parent=app)
            return
        if chat.busy and not smoke_test:
            if not messagebox.askyesno(tr('予備チャット'), tr('独立チャット接続を閉じます。未確認の送信状態は保存し、次回接続時に照合します。実行中なら先に「停止」を使ってください。終了しますか？'), parent=app):
                return
        state['closed'] = True
        chat.shutdown()
        pool.shutdown(wait=False, cancel_futures=True)
        for timer in (state.get('timer'), state.get('refresh_timer')):
            if timer:
                app.after_cancel(timer)
        app.destroy()

    def change_language(_event):
        selected = 'ja' if language.get() == '日本語' else 'en'
        if state['busy'] or chat.busy or selected == get_language():
            return
        try:
            save_language(selected)
        except OSError:
            messagebox.showerror(tr('Codex 復旧'), tr('言語を保存できませんでした。'), parent=app)
            language.set('日本語' if get_language() == 'ja' else 'English')
            return
        set_language(selected)
        state['restart'] = True
        close()

    app.protocol('WM_DELETE_WINDOW', close)
    language.bind('<<ComboboxSelected>>', change_language)
    poll()
    tick()
    if smoke_test:
        app.after(smoke_ms, close)
    app.mainloop()
    return state['restart']


# --- Command line ---------------------------------------------------------------

def launch_from_shortcut() -> int:
    """Entry for the 'Codex (guarded)' shortcut: no window unless a question is needed."""
    import ctypes
    import tkinter
    from tkinter import messagebox
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    mutex = kernel.CreateMutexW(None, False, 'Local\\CodexGuardedLaunch')
    if mutex and ctypes.get_last_error() == 183:
        return 0  # another launch is already in progress

    def ask(title, text):
        root = tkinter.Tk()
        root.withdraw()
        try:
            return messagebox.askyesno(title, text)
        finally:
            root.destroy()

    def confirm_restart():
        return ask(tr('Codex（ガード付き）'), tr('Codexは自己修復ガードなしで起動しています。\n\nガードを付けるには、Codexをいったん終了して起動し直します。実行中の作業がある場合は「いいえ」を選び、区切りがついてから開き直してください。\n\n今すぐ開き直しますか？'))

    def confirm_force():
        return ask(tr('強制終了の確認'), tr('Codexが終了の要求に応答しません。強制的に終了すると、未保存の作業や実行中の処理が失われることがあります。\n\n強制的に終了して、ガード付きで起動し直しますか？'))
    try:
        control.launch(confirm_restart=confirm_restart, confirm_force=confirm_force)
        return 0
    except Exception as error:
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(tr('Codex（ガード付き）'), error_text(error))
        root.destroy()
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Codex Recovery')
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument('--launch', action='store_true', help='Start Codex with the self-heal guard (or bring it forward).')
    operation.add_argument('--status', action='store_true', help='Print the current state; never changes anything.')
    operation.add_argument('--checkup', action='store_true', help='Make sure the guard runs; never reloads without a window.')
    parser.add_argument('--gui-smoke', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--version', action='version', version=APP_VERSION)
    parser.add_argument('--lang', choices=('ja', 'en'), help='Display language for this launch (does not change the saved choice).')
    args = parser.parse_args()
    set_language(resolve_language(args.lang))
    if sys.platform != 'win32':
        parser.exit(1, 'Codex Recovery supports Windows only.\n')
    if args.launch:
        return launch_from_shortcut()
    if args.status or args.checkup:
        sys.stdout.reconfigure(encoding='utf-8')
        try:
            if args.status:
                described = describe_overview(control.overview())
                print(f"Codex: {described['codex']}\n{tr('自己修復ガード')}: {described['guard']}\n{tr('画面')}: {described['screen']}")
                for when, text in guard_events.recent(limit=10):
                    print(f'{when:%m/%d %H:%M}  {text}')
            else:
                print(checkup_text(control.checkup(lambda step: print(progress_text(step)))))
            return 0
        except Exception as error:
            print(error_text(error))
            return 1
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    mutex = kernel.CreateMutexW(None, False, 'Local\\CodexAppRecoveryTool')
    if not mutex:
        raise OSError('Could not create recovery lock')
    if ctypes.get_last_error() == 183:
        ctypes.windll.user32.MessageBoxW(None, tr('復旧ウィンドウは既に開いています。タスクバーから開いてください。'), tr('Codex 復旧'), 0)
        return 0
    gui(smoke_test=args.gui_smoke)
    return 0


if __name__ == '__main__':
    sys.exit(main())
