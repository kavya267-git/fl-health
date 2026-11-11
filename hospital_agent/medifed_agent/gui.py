"""The MediFed Hospital Agent window (tkinter, part of Python's standard library)."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__
from .session import AgentError, AgentSession
from .settings import load_settings, load_token, save_settings, save_token, token_storage

LABELS = {"ehr": "EHR", "ecg": "ECG", "xray": "X-ray"}
BRAND = "#24489a"


class AgentWindow:
    def __init__(self, root: tk.Tk, default_server: str):
        self.root = root
        self.messages: "queue.Queue[tuple]" = queue.Queue()
        self.session = AgentSession(log=lambda line: self.messages.put(("log", line)))
        saved = load_settings()
        server = saved.get("server") or default_server

        root.title("MediFed Hospital Agent")
        root.minsize(760, 640)
        style = ttk.Style(root)
        try:
            style.theme_use("vista" if "vista" in style.theme_names() else "clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"), foreground=BRAND)
        style.configure("Muted.TLabel", foreground="#5b6478")
        style.configure("Sim.TLabel", foreground="#8a5a00", font=("Segoe UI", 9, "bold"))

        outer = ttk.Frame(root, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="MediFed Hospital Agent", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Trains on your hospital's data on this computer. Only model updates, counts and summary metrics "
            "are sent to the server; your records stay here.",
            style="Muted.TLabel",
            wraplength=700,
        ).pack(anchor="w", pady=(2, 12))

        form = ttk.Frame(outer)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Server").grid(row=0, column=0, sticky="w", pady=4)
        self.server = tk.StringVar(value=server)
        ttk.Entry(form, textvariable=self.server).grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)

        ttk.Label(form, text="Node token").grid(row=1, column=0, sticky="w", pady=4)
        self.token = tk.StringVar(value=load_token(server) or "")
        ttk.Entry(form, textvariable=self.token, show="•").grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(form, text="Check token", command=self.check_token).grid(row=1, column=2, padx=(8, 0), pady=4)

        ttk.Label(form, text="Hospital").grid(row=2, column=0, sticky="w", pady=4)
        self.hospital = tk.StringVar(value=saved.get("hospital_name") or "Not checked yet")
        ttk.Label(form, textvariable=self.hospital).grid(row=2, column=1, sticky="w", pady=4)
        self.hospital_id = saved.get("hospital_id") or ""

        ttk.Label(form, text="Data folder").grid(row=3, column=0, sticky="w", pady=4)
        self.folder = tk.StringVar(value=saved.get("data_dir") or "")
        ttk.Entry(form, textvariable=self.folder, state="readonly").grid(row=3, column=1, sticky="ew", pady=4)
        buttons = ttk.Frame(form)
        buttons.grid(row=3, column=2, padx=(8, 0), pady=4)
        ttk.Button(buttons, text="Choose data folder…", command=self.choose_folder).pack(side="left")
        self.sample_note = ttk.Label(form, text="", style="Sim.TLabel")
        self.sample_note.grid(row=4, column=1, sticky="w")
        ttk.Button(form, text="Use sample data (SIMULATED)", command=self.use_sample).grid(row=4, column=2, padx=(8, 0), pady=4)
        self._update_sample_note()

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(12, 6))
        ttk.Button(actions, text="Check data", command=self.check_data).pack(side="left")
        self.connect_button = ttk.Button(actions, text="Connect", command=self.connect)
        self.connect_button.pack(side="left", padx=8)
        self.disconnect_button = ttk.Button(actions, text="Disconnect", command=self.disconnect, state="disabled")
        self.disconnect_button.pack(side="left")
        self.take_part = tk.BooleanVar(value=saved.get("take_part", True))
        ttk.Checkbutton(actions, text="Take part in rounds", variable=self.take_part, command=self.toggle_take_part).pack(
            side="left", padx=16
        )
        self.status = tk.StringVar(value="Not connected")
        ttk.Label(actions, textvariable=self.status, style="Muted.TLabel").pack(side="right")

        self.checks = ttk.Treeview(outer, columns=("result", "train", "val", "notes"), height=3)
        self.checks.heading("#0", text="Data")
        self.checks.heading("result", text="Check")
        self.checks.heading("train", text="Training records")
        self.checks.heading("val", text="Held-out records")
        self.checks.heading("notes", text="Notes")
        self.checks.column("#0", width=80, stretch=False)
        self.checks.column("result", width=80, stretch=False)
        self.checks.column("train", width=120, anchor="e", stretch=False)
        self.checks.column("val", width=120, anchor="e", stretch=False)
        self.checks.pack(fill="x", pady=(6, 10))

        ttk.Label(outer, text="Activity").pack(anchor="w")
        self.log_box = ScrolledText(outer, height=14, state="disabled", font=("Consolas", 9), wrap="word")
        self.log_box.pack(fill="both", expand=True)
        ttk.Label(outer, text=f"MediFed Hospital Agent {__version__} · token kept in {token_storage()}", style="Muted.TLabel").pack(
            anchor="w", pady=(6, 0)
        )
        self.root.after(150, self._drain)
        root.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------- helpers
    def _log(self, line: str) -> None:
        self.messages.put(("log", f"{datetime.now():%H:%M:%S} {line}"))

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", payload + "\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        self.root.after(150, self._drain)

    def _in_background(self, work, done) -> None:
        def run() -> None:
            try:
                result = work()
                self.messages.put(("call", lambda: done(result, None)))
            except Exception as exc:  # noqa: BLE001 - shown to the operator
                failure = exc  # bound now: Python clears `exc` when the except block ends
                self.messages.put(("call", lambda: done(None, failure)))

        threading.Thread(target=run, daemon=True).start()

    def _save(self) -> None:
        save_settings(
            {
                "server": self.server.get().strip().rstrip("/"),
                "hospital_id": self.hospital_id,
                "hospital_name": self.hospital.get() if self.hospital_id else None,
                "data_dir": self.folder.get(),
                "take_part": self.take_part.get(),
            }
        )

    def _update_sample_note(self) -> None:
        folder = self.folder.get()
        simulated = "sample-data" in Path(folder).parts if folder else False
        self.sample_note.configure(text="SIMULATED sample data: fictional records, for trying the agent" if simulated else "")

    # ------------------------------------------------------------- actions
    def check_token(self, then=None) -> None:
        server, token = self.server.get(), self.token.get()
        self._log("checking the token with the server…")

        def done(profile, error):
            if error:
                self.hospital.set("Not checked")
                self.hospital_id = ""
                self._log(f"token: {error}")
                messagebox.showerror("Node token", str(error))
                return
            self.hospital_id = profile["hospital_id"]
            names = ", ".join(LABELS.get(m, m) for m in profile.get("declared_modalities") or [])
            self.hospital.set(f"{profile['name']} ({profile['hospital_id']}) · {names}")
            where = save_token(server.strip().rstrip("/"), token.strip())
            self._log(f"token accepted for {profile['name']}; kept in {where}")
            self._save()
            if then:
                then()

        self._in_background(lambda: self.session.identify(server, token), done)

    def choose_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Choose your prepared data folder")
        if chosen:
            self.folder.set(chosen)
            self._update_sample_note()
            self._save()

    def use_sample(self) -> None:
        def make():
            if not self.session.profile:
                raise AgentError("Check the token first, so the sample data matches your hospital.")
            return self.session.make_sample_data()

        def done(folder, error):
            if error:
                messagebox.showerror("Sample data", str(error))
                return
            self.folder.set(str(folder))
            self._update_sample_note()
            self._save()
            self._log(f"SIMULATED sample data written to {folder} (fictional records)")

        self._log("creating SIMULATED sample data…")
        self._in_background(make, done)

    def check_data(self) -> None:
        folder = self.folder.get()
        if not folder:
            messagebox.showinfo("Check data", "Choose a data folder, or use sample data, first.")
            return

        def done(results, error):
            self.checks.delete(*self.checks.get_children())
            if error:
                messagebox.showerror("Check data", str(error))
                return
            for modality, result in results.items():
                verdict = "Passed" if result["passed"] else "Failed"
                notes = "; ".join(result["problems"]) or ", ".join(f"{k} {v}" for k, v in result["label_counts"].items())
                self.checks.insert(
                    "", "end", text=LABELS.get(modality, modality),
                    values=(verdict, result["train_records"], result["val_records"], notes),
                )
                self._log(f"data check {LABELS.get(modality, modality)}: {verdict.lower()} ({result['train_records']} train / {result['val_records']} held-out), on this computer only")

        self._in_background(lambda: self.session.check_data(Path(folder)), done)

    def connect(self) -> None:
        if not self.folder.get():
            messagebox.showinfo("Connect", "Choose a data folder, or use sample data, first.")
            return

        def start():
            try:
                self.session.connect(self.server.get(), self.token.get(), Path(self.folder.get()), on_end=self._ended)
            except AgentError as exc:
                messagebox.showerror("Connect", str(exc))
                return
            self.status.set("Connecting…")
            self.connect_button.configure(state="disabled")
            self.disconnect_button.configure(state="normal")
            self.root.after(4000, self._refresh_status)

        if self.session.profile:
            start()
        else:
            self.check_token(then=start)

    def _refresh_status(self) -> None:
        if self.session.connected:
            self.status.set("Connected · taking part in rounds" if self.take_part.get() else "Connected · not taking part")
            self.root.after(4000, self._refresh_status)

    def _ended(self, error) -> None:
        def update():
            self.status.set("Not connected")
            self.connect_button.configure(state="normal")
            self.disconnect_button.configure(state="disabled")
            if error:
                self._log(f"stopped: {error}")
                messagebox.showerror("Connection", error)
            else:
                self._log("disconnected")

        self.messages.put(("call", update))

    def disconnect(self) -> None:
        self._log("disconnecting…")
        self.session.disconnect()

    def toggle_take_part(self) -> None:
        self.session.set_take_part(self.take_part.get())
        self._log("taking part in rounds" if self.take_part.get() else "not taking part: invitations will be declined")
        self._save()
        self._refresh_status()

    def close(self) -> None:
        self.session.disconnect()
        self.root.destroy()


def run_window(default_server: str) -> None:
    root = tk.Tk()
    root.geometry("900x800")
    AgentWindow(root, default_server)
    root.mainloop()
