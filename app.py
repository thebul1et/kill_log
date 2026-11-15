"""Rob Run Death Log - desktop app: window + tray icon + starts reading when the game opens."""
import csv
import json
import os
import queue
import socket
import sqlite3
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import bot

PING_PORT = 48271  # used so a second launch just shows the already-running window
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def fmt(iso):
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%b %d, %I:%M %p")
    except Exception:
        return iso or ""


def running_programs():
    try:
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return sorted({r[0] for r in csv.reader(out.splitlines()) if r}, key=str.lower)
    except Exception:
        return []


def autostart_on():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "RobRunDeathLog")
        return True
    except Exception:
        return False


def set_autostart(on):
    try:
        import winreg
        exe = f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{os.path.abspath(__file__)}"'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, "RobRunDeathLog", 0, winreg.REG_SZ, exe + " --background")
            else:
                try:
                    winreg.DeleteValue(k, "RobRunDeathLog")
                except FileNotFoundError:
                    pass
    except Exception:
        pass


def save_config():
    bot.CFG_PATH.write_text(json.dumps(bot.CFG, indent=2), encoding="utf-8")


class App:
    COLS = [("player", "Player", 260), ("id", "ID", 120), ("kills", "Kills", 70),
            ("arrests", "Arrests", 70), ("first", "First seen", 150), ("last", "Last seen", 150)]

    def __init__(self, background):
        self.q = queue.Queue()
        self.stop = threading.Event()
        self.sort = ("kills", True)
        self.root = tk.Tk()
        self.root.title("Rob Run Death Log")
        self.root.geometry("920x600")
        self.root.minsize(760, 460)
        self.status = tk.StringVar(value="Loading the text reader (first start takes a minute)...")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.render())
        self.rows = []
        self._style()
        self._build()
        bot.log = lambda *a, **k: self.q.put(("log", " ".join(str(x) for x in a)))
        self.tray = self._tray()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        threading.Thread(target=self._engine, daemon=True).start()
        self.tick()
        self.drain()
        if background:
            self.root.withdraw()
        elif not bot.CFG.get("game_process"):
            self.root.after(600, lambda: self.settings(first=True))

    # ---------- look ----------
    def _style(self):
        bg, card, fg, mut, acc = "#080e17", "#101a28", "#e6edf6", "#8497ae", "#ff4d5e"
        self.root.configure(bg=bg)
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure(".", background=bg, foreground=fg, fieldbackground=card, font=("Segoe UI", 10))
        st.configure("Treeview", background=card, fieldbackground=card, foreground=fg, rowheight=26, borderwidth=0)
        st.configure("Treeview.Heading", background=bg, foreground=mut, relief="flat", font=("Segoe UI", 9, "bold"))
        st.map("Treeview", background=[("selected", "#1d2b3f")])
        st.configure("TButton", background=card, foreground=fg, padding=6, borderwidth=0)
        st.map("TButton", background=[("active", "#1d2b3f")])
        st.configure("TEntry", insertcolor=fg)
        st.configure("TCheckbutton", background=bg, foreground=fg)
        self.acc, self.mut, self.card, self.fg, self.bg = acc, mut, card, fg, bg

    def _build(self):
        top = ttk.Frame(self.root, padding=(14, 12, 14, 6)); top.pack(fill="x")
        ttk.Label(top, textvariable=self.status, foreground=self.mut).pack(side="left")
        bar = ttk.Frame(self.root, padding=(14, 4)); bar.pack(fill="x")
        ttk.Entry(bar, textvariable=self.search, width=34).pack(side="left", padx=(0, 8))
        for text, cmd in (("Export CSV", self.export), ("Open in browser", self.browser),
                          ("Test screen read", self.test_read), ("Settings", self.settings)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=3)
        mid = ttk.Frame(self.root, padding=(14, 6)); mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=[c[0] for c in self.COLS], show="headings", selectmode="browse")
        for key, title, w in self.COLS:
            self.tree.heading(key, text=title, command=lambda k=key: self.set_sort(k))
            self.tree.column(key, width=w, anchor="w" if key in ("player", "first", "last") else "center")
        self.tree.tag_configure("odd", background="#0d1622")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        self.logbox = tk.Text(self.root, height=6, bg=self.card, fg=self.mut, relief="flat",
                              font=("Consolas", 9), state="disabled", wrap="word")
        self.logbox.pack(fill="x", padx=14, pady=(4, 12))

    # ---------- data ----------
    def tick(self):
        try:
            self.rows = bot._local_json(1)["players"]
            self.render()
        except Exception as exc:
            self.add_log(f"couldn't read the saved deaths: {exc}")
        self.root.after(3000, self.tick)

    def set_sort(self, key):
        self.sort = (key, not self.sort[1] if self.sort[0] == key else key not in ("player", "first", "last"))
        self.render()

    def render(self):
        q = self.search.get().strip().lower().lstrip("#")
        keyf = {"player": lambda p: (p["killer_name"] or "").lower(), "id": lambda p: p["killer_id"] or "",
                "kills": lambda p: p["kills"], "arrests": lambda p: p["arrests"],
                "first": lambda p: p["first_seen"], "last": lambda p: p["last_seen"]}[self.sort[0]]
        rows = [p for p in self.rows if not q or q in (p["killer_name"] or "").lower() or q in (p["killer_id"] or "")]
        rows.sort(key=keyf, reverse=self.sort[1])
        self.tree.delete(*self.tree.get_children())
        for i, p in enumerate(rows):
            self.tree.insert("", "end", tags=("odd",) if i % 2 else (),
                             values=(p["killer_name"], p["killer_id"] and "#" + p["killer_id"], p["kills"], p["arrests"],
                                     fmt(p["first_seen"]), fmt(p["last_seen"])))

    def export(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="players-who-killed-me.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["player", "id", "kills", "arrests", "first_seen", "last_seen"])
            for p in self.rows:
                w.writerow([p["killer_name"], p["killer_id"], p["kills"], p["arrests"], p["first_seen"], p["last_seen"]])

    def browser(self):
        webbrowser.open("http://127.0.0.1:%s" % (bot.CFG.get("local_page") or {}).get("port", 8765))

    # ---------- engine + messages ----------
    def _engine(self):
        try:
            bot.run(stop=self.stop, on_game=lambda r: self.q.put(("game", r)), open_page=False)
        except Exception as exc:
            self.q.put(("log", f"The logger stopped: {exc}"))

    def add_log(self, text):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", datetime.now().strftime("%H:%M  ") + text + "\n")
        if int(self.logbox.index("end-1c").split(".")[0]) > 300:
            self.logbox.delete("1.0", "50.0")
        self.logbox.see("end"); self.logbox.configure(state="disabled")

    def drain(self):
        try:
            while True:
                kind, *rest = self.q.get_nowait()
                if kind == "log":
                    self.add_log(rest[0])
                    if rest[0].startswith("Watching for deaths") and not bot.CFG.get("game_process"):
                        self.status.set("Watching your screen (no game selected in Settings)")
                elif kind == "game":
                    if not bot.CFG.get("game_process"):
                        self.status.set("Watching your screen (no game selected in Settings)")
                    elif rest[0]:
                        self.status.set("Rob Run is running - watching for deaths")
                        if bot.CFG.get("show_window_on_game_start", True):
                            self.show()
                    else:
                        self.status.set("Waiting for Rob Run to start...")
                elif kind == "show":
                    self.show()
                elif kind == "test":
                    self.show_test(*rest)
                elif kind == "quit":
                    return self.quit()
        except queue.Empty:
            pass
        self.root.after(300, self.drain)

    def show(self):
        self.root.deiconify(); self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(250, lambda: self.root.attributes("-topmost", False))

    def on_close(self):
        self.root.withdraw() if self.tray else self.quit()

    def quit(self):
        self.stop.set()
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def _tray(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
        except Exception:
            return None
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 4, 60, 60), fill=(255, 77, 94, 255)); d.ellipse((22, 22, 42, 42), fill=(8, 14, 23, 255))
        menu = pystray.Menu(pystray.MenuItem("Open Rob Run Death Log", lambda *_: self.q.put(("show",)), default=True),
                            pystray.MenuItem("Quit", lambda *_: self.q.put(("quit",))))
        icon = pystray.Icon("RobRunDeathLog", img, "Rob Run Death Log", menu)
        icon.run_detached()
        return icon

    # ---------- test read ----------
    def test_read(self):
        self.status.set("Reading the screen...")
        def work():
            try:
                crop, text = bot.ocr(bot.grab())
                self.q.put(("test", crop, text, bot.parse(text)))
            except Exception as exc:
                self.q.put(("log", f"Test read failed: {exc}"))
        threading.Thread(target=work, daemon=True).start()

    def show_test(self, crop, text, parsed):
        from PIL import ImageTk
        w = tk.Toplevel(self.root); w.title("Test screen read"); w.configure(bg=self.bg)
        photo = ImageTk.PhotoImage(crop); lbl = tk.Label(w, image=photo, bg=self.bg); lbl.image = photo; lbl.pack(padx=12, pady=10)
        ttk.Label(w, text="It read:", foreground=self.mut).pack(anchor="w", padx=12)
        ttk.Label(w, text=text or "(nothing)", wraplength=520).pack(anchor="w", padx=12)
        ttk.Label(w, text="Counted as a death:", foreground=self.mut).pack(anchor="w", padx=12, pady=(8, 0))
        ttk.Label(w, text=f"{parsed[0]}  {parsed[1]}" if parsed else "No - that isn't a death or arrest screen.").pack(anchor="w", padx=12, pady=(0, 12))
        self.status.set("Test finished")

    # ---------- settings ----------
    def settings(self, first=False):
        w = tk.Toplevel(self.root); w.title("Settings"); w.configure(bg=self.bg); w.resizable(False, False)
        pad = {"padx": 12, "pady": 5}
        if first:
            ttk.Label(w, text="Start Rob Run, then pick it from the list so the logger only\nreads your screen while the game is open.",
                      foreground=self.mut).grid(row=0, column=0, columnspan=3, **pad)
        gp = tk.StringVar(value=bot.CFG.get("game_process", ""))
        mon = tk.StringVar(value=str(bot.CFG.get("monitor", 1)))
        arr = tk.BooleanVar(value=bot.CFG.get("log_arrests", True))
        shw = tk.BooleanVar(value=bot.CFG.get("show_window_on_game_start", True))
        auto = tk.BooleanVar(value=autostart_on())
        ttk.Label(w, text="Game program name").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(w, textvariable=gp, width=24).grid(row=1, column=1, **pad)
        ttk.Button(w, text="Pick from running programs", command=lambda: self.pick(gp)).grid(row=1, column=2, **pad)
        ttk.Label(w, text="Monitor the game is on").grid(row=2, column=0, sticky="w", **pad)
        ttk.Spinbox(w, from_=1, to=6, textvariable=mon, width=5).grid(row=2, column=1, sticky="w", **pad)
        for r, (var, text) in enumerate(((arr, "Also log arrests (not only eliminations)"),
                                         (shw, "Open this window when Rob Run starts"),
                                         (auto, "Start with Windows (waits in the tray until the game opens)")), start=3):
            ttk.Checkbutton(w, text=text, variable=var).grid(row=r, column=0, columnspan=3, sticky="w", **pad)
        def save():
            bot.CFG.update(game_process=gp.get().strip().lower(), monitor=int(mon.get() or 1),
                           log_arrests=bool(arr.get()), show_window_on_game_start=bool(shw.get()))
            save_config(); set_autostart(bool(auto.get())); bot._game["checked"] = 0; w.destroy()
        def clear():
            if messagebox.askyesno("Clear saved deaths", "Delete every saved death and arrest? This can't be undone.", parent=w):
                con = sqlite3.connect(bot.DB_PATH); con.execute("DELETE FROM deaths"); con.commit(); con.close(); self.tick()
        row = ttk.Frame(w); row.grid(row=7, column=0, columnspan=3, pady=10)
        ttk.Button(row, text="Save", command=save).pack(side="left", padx=4)
        ttk.Button(row, text="Advanced (config.json)", command=lambda: os.startfile(bot.CFG_PATH) if hasattr(os, "startfile") else None).pack(side="left", padx=4)
        ttk.Button(row, text="Clear saved deaths", command=clear).pack(side="left", padx=4)

    def pick(self, var):
        w = tk.Toplevel(self.root); w.title("Running programs"); w.configure(bg=self.bg)
        q = tk.StringVar(); ttk.Entry(w, textvariable=q).pack(fill="x", padx=10, pady=8)
        lb = tk.Listbox(w, width=44, height=16, bg=self.card, fg=self.fg, relief="flat"); lb.pack(padx=10, pady=(0, 10))
        names = running_programs()
        def fill(*_):
            lb.delete(0, "end")
            for n in names:
                if q.get().lower() in n.lower():
                    lb.insert("end", n)
        def choose(_=None):
            if lb.curselection():
                var.set(lb.get(lb.curselection()[0]).lower().removesuffix(".exe")); w.destroy()
        q.trace_add("write", fill); lb.bind("<Double-Button-1>", choose); fill()


def main():
    if "--selftest" in sys.argv:  # used by the automatic build to prove the app works
        sys.exit(bot.selftest())
    background = "--background" in sys.argv
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", PING_PORT))
    except OSError:  # already running: ask that copy to show its window
        try:
            socket.create_connection(("127.0.0.1", PING_PORT), timeout=2).close()
        except OSError:
            pass
        return
    lock.listen(5)
    app = App(background)
    def listen():
        while True:
            try:
                lock.accept()[0].close(); app.q.put(("show",))
            except OSError:
                return
    threading.Thread(target=listen, daemon=True).start()
    app.root.mainloop()


if __name__ == "__main__":
    main()
