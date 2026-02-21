#!/usr/bin/env python3
"""
FM Radio Station - Desktop internet radio player.
Requires VLC media player to be installed: https://www.videolan.org/vlc/
"""

import json
import os
import random
import sys
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

# Paths (when frozen by PyInstaller, use exe directory so stations.json lives next to exe)
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
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
    # When frozen, copy bundled stations.json to exe dir if missing (first run)
    if getattr(sys, "frozen", False) and not STATIONS_FILE.exists():
        bundled = Path(sys._MEIPASS) / "stations.json"
        if bundled.exists():
            try:
                import shutil
                shutil.copy2(bundled, STATIONS_FILE)
            except OSError:
                pass
    if not STATIONS_FILE.exists():
        return []
    try:
        with open(STATIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("stations", [])
        defaults = default_station_metadata()
        out = []
        for i, s in enumerate(raw):
            merged = {**defaults, **s}
            if merged.get("dialPosition", 0) == 0:
                merged["dialPosition"] = i + 1
            out.append(merged)
        return out
    except (json.JSONDecodeError, OSError):
        return []


def save_stations(stations):
    """Save station list to JSON."""
    with open(STATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"stations": stations}, f, indent=2)


def default_station_metadata():
    """Return default values for enhanced station metadata (for new stations)."""
    return {
        "genre": "",
        "format": "streaming",
        "location": {"city": "", "state": "", "country": "US"},
        "language": "en",
        "bitrate": None,
        "codec": "",
        "logo": "",
        "description": "",
        "tags": [],
        "favorite": False,
        "lastPlayed": None,
        "popularity": None,
        "streamType": "icecast",
        "isLive": True,
        "fallbackUrls": [],
        "status": "unknown",
        "latencyMs": None,
        "nowPlaying": None,
        "scheduleUrl": "",
        "website": "",
        "socials": {"twitter": "", "instagram": ""},
        "dialPosition": 0,
        "band": "FM",
        "hdChannel": "",
        "priority": 1,
    }


class FMRadioApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FM Radio")
        self.root.geometry("440x560")
        self.root.resizable(True, True)
        self.root.configure(bg=BG_DARK)

        self.stations = load_stations()
        self.filtered_indices = list(range(len(self.stations)))
        self.current_index = 0
        self.player = None
        self.instance = None
        self._volume = 80
        self._recording = False
        self._recording_stop = threading.Event()
        self._recording_thread = None
        self._recording_path = None
        self._filling_listbox = False
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
        self.root.bind_all("<Return>", self._on_enter_key)
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
        # Wraplength for all display text so it wraps to new lines instead of cutting off
        display_wraplength = 420

        # Now Playing (compact, fixed height — single line, no resize)
        now_playing_frame = tk.Frame(display_inner, bg=BG_DISPLAY)
        now_playing_frame.pack(fill=tk.X, pady=(0, 4))
        tk.Label(
            now_playing_frame, text="Now Playing", font=("Consolas", 9),
            fg=TEXT_DIM, bg=BG_DISPLAY
        ).pack(anchor=tk.W)
        # Single-line only: fixed height + no wrap so section never resizes
        self.now_playing_label = tk.Label(
            display_inner, text="", font=("Segoe UI", 10),
            fg=GLOW, bg=BG_DISPLAY, height=1, width=48, anchor=tk.W, wraplength=0
        )
        self.now_playing_label.pack(anchor=tk.W)

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
            fg=TEXT_DIM, bg=BG_DISPLAY, wraplength=display_wraplength, justify=tk.LEFT
        )
        self.station_label.pack(anchor=tk.W)

        # Tune + Play/Stop row
        controls = tk.Frame(main, bg=BG_DARK)
        controls.pack(pady=14)
        tune_frame = tk.Frame(controls, bg=BG_DARK)
        tune_frame.pack(side=tk.LEFT, padx=(0, 20))
        for label, cmd in [
            ("◀ PREV", self._prev_station),
            ("NEXT ▶", self._next_station),
            ("🎲 RANDOM", self._random_station),
        ]:
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

        # Search box (on top of playlist)
        search_frame = tk.Frame(main, bg=BG_DARK)
        search_frame.pack(fill=tk.X, pady=(16, 6))
        tk.Label(
            search_frame, text="Search", font=("Consolas", 9),
            fg=TEXT_DIM, bg=BG_DARK, width=6, anchor=tk.W
        ).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._on_search())
        self.search_entry = tk.Entry(
            search_frame, textvariable=self.search_var, font=("Segoe UI", 10),
            bg=BG_DISPLAY, fg=TEXT, insertbackground=TEXT,
            relief=tk.FLAT, bd=0, highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=BORDER_ACCENT
        )
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), ipady=6, ipadx=8)

        # Station list
        list_header = tk.Frame(main, bg=BG_DARK)
        list_header.pack(fill=tk.X, pady=(16, 6))
        tk.Label(list_header, text="STATIONS", font=("Consolas", 9), fg=TEXT_DIM, bg=BG_DARK).pack(side=tk.LEFT)
        tk.Button(
            list_header, text="Add", font=("Consolas", 9),
            bg=BG_PANEL, fg=TEXT_DIM, activebackground=BORDER_ACCENT, activeforeground=BG_DARK,
            relief=tk.FLAT, padx=10, pady=2, cursor="hand2",
            command=self._add_station
        ).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(
            list_header, text="Remove", font=("Consolas", 9),
            bg=BG_PANEL, fg=TEXT_DIM, activebackground=STOP_BG, activeforeground=TEXT,
            relief=tk.FLAT, padx=10, pady=2, cursor="hand2",
            command=self._delete_station
        ).pack(side=tk.RIGHT, padx=(0, 8))
        self.station_count_label = tk.Label(
            list_header, text="0 stations", font=("Consolas", 9), fg=TEXT_DIM, bg=BG_DARK
        )
        self.station_count_label.pack(side=tk.RIGHT)
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
        self.listbox.bind("<Return>", self._on_enter_key)

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

    def _on_search(self):
        self._fill_listbox()
        # Do not change current_index or update Now Playing when typing in search—
        # the display should only reflect the station that is actually selected/playing.

    def _fill_listbox(self):
        q = (getattr(self, "search_var", None) and self.search_var.get() or "").strip().lower()
        if not q:
            self.filtered_indices = list(range(len(self.stations)))
        else:
            def matches(s):
                if q in (s.get("name") or "").lower() or q in str(s.get("frequency", "")):
                    return True
                if q in (s.get("genre") or "").lower() or q in (s.get("description") or "").lower():
                    return True
                for tag in s.get("tags") or []:
                    if q in (tag or "").lower():
                        return True
                loc = s.get("location") or {}
                if isinstance(loc, dict):
                    if q in (loc.get("city") or "").lower() or q in (loc.get("state") or "").lower():
                        return True
                return False
            self.filtered_indices = [i for i, s in enumerate(self.stations) if matches(s)]
        # Ignore selection events while rebuilding (they can fire with wrong index, e.g. 0)
        self._filling_listbox = True
        try:
            self.listbox.delete(0, tk.END)
            for idx in self.filtered_indices:
                s = self.stations[idx]
                self.listbox.insert(tk.END, f"  {s.get('frequency', '??')}  {s.get('name', 'Unknown')}")
            if self.filtered_indices and self.current_index in self.filtered_indices:
                listbox_idx = self.filtered_indices.index(self.current_index)
                self.listbox.selection_set(listbox_idx)
                self.listbox.see(listbox_idx)
        finally:
            self._filling_listbox = False
        n = len(self.stations)
        if hasattr(self, "station_count_label") and self.station_count_label.winfo_exists():
            self.station_count_label.config(text=f"{n} station{'s' if n != 1 else ''}")

    def _update_display(self):
        if not self.stations or self.current_index < 0 or self.current_index >= len(self.stations):
            return
        s = self.stations[self.current_index]
        self.freq_label.config(text=s.get("frequency", "—"))
        # Now Playing from station metadata (title, artist, show)
        np = s.get("nowPlaying")
        if np and isinstance(np, dict):
            title = (np.get("title") or "").strip()
            artist = (np.get("artist") or "").strip()
            show = (np.get("show") or "").strip()
            parts = []
            if artist and title:
                parts.append(f"{artist} – {title}")
            elif title:
                parts.append(title)
            if show:
                parts.append(f"({show})")
            now_text = "  ".join(parts) if parts else ""
        else:
            now_text = ""
        # Keep Now Playing to one line so the section height never resizes
        max_len = 47
        if len(now_text) > max_len:
            now_text = now_text[: max_len - 1].rstrip() + "…"
        self.now_playing_label.config(text=now_text)
        # Station name + genre/bitrate/description (wraps to new lines)
        name = s.get("name", "—")
        genre = (s.get("genre") or "").strip()
        desc = (s.get("description") or "").strip()
        bitrate = s.get("bitrate")
        sub = []
        if genre:
            sub.append(genre)
        if bitrate is not None:
            sub.append(f"{bitrate} kbps")
        if desc:
            sub.append(desc)
        display_text = name + ("  ·  " + "  ·  ".join(sub) if sub else "")
        self.station_label.config(text=display_text)
        # Only sync listbox selection; don't rebuild the list (avoids flicker/rearrange on click)
        if self.listbox.size() == len(self.filtered_indices) and self.current_index in self.filtered_indices:
            self.listbox.selection_clear(0, tk.END)
            listbox_idx = self.filtered_indices.index(self.current_index)
            self.listbox.selection_set(listbox_idx)
            self.listbox.see(listbox_idx)
        else:
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

    def _on_enter_key(self, event=None):
        self._play_current_station()
        return "break"

    def _play_current_station(self):
        """Start or restart playback of the currently selected station."""
        if not self.player or not self.stations:
            return
        if self.player.is_playing():
            self._toggle_play()
            self._toggle_play()
        else:
            self._toggle_play()

    def _prev_station(self):
        if not self.filtered_indices:
            return
        was_playing = self.player and self.player.is_playing()
        pos = self.filtered_indices.index(self.current_index) if self.current_index in self.filtered_indices else 0
        new_pos = (pos - 1) % len(self.filtered_indices)
        self.current_index = self.filtered_indices[new_pos]
        self._update_display()
        if was_playing:
            self._toggle_play()
            self._toggle_play()

    def _next_station(self):
        if not self.filtered_indices:
            return
        was_playing = self.player and self.player.is_playing()
        pos = self.filtered_indices.index(self.current_index) if self.current_index in self.filtered_indices else 0
        new_pos = (pos + 1) % len(self.filtered_indices)
        self.current_index = self.filtered_indices[new_pos]
        self._update_display()
        if was_playing:
            self._toggle_play()
            self._toggle_play()

    def _random_station(self):
        """Pick a random station and start playing it."""
        if not self.filtered_indices:
            return
        n = len(self.filtered_indices)
        if n == 1:
            idx = self.filtered_indices[0]
        else:
            candidates = [i for i in self.filtered_indices if i != self.current_index]
            idx = random.choice(candidates) if candidates else self.filtered_indices[0]
        self.current_index = idx
        self._update_display()
        # Start playing (or restart if already playing)
        if self.player and self.player.is_playing():
            self._toggle_play()
            self._toggle_play()
        else:
            self._toggle_play()

    def _on_station_select(self, event):
        # Ignore selection events fired during search/listbox rebuild (they use wrong index)
        if getattr(self, "_filling_listbox", False):
            return
        sel = self.listbox.curselection()
        if not sel or not self.filtered_indices:
            return
        listbox_idx = int(sel[0])
        if listbox_idx < 0 or listbox_idx >= len(self.filtered_indices):
            return
        new_index = self.filtered_indices[listbox_idx]
        if new_index == self.current_index:
            self._update_display()
            return
        self.current_index = new_index
        self._update_display()
        self._play_current_station()

    def _add_station(self):
        """Open a dialog to add a new station (name, URL, frequency) and save."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add station")
        dialog.configure(bg=BG_DARK)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("360x180")
        dialog.resizable(False, False)

        main_dlg = tk.Frame(dialog, bg=BG_DARK, padx=20, pady=16)
        main_dlg.pack(fill=tk.BOTH, expand=True)

        def make_row(label_text, default=""):
            row = tk.Frame(main_dlg, bg=BG_DARK)
            row.pack(fill=tk.X, pady=6)
            tk.Label(row, text=label_text, font=("Consolas", 9), fg=TEXT_DIM, bg=BG_DARK, width=10, anchor=tk.W).pack(side=tk.LEFT)
            entry = tk.Entry(row, font=("Segoe UI", 10), bg=BG_DISPLAY, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER_ACCENT)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), ipady=4, ipadx=6)
            entry.insert(0, default)
            return entry

        name_entry = make_row("Name", "")
        url_entry = make_row("URL", "https://")
        freq_entry = make_row("Frequency", "98.5")

        result = {"ok": False}

        def on_ok():
            name = name_entry.get().strip()
            url = url_entry.get().strip()
            freq = freq_entry.get().strip() or "—"
            if not name:
                messagebox.showwarning("Add station", "Please enter a station name.", parent=dialog)
                return
            if not url:
                messagebox.showwarning("Add station", "Please enter a stream URL.", parent=dialog)
                return
            if not url.startswith(("http://", "https://")):
                messagebox.showwarning("Add station", "URL must start with http:// or https://", parent=dialog)
                return
            result["ok"] = True
            new_station = {"name": name, "url": url, "frequency": freq, **default_station_metadata()}
            new_station["dialPosition"] = len(self.stations) + 1
            self.stations.append(new_station)
            save_stations(self.stations)
            self.current_index = len(self.stations) - 1
            self._update_display()
            self._fill_listbox()
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        btn_row = tk.Frame(main_dlg, bg=BG_DARK)
        btn_row.pack(fill=tk.X, pady=(16, 0))
        tk.Button(
            btn_row, text="Cancel", font=("Consolas", 9),
            bg=BG_PANEL, fg=TEXT_DIM, activebackground=BORDER_ACCENT, activeforeground=BG_DARK,
            relief=tk.FLAT, padx=14, pady=6, cursor="hand2",
            command=on_cancel
        ).pack(side=tk.RIGHT, padx=4)
        tk.Button(
            btn_row, text="Add", font=("Consolas", 9, "bold"),
            bg=PLAY_BG, fg=PLAY_FG, activebackground=ACCENT_DIM, activeforeground=PLAY_FG,
            relief=tk.FLAT, padx=14, pady=6, cursor="hand2",
            command=on_ok
        ).pack(side=tk.RIGHT)

        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_reqheight()) // 2
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        name_entry.focus_set()
        dialog.wait_window()

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
            if hasattr(self, "now_playing_label") and self.now_playing_label.winfo_exists():
                self.now_playing_label.config(text="")
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
