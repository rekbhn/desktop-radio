#!/usr/bin/env python3
"""
FM Radio Station - Desktop internet radio player.
Requires VLC media player to be installed: https://www.videolan.org/vlc/
"""

import json
import os
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox
from urllib.request import Request, urlopen

try:
    import vlc  # type: ignore[import-untyped]
except ImportError:
    vlc = None

# Paths
APP_DIR = Path(__file__).resolve().parent
STATIONS_FILE = APP_DIR / "stations.json"
RECORDINGS_DIR = APP_DIR / "Recordings"
RECORD_CHUNK_SIZE = 8192

# Subtle, muted theme (no neon)
BG_DARK = "#1a1d24"
BG_PANEL = "#252a33"
BG_DISPLAY = "#1e2128"
ACCENT = "#6b8a94"
ACCENT_DIM = "#5b7a84"
GLOW = "#7d95a0"
TEXT = "#e4e7eb"
TEXT_DIM = "#8b95a0"
PLAY_BG = "#4a6b5a"
PLAY_FG = "#e4e7eb"
STOP_BG = "#7a6b6b"
STOP_FG = "#e4e7eb"
BORDER = "#2d333b"
BORDER_ACCENT = "#5b7c85"


def load_stations():
    """Load station list from JSON."""
    if not STATIONS_FILE.exists():
        return []
    try:
        with open(STATIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("stations", [])
    except (json.JSONDecodeError, OSError):
        return []


def save_stations(stations):
    """Save station list to JSON."""
    with open(STATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"stations": stations}, f, indent=2)


class FMRadioApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FM Radio")
        self.root.geometry("440x560")
        self.root.resizable(True, True)
        self.root.configure(bg=BG_DARK)

        self.stations = load_stations()
        self.current_index = 0
        self.player = None
        self.instance = None
        self._volume = 80
        self._recording = False
        self._recording_stop = threading.Event()
        self._recording_thread = None
        self._recording_path = None
        RECORDINGS_DIR.mkdir(exist_ok=True)

        if vlc is None:
            self._show_vlc_error()
            return

        try:
            self.instance = vlc.Instance("--no-xlib" if os.name != "nt" else "")
            self.player = self.instance.media_player_new()
        except Exception as e:
            messagebox.showerror("VLC Error", f"Could not start VLC.\n\n{e}\n\nMake sure VLC is installed.")
            self.root.destroy()
            return

        self._build_ui()
        self._apply_styles()
        if self.stations:
            self._update_display()

        self.root.bind_all("<Up>", self._on_up_key)
        self.root.bind_all("<Down>", self._on_down_key)
        self.root.bind_all("<Left>", self._on_left_key)
        self.root.bind_all("<Right>", self._on_right_key)
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.root.focus_set()

    def _show_vlc_error(self):
        messagebox.showerror(
            "Missing dependency",
            "python-vlc is required.\n\n"
            "Install with: pip install python-vlc\n\n"
            "You also need VLC media player installed:\n"
            "https://www.videolan.org/vlc/"
        )
        self.root.destroy()

    def _build_ui(self):
        main = tk.Frame(self.root, bg=BG_DARK, padx=24, pady=20)
        main.pack(fill=tk.BOTH, expand=True)

        # Title + accent line
        header = tk.Frame(main, bg=BG_DARK)
        header.pack(fill=tk.X, pady=(0, 16))
        title = tk.Label(
            header, text="FM RADIO", font=("Consolas", 11, "bold"),
            fg=TEXT_DIM, bg=BG_DARK
        )
        title.pack(anchor=tk.W)
        tk.Frame(header, height=1, bg=BORDER_ACCENT).pack(fill=tk.X, pady=(6, 0))

        # Display panel — LED-style screen
        display_outer = tk.Frame(main, bg=BORDER_ACCENT, padx=1, pady=1)
        display_outer.pack(fill=tk.X, pady=(0, 14))
        display_inner = tk.Frame(display_outer, bg=BG_DISPLAY, padx=20, pady=16)
        display_inner.pack(fill=tk.X)

        self.freq_label = tk.Label(
            display_inner, text="98.5", font=("Consolas", 36, "bold"),
            fg=ACCENT, bg=BG_DISPLAY
        )
        self.freq_label.pack(anchor=tk.W)
        self.mhz_label = tk.Label(
            display_inner, text="MHz", font=("Consolas", 12),
            fg=GLOW, bg=BG_DISPLAY
        )
        self.mhz_label.place(in_=self.freq_label, relx=1.0, x=6, rely=0.55)

        self.station_label = tk.Label(
            display_inner, text="— No station —", font=("Segoe UI", 11),
            fg=TEXT_DIM, bg=BG_DISPLAY, wraplength=380
        )
        self.station_label.pack(anchor=tk.W)

        # Tune + Play/Stop row
        controls = tk.Frame(main, bg=BG_DARK)
        controls.pack(pady=14)
        tune_frame = tk.Frame(controls, bg=BG_DARK)
        tune_frame.pack(side=tk.LEFT, padx=(0, 20))
        for label, cmd in [("◀ PREV", self._prev_station), ("NEXT ▶", self._next_station)]:
            btn = tk.Button(
                tune_frame, text=label, font=("Consolas", 10, "bold"),
                bg=BG_PANEL, fg=TEXT, activebackground=BORDER_ACCENT, activeforeground=BG_DARK,
                relief=tk.FLAT, bd=0, highlightthickness=1, highlightbackground=BORDER,
                padx=14, pady=8, cursor="hand2", command=cmd
            )
            btn.pack(side=tk.LEFT, padx=4)
        play_frame = tk.Frame(controls, bg=BG_DARK)
        play_frame.pack(side=tk.LEFT)
        self.play_btn = tk.Button(
            play_frame, text="▶ PLAY", font=("Consolas", 11, "bold"),
            bg=PLAY_BG, fg=PLAY_FG, activebackground=ACCENT_DIM, activeforeground=PLAY_FG,
            relief=tk.FLAT, padx=22, pady=8, cursor="hand2",
            command=self._toggle_play
        )
        self.play_btn.pack(side=tk.LEFT, padx=4)
        self.stop_btn = tk.Button(
            play_frame, text="■ STOP", font=("Consolas", 11, "bold"),
            bg=STOP_BG, fg=STOP_FG, activebackground=TEXT_DIM, activeforeground=STOP_FG,
            relief=tk.FLAT, padx=22, pady=8, cursor="hand2",
            command=self._stop
        )
        self.stop_btn.pack(side=tk.LEFT, padx=4)
        self.rec_btn = tk.Button(
            play_frame, text="● REC", font=("Consolas", 10, "bold"),
            bg=BG_PANEL, fg=TEXT, activebackground=BORDER_ACCENT, activeforeground=BG_DARK,
            relief=tk.FLAT, padx=16, pady=8, cursor="hand2",
            command=self._toggle_record
        )
        self.rec_btn.pack(side=tk.LEFT, padx=4)
        rec_status_frame = tk.Frame(main, bg=BG_DARK)
        rec_status_frame.pack(fill=tk.X)
        self.rec_status_label = tk.Label(
            rec_status_frame, text="", font=("Consolas", 9),
            fg=TEXT_DIM, bg=BG_DARK
        )
        self.rec_status_label.pack(anchor=tk.W)

        # Volume
        vol_frame = tk.Frame(main, bg=BG_DARK)
        vol_frame.pack(fill=tk.X, pady=10)
        tk.Label(vol_frame, text="VOL", font=("Consolas", 9), fg=TEXT_DIM, bg=BG_DARK, width=4, anchor=tk.W).pack(side=tk.LEFT)
        self.vol_var = tk.IntVar(value=self._volume)
        self.vol_scale = ttk.Scale(
            vol_frame, from_=0, to=100, variable=self.vol_var,
            orient=tk.HORIZONTAL, length=240, command=self._on_volume
        )
        self.vol_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self.vol_value_label = tk.Label(
            vol_frame, text="80%", font=("Consolas", 9),
            fg=ACCENT, bg=BG_DARK, width=4
        )
        self.vol_value_label.pack(side=tk.LEFT)

        # Station list
        list_header = tk.Frame(main, bg=BG_DARK)
        list_header.pack(fill=tk.X, pady=(16, 6))
        tk.Label(list_header, text="STATIONS", font=("Consolas", 9), fg=TEXT_DIM, bg=BG_DARK).pack(side=tk.LEFT)
        tk.Button(
            list_header, text="Remove", font=("Consolas", 9),
            bg=BG_PANEL, fg=TEXT_DIM, activebackground=STOP_BG, activeforeground=TEXT,
            relief=tk.FLAT, padx=10, pady=2, cursor="hand2",
            command=self._delete_station
        ).pack(side=tk.RIGHT)
        tk.Frame(list_header, height=1, bg=BORDER).pack(fill=tk.X, pady=(4, 0))
        list_outer = tk.Frame(main, bg=BORDER, padx=1, pady=1)
        list_outer.pack(fill=tk.BOTH, expand=True)
        list_container = tk.Frame(list_outer, bg=BG_PANEL)
        list_container.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox = tk.Listbox(
            list_container, font=("Consolas", 10), height=8,
            bg=BG_DISPLAY, fg=TEXT, selectbackground=BORDER_ACCENT, selectforeground=BG_DARK,
            activestyle=tk.NONE, relief=tk.FLAT, bd=0,
            highlightthickness=0, yscrollcommand=scrollbar.set
        )
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_station_select)
        self.listbox.bind("<Double-1>", lambda e: self._toggle_play())
        # Bind Up/Down on listbox so they work when listbox has focus (e.g. on Windows)
        self.listbox.bind("<Up>", self._on_up_key)
        self.listbox.bind("<Down>", self._on_down_key)

        self._fill_listbox()

    def _apply_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Horizontal.TScale",
            background=BG_DARK,
            troughcolor=BG_PANEL,
            darkcolor=BORDER,
            lightcolor=ACCENT,
        )
        style.map("Horizontal.TScale", background=[("active", ACCENT)])
        try:
            style.configure("Vertical.TScrollbar", background=BG_PANEL, troughcolor=BG_DARK)
        except tk.TclError:
            pass

    def _fill_listbox(self):
        self.listbox.delete(0, tk.END)
        for i, s in enumerate(self.stations):
            self.listbox.insert(tk.END, f"  {s.get('frequency', '??')}  {s.get('name', 'Unknown')}")
        if self.stations and 0 <= self.current_index < len(self.stations):
            self.listbox.selection_set(self.current_index)
            self.listbox.see(self.current_index)

    def _update_display(self):
        if not self.stations or self.current_index < 0 or self.current_index >= len(self.stations):
            return
        s = self.stations[self.current_index]
        self.freq_label.config(text=s.get("frequency", "—"))
        self.station_label.config(text=s.get("name", "—"))
        self._fill_listbox()

    def _get_station(self):
        if not self.stations or self.current_index < 0 or self.current_index >= len(self.stations):
            return None
        return self.stations[self.current_index]

    def _toggle_play(self):
        if not self.player or not self.stations:
            return
        if self.player.is_playing():
            self.player.pause()
            self.play_btn.config(text="▶ PLAY")
        else:
            station = self._get_station()
            if not station:
                return
            url = station.get("url")
            if not url:
                messagebox.showwarning("No URL", "This station has no stream URL.")
                return
            media = self.instance.media_new(url)
            self.player.set_media(media)
            self.player.audio_set_volume(self._volume)
            self.player.play()
            self.play_btn.config(text="⏸ PAUSE")

    def _stop(self):
        if self.player:
            self.player.stop()
            self.play_btn.config(text="▶ PLAY")

    def _record_worker(self, url: str, path: Path):
        """Background thread: stream URL to file until stop is requested."""
        try:
            req = Request(url, headers={"User-Agent": "FM-Radio-Recorder/1.0"})
            with urlopen(req, timeout=15) as resp:
                try:
                    if hasattr(resp, "fp") and getattr(resp.fp, "raw", None) is not None:
                        resp.fp.raw.sock.settimeout(10.0)
                except (AttributeError, OSError):
                    pass
                with open(path, "wb") as f:
                    while not self._recording_stop.is_set():
                        try:
                            chunk = resp.read(RECORD_CHUNK_SIZE)
                            if not chunk:
                                break
                            f.write(chunk)
                        except (OSError, ConnectionError, TimeoutError):
                            break
        except Exception as e:
            if self._recording and self.rec_status_label.winfo_exists():
                self._recording_path = None
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                self.root.after(0, lambda: self._show_recording_error(str(e)))
        finally:
            self.root.after(0, self._on_recording_finished)

    def _show_recording_error(self, msg: str):
        messagebox.showerror("Recording error", f"Recording failed.\n\n{msg}")
        self._recording = False
        self._update_recording_ui()

    def _on_recording_finished(self):
        self._recording = False
        self._recording_thread = None
        self._update_recording_ui()
        if self._recording_path and self._recording_path.exists() and self._recording_path.stat().st_size > 0:
            messagebox.showinfo("Recording saved", f"Saved to:\n{self._recording_path}")

    def _update_recording_ui(self):
        if not hasattr(self, "rec_btn") or not self.rec_btn.winfo_exists():
            return
        if self._recording:
            self.rec_btn.config(text="■ STOP REC", bg=STOP_BG, fg=STOP_FG)
            self.rec_status_label.config(text=f"Recording: {self._recording_path.name if self._recording_path else '…'}", fg=ACCENT)
        else:
            self.rec_btn.config(text="● REC", bg=BG_PANEL, fg=TEXT)
            self.rec_status_label.config(text="", fg=TEXT_DIM)

    def _toggle_record(self):
        if self._recording:
            self._stop_recording()
            return
        station = self._get_station()
        if not station:
            messagebox.showwarning("No station", "Select a station first.")
            return
        url = station.get("url")
        if not url:
            messagebox.showwarning("No URL", "This station has no stream URL.")
            return
        safe_name = "".join(c if c.isalnum() or c in " .-_" else "_" for c in station.get("name", "station"))[:40]
        ext = ".mp3" if "mp3" in url.lower() or "mpeg" in url.lower() else ".aac" if "aac" in url.lower() else ".mp3"
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._recording_path = RECORDINGS_DIR / f"record_{stamp}_{safe_name.strip()}{ext}"
        self._recording_stop.clear()
        self._recording = True
        self._recording_thread = threading.Thread(
            target=self._record_worker,
            args=(url, self._recording_path),
            daemon=True,
        )
        self._recording_thread.start()
        self._update_recording_ui()

    def _stop_recording(self):
        self._recording_stop.set()
        self._update_recording_ui()

    def _on_volume(self, value):
        try:
            v = int(float(value))
            self._volume = max(0, min(100, v))
            self.vol_value_label.config(text=f"{self._volume}%")
            if self.player:
                self.player.audio_set_volume(self._volume)
        except (ValueError, TypeError):
            pass

    def _on_up_key(self, event=None):
        self._prev_station()
        return "break"

    def _on_down_key(self, event=None):
        self._next_station()
        return "break"

    def _on_left_key(self, event=None):
        self._prev_station()
        return "break"

    def _on_right_key(self, event=None):
        self._next_station()
        return "break"

    def _prev_station(self):
        if not self.stations:
            return
        was_playing = self.player and self.player.is_playing()
        self.current_index = (self.current_index - 1) % len(self.stations)
        self._update_display()
        if was_playing:
            self._toggle_play()
            self._toggle_play()

    def _next_station(self):
        if not self.stations:
            return
        was_playing = self.player and self.player.is_playing()
        self.current_index = (self.current_index + 1) % len(self.stations)
        self._update_display()
        if was_playing:
            self._toggle_play()
            self._toggle_play()

    def _on_station_select(self, event):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.stations):
            was_playing = self.player and self.player.is_playing()
            self.current_index = idx
            self._update_display()
            if was_playing:
                self._toggle_play()
                self._toggle_play()

    def _delete_station(self):
        """Remove the currently selected station from the list and save to file."""
        if not self.stations:
            return
        idx = self.current_index
        if idx < 0 or idx >= len(self.stations):
            return
        name = self.stations[idx].get("name", "Unknown")
        if not messagebox.askyesno("Remove station", f"Remove \"{name}\" from the list?"):
            return
        was_playing = self.player and self.player.is_playing()
        if was_playing:
            self.player.stop()
            self.play_btn.config(text="▶ PLAY")
        self.stations.pop(idx)
        save_stations(self.stations)
        if not self.stations:
            self.current_index = 0
            self.freq_label.config(text="—")
            self.station_label.config(text="— No station —")
        else:
            self.current_index = min(idx, len(self.stations) - 1)
            self._update_display()
        self._fill_listbox()

    def _on_closing(self):
        if self.player:
            self.player.stop()
        self.root.destroy()

    def run(self):
        if self.player is None and vlc is not None:
            return
        self.root.mainloop()


def main():
    app = FMRadioApp()
    app.run()


if __name__ == "__main__":
    main()
