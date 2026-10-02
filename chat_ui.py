"""Tk chat tab. Network/agent work never runs on the Tk event thread."""
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from chat_client import ChatSession, ChatError, MODEL, EFFORT
from i18n import tr


class ChatPanel(ttk.Frame):
    def __init__(self, parent, session=None):
        super().__init__(parent, padding=16)
        self.session = session or ChatSession()
        self.dialogs, self.alive, self.working = {}, True, False
        self.notices = []
        self.status = tk.StringVar(value=tr('未接続'))
        self.cwd = tk.StringVar(value=self.session.data['cwd'] or str(Path.cwd()))
        ttk.Label(self, text=tr('復旧アプリからCodexとチャット'), font=('Yu Gothic UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(self, text=tr('公式CLIの独立接続を使います。既存のデスクトップ送信キューは経由しません。'), wraplength=720).pack(anchor='w', pady=(4, 8))
        ttk.Label(self, text=f'{MODEL} / {EFFORT} · ' + tr('読み取り専用から開始・操作は公式の承認に従います'), foreground='#526078').pack(anchor='w')
        row = ttk.Frame(self)
        row.pack(fill='x', pady=8)
        ttk.Label(row, text=tr('作業フォルダ')).pack(side='left')
        self.folder = ttk.Entry(row, textvariable=self.cwd)
        self.folder.pack(side='left', fill='x', expand=True, padx=8)
        self.browse = ttk.Button(row, text=tr('選択'), command=self.choose_folder)
        self.browse.pack(side='right')
        toolbar = ttk.Frame(self)
        toolbar.pack(fill='x')
        self.connect_button = ttk.Button(toolbar, text=tr('接続・会話を復元'), command=lambda: self.work(self.session.connect))
        self.connect_button.pack(side='left')
        self.new_button = ttk.Button(toolbar, text=tr('新しい会話'), command=lambda: self.work(self.session.new_conversation))
        self.new_button.pack(side='left', padx=6)
        ttk.Button(toolbar, text=tr('接続診断'), command=self.diagnose).pack(side='right')
        self.state_label = ttk.Label(self, textvariable=self.status, wraplength=720)
        self.state_label.pack(anchor='w', pady=(8, 4))
        body = ttk.Frame(self)
        body.pack(fill='both', expand=True)
        self.output = tk.Text(body, wrap='word', height=14, font=('Yu Gothic UI', 10), state='disabled')
        scrollbar = ttk.Scrollbar(body, command=self.output.yview)
        self.output.configure(yscrollcommand=scrollbar.set)
        self.output.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        ttk.Label(self, text=tr('メッセージ（Ctrl+Enterで送信）')).pack(anchor='w', pady=(8, 2))
        self.input = tk.Text(self, height=4, wrap='word', font=('Yu Gothic UI', 10))
        self.input.pack(fill='x')
        self.input.bind('<Control-Return>', lambda _: (self.send(), 'break')[1])
        actions = ttk.Frame(self)
        actions.pack(fill='x', pady=(8, 0))
        self.send_button = ttk.Button(actions, text=tr('送信'), command=self.send)
        self.send_button.pack(side='right')
        self.stop_button = ttk.Button(actions, text=tr('停止'), command=lambda: self.work(self.session.stop, concurrent=True))
        self.stop_button.pack(side='right', padx=8)
        self.retry_button = ttk.Button(actions, text=tr('最後の入力を再送'), command=self.retry)
        self.retry_button.pack(side='left')
        ttk.Label(self, text=tr('再接続は再送しません。受信が不明な送信は照合が済むまで再送できません。'), wraplength=720, foreground='#555555').pack(anchor='w', pady=(8, 0))
        self.render()
        self.update_controls()
        self.timer = self.after(100, self.poll)

    @property
    def busy(self):
        return self.working or bool(self.session.data['pending'])

    def choose_folder(self):
        selected = filedialog.askdirectory(parent=self, initialdir=self.cwd.get())
        if selected:
            self.cwd.set(selected)

    def work(self, fn, concurrent=False):
        if self.working and not concurrent:
            return
        if not concurrent:
            self.working = True
        self.update_controls()
        def run():
            try:
                fn()
            except Exception as error:
                self.session.events.put({'type': 'ui_error', 'code': getattr(error, 'code', 'operation_failed')})
            finally:
                self.session.events.put({'type': 'worker_done', 'concurrent': concurrent})
        threading.Thread(target=run, daemon=True).start()

    def send(self):
        text = self.input.get('1.0', 'end-1c')
        if not text.strip():
            return
        if self.working or self.session.data['pending'] or not self.session.connected:
            return
        cwd = self.cwd.get()
        # Preserve the unsent editor contents until turn/start acknowledges receipt.
        def send():
            self.session.send(text, cwd)
            self.session.events.put({'type': 'input_accepted', 'text': text})
        self.work(send)

    def retry(self):
        if messagebox.askyesno(tr('最後の入力を再送'), tr('最後の入力を同じ会話へもう一度送信します。続けますか？'), parent=self):
            self.work(self.session.retry)

    def diagnose(self):
        self.append_notice(json.dumps(self.session.diagnostics(), ensure_ascii=False, indent=2))

    def append_notice(self, text):
        self.notices.append(text)
        self.notices = self.notices[-100:]
        self.render()

    def render(self):
        with self.session.lock:
            entries = list(self.session.data['messages'])
        text = '\n\n'.join((tr('あなた') if x['role'] == 'user' else 'Codex') + '\n' + x['text'] for x in entries)
        if self.notices:
            text += '\n\n' + '\n'.join(self.notices)
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.insert('1.0', text[-200000:])
        self.output.configure(state='disabled')
        self.output.see('end')

    def update_controls(self):
        state = self.session.state
        pending = bool(self.session.data['pending'])
        ready = not self.working and not pending and self.session.connected and state in ('idle', 'stopped', 'error')
        self.send_button.configure(state='normal' if ready else 'disabled')
        self.retry_button.configure(state='normal' if ready and self.session.data['messages'] else 'disabled')
        self.new_button.configure(state='normal' if not self.working and not pending else 'disabled')
        self.connect_button.configure(state='normal' if not self.working and state in ('disconnected', 'error', 'unknown', 'stopped', 'idle') else 'disabled')
        self.stop_button.configure(state='normal' if pending and self.session.connected and self.session.turn_id and state != 'stopping' else 'disabled')
        for widget in (self.folder, self.browse):
            widget.configure(state='disabled' if self.session.data['threadId'] or self.working else 'normal')
        labels = {'disconnected': tr('未接続'), 'connecting': tr('接続しています…'), 'idle': tr('送信できます'),
            'sending': tr('送信中・受信確認を待っています'), 'running': tr('実行中・応答を受信しています'),
            'waiting': tr('応答待ち'), 'approval': tr('承認・回答を待っています'), 'stopping': tr('停止を確認しています'),
            'stopped': tr('停止しました'), 'error': tr('エラー'), 'unknown': tr('受信・実行状態が不明です。接続診断と再接続で確認してください。')}
        seconds = self.session.diagnostics()['secondsSinceEvent']
        label = labels.get(state, state)
        if pending:
            label += tr('（最終イベントから {seconds} 秒）').format(seconds=seconds)
        if self.session.error:
            label += ' · ' + self.session.error
        self.status.set(label)

    def approval_dialog(self, event):
        request_id = event['id']
        if request_id not in self.session.approvals:
            return
        dialog = tk.Toplevel(self)
        dialog.title(tr('Codexからの承認・回答依頼'))
        dialog.geometry('760x600')
        self.dialogs[request_id] = dialog
        preview = tk.Text(dialog, wrap='word', height=20)
        preview.pack(fill='both', expand=True, padx=12, pady=12)
        preview.insert('1.0', event['preview'])
        preview.configure(state='disabled')
        request = self.session.approvals[request_id]
        answers = {}
        if request['method'] == 'item/tool/requestUserInput':
            for question in request['params'].get('questions', []):
                ttk.Label(dialog, text=question.get('question', ''), wraplength=720).pack(anchor='w', padx=12)
                value = tk.StringVar()
                options = [x['label'] for x in question.get('options', [])]
                if options:
                    ttk.Combobox(dialog, values=options, textvariable=value).pack(fill='x', padx=12, pady=4)
                else:
                    ttk.Entry(dialog, textvariable=value, show='*' if question.get('isSecret') else '').pack(fill='x', padx=12, pady=4)
                answers[question['id']] = value
        def reply(accept):
            result = {k: [v.get()] for k, v in answers.items()} if answers else None
            if answers and not accept:
                self.work(self.session.stop, concurrent=True)
            else:
                self.work(lambda: self.session.answer(request_id, accept, result), concurrent=True)
            self.dialogs.pop(request_id, None)
            dialog.destroy()
        row = ttk.Frame(dialog, padding=12)
        row.pack(fill='x')
        ttk.Button(row, text=tr('拒否・停止'), command=lambda: reply(False)).pack(side='left')
        ttk.Button(row, text=tr('今回だけ承認・回答'), command=lambda: reply(True)).pack(side='right')
        dialog.protocol('WM_DELETE_WINDOW', lambda: reply(False))

    def poll(self):
        if not self.alive:
            return
        dirty = False
        for _ in range(200):
            try:
                event = self.session.events.get_nowait()
            except queue.Empty:
                break
            kind = event['type']
            if kind in ('message', 'transcript'):
                dirty = True
            elif kind == 'worker_done' and not event.get('concurrent'):
                self.working = False
            elif kind == 'input_accepted' and self.input.get('1.0', 'end-1c') == event['text']:
                self.input.delete('1.0', 'end')
            elif kind == 'approval':
                self.approval_dialog(event)
            elif kind == 'approval_resolved':
                dialog = self.dialogs.pop(event['id'], None)
                if dialog:
                    dialog.destroy()
            elif kind in ('diagnostic', 'ui_error', 'tool'):
                self.append_notice(tr('状態通知') + ': ' + event.get('code', event.get('kind', '')) + ' ' + event.get('status', ''))
        if dirty:
            self.render()
        if not self.session.approvals:
            for dialog in list(self.dialogs.values()):
                dialog.destroy()
            self.dialogs.clear()
        self.update_controls()
        self.timer = self.after(100, self.poll)

    def shutdown(self):
        self.alive = False
        self.after_cancel(self.timer)
        # Closing preserves an unresolved receipt for reconciliation on next launch.
        threading.Thread(target=self.session.close, daemon=True).start()
