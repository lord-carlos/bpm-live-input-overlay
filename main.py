import pyaudio
import numpy as np
import aubio
import argparse
import logging
import threading
import json
import tkinter as tk
import threading
import time
import os

class DeviceDetector:
    def __init__(self):
        self.p = pyaudio.PyAudio()

    def list_audio_devices(self):
        try:
            info = self.p.get_host_api_info_by_index(0)
            numdevices = info.get('deviceCount')
            for i in range(0, numdevices):
                if (self.p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
                    logging.info("Input Device id %s - %s", i, self.p.get_device_info_by_host_api_device_index(0, i).get('name'))
        except Exception:
            logging.exception('Error listing audio devices')

    def __del__(self):
        self.p.terminate()

def list_input_devices():
    p = pyaudio.PyAudio()
    devices = []
    try:
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info.get('maxInputChannels', 0) > 0:
                devices.append({
                    'id': i,
                    'name': info.get('name'),
                    'defaultSampleRate': int(info.get('defaultSampleRate') or 0),
                    'maxInputChannels': int(info.get('maxInputChannels') or 0)
                })
        logging.debug('Found %d input devices', len(devices))
    except Exception:
        logging.exception('Error listing input devices')
    finally:
        p.terminate()
    return devices


def resolve_device_index(pyaudio_instance, config_entry):
    """Resolve a configured device entry to an actual device index.
    Strategy: exact name match -> substring match -> stored id fallback -> None
    """
    target_name = config_entry.get('name')
    # 1) exact name
    if target_name:
        for i in range(pyaudio_instance.get_device_count()):
            try:
                info = pyaudio_instance.get_device_info_by_index(i)
            except Exception:
                continue
            if info.get('maxInputChannels', 0) <= 0:
                continue
            if info.get('name') == target_name:
                return i
    # 2) substring match (case-insensitive)
    if target_name:
        lower = target_name.lower()
        for i in range(pyaudio_instance.get_device_count()):
            try:
                info = pyaudio_instance.get_device_info_by_index(i)
            except Exception:
                continue
            if info.get('maxInputChannels', 0) <= 0:
                continue
            if lower in (info.get('name') or '').lower():
                return i
    # 3) fallback to stored id if it exists and has input channels
    stored_id = config_entry.get('id')
    if stored_id is not None:
        try:
            info = pyaudio_instance.get_device_info_by_index(stored_id)
            if info.get('maxInputChannels', 0) > 0:
                return stored_id
        except Exception:
            pass
    return None

class BeatDetector(threading.Thread):
    def __init__(self, method, buffer_size, sample_rate, channels, format, input_device_index=None, bpm_scale=1.0, window_multiple=4):
        threading.Thread.__init__(self)
        self.p = pyaudio.PyAudio()
        # make buffer and window sizes explicit and configurable
        self.buffer_size = buffer_size
        self.window_multiple = window_multiple
        win_size = buffer_size * window_multiple
        # determine samplerate from device when available to avoid clock mismatch calibration
        self.sample_rate = int(sample_rate) if sample_rate else None
        if input_device_index is not None:
            try:
                dev_info = self.p.get_device_info_by_index(input_device_index)
                dev_rate = dev_info.get('defaultSampleRate')
                if dev_rate:
                    self.sample_rate = int(dev_rate)
                    if os.environ.get('BPM_DEBUG') == '1':
                        print(f"Using device sample rate {self.sample_rate} for input {input_device_index}")
            except Exception:
                # fallback to provided sample_rate
                pass
        if not self.sample_rate:
            # fallback to a sane default
            self.sample_rate = int(44100)

        # use named arguments to avoid ambiguity
        self.tempo = aubio.tempo(method=method, buf_size=win_size, hop_size=buffer_size, samplerate=self.sample_rate)
        # open stream with the device sample rate to prevent clock drift bias
        self.stream = self.p.open(format=format, channels=channels, rate=self.sample_rate, input=True, frames_per_buffer=buffer_size, input_device_index=input_device_index)
        self.bpm_estimates = []
        self.rolling_window_seconds = 5
        self.bpm = 0
        self.running = True
        # calibration / scale factor (defaults to 1.0; previous code used 0.993)
        self.bpm_scale = float(bpm_scale)

    def run(self):
        print("Starting to listen, press Ctrl+C to stop")
        try:
            while self.running:
                self.detect_beat()
        except KeyboardInterrupt:
            print("\nStopping")
            self.stream.stop_stream()
            self.stream.close()
            self.p.terminate()

    def stop(self):
        self.running = False

    def detect_beat(self):
        # guard against buffer overflow by allowing non-blocking read to drop frames when needed
        try:
            data = self.stream.read(self.buffer_size, exception_on_overflow=False)
        except Exception:
            return
        samples = np.frombuffer(data, dtype=aubio.float_type)
        is_beat = self.tempo(samples)
        if is_beat:
            this_beat = int(self.tempo.get_last_s())
            raw_bpm = self.tempo.get_bpm()
            if raw_bpm:
                # apply scale (previously a magic 0.993 multiplier)
                bpm_estimate = raw_bpm * self.bpm_scale
                self.bpm_estimates.append(bpm_estimate)
                # keep last N seconds estimates
                self.bpm_estimates = self.bpm_estimates[-self.rolling_window_seconds:]
                # use median for robustness
                try:
                    median_bpm = float(np.median(self.bpm_estimates))
                except Exception:
                    median_bpm = float(bpm_estimate)
                self.bpm = round(median_bpm, 1)
                # optional debug print controlled by env var
                if os.environ.get('BPM_DEBUG') == '1':
                    print(f"raw={raw_bpm:.3f}, scale={self.bpm_scale:.3f}, adj={bpm_estimate:.3f}, median={self.bpm:.2f}")
                # print(f"\rBeat at estimated BPM: {bpm_estimate:.2f}, rolling {self.rolling_window_seconds}s average BPM: {self.bpm:.1f} ", end='', flush=True)

class BpmDisplay:
    def __init__(self, beat_detectors):
        self.beat_detectors = beat_detectors

    def display_bpms(self):
        print("\n" * 10)
        while True:
            print("\r\033[K" + ",       ".join([f"{i}: {beat_detector.bpm:.1f}" for i, beat_detector in enumerate(self.beat_detectors)]), end='', flush=True)
            time.sleep(1)

def create_window(bd, x, y, font_size, font_color, bg_color):
    window = tk.Toplevel()
    window.overrideredirect(True)  # Remove border
    window.geometry(f'+{x}+{y}')  # Set position on screen
    window.attributes('-topmost', True)  # This makes the window always on top
    # window.attributes('-alpha', 0.5)  # Make window semi-transparent
    if bd is None:
        label = tk.Label(window, text='MISSING', font=("Helvetica", font_size), fg='red', bg=bg_color)
        label.pack()
        return window

    label = tk.Label(window, text=str(bd.bpm), font=("Helvetica", font_size), fg=font_color, bg=bg_color)
    label.pack()


    def update_label():
        if stop_event.is_set():
            return
        try:
            label.config(text=str(bd.bpm))
        except Exception:
            label.config(text='-')
        window.after(1000, update_label)  # Schedule next update after 1 second

    window.after(1000, update_label)  # Start updates
    return window

# Constants
BUFFER_SIZE = 256
CHANNELS = 1
FORMAT = pyaudio.paFloat32
METHOD = "default"
SAMPLE_RATE = 44100

# Add a global event to signal threads to stop
stop_event = threading.Event()

# Parse command line arguments
parser = argparse.ArgumentParser()
parser.add_argument("--list-devices", help="List all audio input devices", action="store_true")
parser.add_argument("--settings", help="Open settings window on start", action="store_true")
parser.add_argument("--debug", help="Enable debug logging", action="store_true")
args = parser.parse_args()

# configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
if args.debug:
    logging.getLogger().setLevel(logging.DEBUG)

if args.list_devices:
    device_detector = DeviceDetector()
    device_detector.list_audio_devices()
else:
    logging.info('Starting BPM overlay (args: settings=%s, debug=%s)', args.settings, args.debug)
    # Load config file
    with open('config.json', 'r') as f:
        config = json.load(f)

    # Create BeatDetector instances and resolve devices robustly
    beat_detectors = []
    p = pyaudio.PyAudio()
    for i, device in enumerate(config['input_devices']):
        try:
            resolved = resolve_device_index(p, device)
            if resolved is None:
                logging.warning("configured device #%d not found: name=%s id=%s", i, device.get('name'), device.get('id'))
                beat_detectors.append(None)
                config['input_devices'][i]['_resolved'] = None
                continue
        except Exception:
            logging.exception("Error resolving configured device #%d", i)
            beat_detectors.append(None)
            config['input_devices'][i]['_resolved'] = None
            continue
        # persist device name when missing for easier later resolution
        try:
            info = p.get_device_info_by_index(resolved)
            if not device.get('name'):
                config['input_devices'][i]['name'] = info.get('name')
                with open('config.json', 'w') as f:
                    json.dump(config, f, indent=4)
        except Exception:
            logging.exception("Error persisting device name for slot %d", i)

        try:
            bpm_scale = device.get('bpm_scale', 1.0)
            beat_detector = BeatDetector(METHOD, BUFFER_SIZE, SAMPLE_RATE, CHANNELS, FORMAT, resolved, bpm_scale=bpm_scale)
            beat_detector.start()
            beat_detectors.append(beat_detector)
        except Exception:
            logging.exception("Failed to start BeatDetector for slot %d (device index %s)", i, resolved)
            beat_detectors.append(None)
    p.terminate()


    root = tk.Tk()
    root.withdraw()  # Hide main window

    windows = []
    for i, bd in enumerate(beat_detectors):
        try:
            w = create_window(bd, config['input_devices'][i]['x'], config['input_devices'][i]['y'], config['font_size'], config['font_color'], config['bg_color'])
            windows.append(w)
        except Exception:
            logging.exception('Failed to create window for slot %d', i)
            windows.append(None)

    

    # Create BpmDisplay instance and start it
    bpm_display = BpmDisplay(beat_detectors)
    windows_visible = True

    def toggle_visibility():
        global windows_visible
        if not windows:
            return
        if windows_visible:
            for w in windows:
                try:
                    w.withdraw()
                except Exception:
                    pass
            windows_visible = False
        else:
            for w in windows:
                try:
                    w.deiconify(); w.lift()
                except Exception:
                    pass
            windows_visible = True

    def quit_from_tray():
        # called from tray menu on main thread
        stop_event.set()
        for bd in beat_detectors:
            if bd is not None:
                try:
                    bd.stop()
                except Exception:
                    pass
        try:
            root.quit()
        except Exception:
            root.destroy()

    # Settings window helper functions (use Tk main thread via root.after)
    def swap_device_slot(slot_index, new_cfg):
        """Replace the device at slot_index with new_cfg (dict), persist config, and restart detector."""
        global config, beat_detectors, windows
        # ensure beat_detectors list is long enough (defensive)
        while len(beat_detectors) <= slot_index:
            beat_detectors.append(None)
        # stop existing detector if present
        old = beat_detectors[slot_index]
        if old is not None:
            try:
                old.stop()
                old.join(timeout=1)
            except Exception:
                pass
        # update config
        config['input_devices'][slot_index] = new_cfg
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=4)
        # resolve and start new detector
        p_local = pyaudio.PyAudio()
        resolved = resolve_device_index(p_local, new_cfg)
        p_local.terminate()
        if resolved is None:
            print(f"Device for slot {slot_index} not found after remap")
            beat_detectors[slot_index] = None
            # ensure corresponding window is updated
            while len(windows) <= slot_index:
                windows.append(None)
            try:
                if windows[slot_index] is not None:
                    windows[slot_index].destroy()
            except Exception:
                logging.exception('Error destroying window for missing device')
            windows[slot_index] = create_window(None, new_cfg.get('x', 100), new_cfg.get('y', 100), config.get('font_size'), config.get('font_color'), config.get('bg_color'))
            return
        bpm_scale = new_cfg.get('bpm_scale', 1.0)
        bd = BeatDetector(METHOD, BUFFER_SIZE, SAMPLE_RATE, CHANNELS, FORMAT, resolved, bpm_scale=bpm_scale)
        bd.start()
        beat_detectors[slot_index] = bd
        # ensure window list is long enough and replace it
        while len(windows) <= slot_index:
            windows.append(None)
        if windows[slot_index] is not None:
            try:
                windows[slot_index].destroy()
            except Exception:
                logging.exception('Error destroying old window during swap')
        windows[slot_index] = create_window(bd, new_cfg.get('x', 100), new_cfg.get('y', 100), config.get('font_size'), config.get('font_color'), config.get('bg_color'))

    def open_settings_window():
        global config, beat_detectors
        try:
            # prevent multiple settings windows
            if getattr(root, '_settings_open', False):
                logging.debug('Settings window already open, skipping')
                return
            setattr(root, '_settings_open', True)

            logging.info('Opening Settings window')
            win = tk.Toplevel(root)
            win.title('Settings')
            # Improve default sizing and appearance
            try:
                win.minsize(720, 320)
                win.resizable(False, False)
                win.deiconify(); win.lift()
                # center the settings window roughly one-third from the top
                win.update_idletasks()
                w = win.winfo_width(); h = win.winfo_height()
                x = (win.winfo_screenwidth() - w) // 2
                y = (win.winfo_screenheight() - h) // 3
                win.geometry(f'+{x}+{y}')
                # do not force topmost; allow child dialogs to appear above
                # win.attributes('-topmost', True)
            except Exception:
                pass
            # handle window close to clear flag
            def on_close():
                try:
                    setattr(root, '_settings_open', False)
                except Exception:
                    pass
                try:
                    win.destroy()
                except Exception:
                    pass
            try:
                win.protocol('WM_DELETE_WINDOW', on_close)
            except Exception:
                pass
        except Exception:
            logging.exception('Failed to create settings window')
            try:
                setattr(root, '_settings_open', False)
            except Exception:
                pass
            return

        from tkinter import ttk, messagebox
        # Use a Treeview with columns for better UX
        tree = ttk.Treeview(win, columns=('slot', 'name', 'id', 'x', 'y', 'scale', 'status'), show='headings', selectmode='browse')
        tree.heading('slot', text='Slot')
        tree.heading('name', text='Name')
        tree.heading('id', text='Device ID')
        tree.heading('x', text='X')
        tree.heading('y', text='Y')
        tree.heading('scale', text='BPM Scale')
        tree.heading('status', text='Status')
        tree.column('slot', width=50, anchor='center')
        tree.column('name', width=220, anchor='w')
        tree.column('id', width=80, anchor='center')
        tree.column('x', width=60, anchor='center')
        tree.column('y', width=60, anchor='center')
        tree.column('scale', width=80, anchor='center')
        tree.column('status', width=100, anchor='center')
        tree.pack(fill='both', expand=True, padx=8, pady=8)

        # style tags for status coloring
        try:
            tree.tag_configure('resolved', foreground='green')
            tree.tag_configure('missing', foreground='gray30')
        except Exception:
            pass

        def refresh_list():
            # Clear existing rows
            for r in tree.get_children():
                tree.delete(r)
            for idx, d in enumerate(config['input_devices']):
                name = d.get('name') or ''
                device_id = d.get('id')
                x = d.get('x', '')
                y = d.get('y', '')
                scale = d.get('bpm_scale', 1.0)
                status = 'MISSING'
                tag = 'missing'
                if idx < len(beat_detectors) and beat_detectors[idx] is not None:
                    status = 'RESOLVED'; tag = 'resolved'
                tree.insert('', 'end', iid=str(idx), values=(idx, name, device_id, x, y, scale, status), tags=(tag,))


        def add_device():
            # list available devices and let user choose one
            avail = list_input_devices()
            sel_win = tk.Toplevel(win)
            sel_win.title('Choose device')
            sel_win.transient(win); sel_win.grab_set(); sel_win.focus()
            sel_win.resizable(False, False)

            lb = ttk.Treeview(sel_win, columns=('id', 'name', 'rate'), show='headings', selectmode='browse')
            lb.heading('id', text='ID'); lb.heading('name', text='Name'); lb.heading('rate', text='Rate')
            lb.column('id', width=60, anchor='center'); lb.column('name', width=300, anchor='w'); lb.column('rate', width=80, anchor='center')
            for a in avail:
                lb.insert('', 'end', iid=str(a['id']), values=(a['id'], a['name'], a['defaultSampleRate']))
            lb.pack(fill='both', expand=True, padx=8, pady=8)

            # default inputs
            frm = ttk.Frame(sel_win)
            frm.pack(fill='x', padx=8, pady=6)
            ttk.Label(frm, text='X').grid(row=0, column=0, sticky='e')
            e_x = ttk.Entry(frm); e_x.grid(row=0, column=1, sticky='w'); e_x.insert(0, '100')
            ttk.Label(frm, text='Y').grid(row=1, column=0, sticky='e')
            e_y = ttk.Entry(frm); e_y.grid(row=1, column=1, sticky='w'); e_y.insert(0, '100')
            ttk.Label(frm, text='BPM Scale').grid(row=2, column=0, sticky='e')
            e_scale = ttk.Entry(frm); e_scale.grid(row=2, column=1, sticky='w'); e_scale.insert(0, '1.0')

            btns = ttk.Frame(sel_win)
            btns.pack(fill='x', padx=8, pady=6)

            def confirm():
                sel = lb.selection()
                if not sel:
                    messagebox.showwarning('No device', 'Please select a device to add')
                    return
                dev_id = int(sel[0])
                dev = next((a for a in avail if a['id'] == dev_id), None)
                if not dev:
                    messagebox.showerror('Error', 'Selected device not found')
                    return
                # validate inputs
                try:
                    x = int(e_x.get()); y = int(e_y.get()); scale = float(e_scale.get())
                except Exception:
                    messagebox.showerror('Invalid input', 'X and Y must be integers; BPM scale a number')
                    return
                new_cfg = {'id': dev['id'], 'name': dev['name'], 'x': x, 'y': y, 'bpm_scale': scale}
                logging.info('Adding new device to config: %s', new_cfg)
                config['input_devices'].append(new_cfg)
                # keep detector/windows lists aligned by appending placeholders now
                beat_detectors.append(None)
                windows.append(None)
                with open('config.json', 'w') as f:
                    json.dump(config, f, indent=4)
                # refresh list (shows MISSING until slot is populated)
                refresh_list()
                # schedule starting the detector for the new slot
                slot = len(config['input_devices']) - 1
                try:
                    root.after(0, lambda s=slot, c=new_cfg: swap_device_slot(s, c))
                    sel_win.destroy(); refresh_list()
                except Exception:
                    logging.exception('Error scheduling swap_device_slot for new device')

            ttk.Button(btns, text='Add Device', command=confirm).pack(side='left')
            ttk.Button(btns, text='Cancel', command=lambda: sel_win.destroy()).pack(side='right')

        def remove_device():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning('No selection', 'Please select a slot to remove')
                return
            idx = int(sel[0])
            # stop detector if present
            if idx < len(beat_detectors) and beat_detectors[idx] is not None:
                try:
                    beat_detectors[idx].stop(); beat_detectors[idx].join(timeout=1)
                except Exception:
                    logging.exception('Error stopping detector during remove')
            # destroy associated window if present
            if idx < len(windows) and windows[idx] is not None:
                try:
                    windows[idx].destroy()
                except Exception:
                    logging.exception('Error destroying window during remove')
            # confirm
            if not messagebox.askyesno('Remove', f"Remove device slot {idx}?"):
                return
            # remove entries from config and lists (defensive)
            try:
                del config['input_devices'][idx]
            except Exception:
                logging.exception('Error deleting config entry during remove')
            if idx < len(beat_detectors):
                del beat_detectors[idx]
            if idx < len(windows):
                del windows[idx]
            with open('config.json', 'w') as f:
                json.dump(config, f, indent=4)
            refresh_list()

        def edit_device():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning('No selection', 'Please select a slot to edit')
                return
            idx = int(sel[0])
            d = config['input_devices'][idx]

            edit_win = tk.Toplevel(win)
            edit_win.title('Edit device')
            edit_win.transient(win); edit_win.grab_set(); edit_win.resizable(False, False)

            frm = ttk.Frame(edit_win, padding=8)
            frm.pack(fill='both', expand=True)
            ttk.Label(frm, text='X').grid(row=0, column=0, sticky='e')
            e_x = ttk.Entry(frm); e_x.grid(row=0, column=1, sticky='w'); e_x.insert(0, str(d.get('x', 100)))
            ttk.Label(frm, text='Y').grid(row=1, column=0, sticky='e')
            e_y = ttk.Entry(frm); e_y.grid(row=1, column=1, sticky='w'); e_y.insert(0, str(d.get('y', 100)))
            ttk.Label(frm, text='BPM Scale').grid(row=2, column=0, sticky='e')
            e_scale = ttk.Entry(frm); e_scale.grid(row=2, column=1, sticky='w'); e_scale.insert(0, str(d.get('bpm_scale', 1.0)))

            def save():
                try:
                    x = int(e_x.get()); y = int(e_y.get()); scale = float(e_scale.get())
                except Exception:
                    messagebox.showerror('Invalid input', 'X and Y must be integers; RPM scale must be a number')
                    return
                d['x'] = x; d['y'] = y; d['bpm_scale'] = scale
                with open('config.json', 'w') as f:
                    json.dump(config, f, indent=4)
                # remap in case id/name changed
                root.after(0, lambda: swap_device_slot(idx, d))
                edit_win.destroy(); refresh_list()

            btns = ttk.Frame(frm)
            btns.grid(row=3, column=0, columnspan=2, pady=(8,0))
            ttk.Button(btns, text='Save', command=save).pack(side='left')
            ttk.Button(btns, text='Cancel', command=lambda: edit_win.destroy()).pack(side='right')

        btn_frame = ttk.Frame(win, padding=8)
        btn_frame.pack(fill='x')
        ttk.Button(btn_frame, text='Add', command=add_device).pack(side='left', padx=(0,6))
        ttk.Button(btn_frame, text='Edit', command=edit_device).pack(side='left', padx=(0,6))
        ttk.Button(btn_frame, text='Remove', command=remove_device).pack(side='left', padx=(0,6))
        ttk.Button(btn_frame, text='Refresh', command=refresh_list).pack(side='left', padx=(0,6))
        ttk.Button(btn_frame, text='Close', command=lambda: (setattr(root, '_settings_open', False), win.destroy())).pack(side='right')

        # initial population
        refresh_list()

    # start tray icon (pystray) if available (after open_settings_window exists)
    try:
        from tray import Tray
        tray = Tray(root, open_settings_window, toggle_visibility, quit_from_tray)
        try:
            tray.start()
            logging.info('Tray icon started')
        except Exception:
            logging.exception('Failed to start tray icon')
            tray = None
    except Exception:
        logging.exception('pystray not available or failed to import')
        tray = None
    if tray is None:
        logging.warning('Tray icon not running (pystray missing or failed to start). Right-click tray features will be unavailable.')

    # Schedule settings on start if requested (do this after tray/Settings function exists)
    if args.settings:
        try:
            logging.info('Scheduling Settings window to open on startup')
            root.after(100, open_settings_window)
        except Exception:
            logging.exception('Failed to schedule settings window open')

    try:
        # bpm_display.display_bpms()
        root.mainloop()
    except KeyboardInterrupt:
        logging.info('KeyboardInterrupt, shutting down')
        stop_event.set()  # Signal threads to stop
        for beat_detector in beat_detectors:
            if beat_detector is not None:
                try:
                    beat_detector.stop()
                except Exception:
                    logging.exception('Error stopping beat detector')
        # stop tray icon if running
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                logging.exception('Error stopping tray icon')
        root.destroy()
    except Exception:
        logging.exception('Unhandled exception in mainloop')
        stop_event.set()
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                logging.exception('Error stopping tray icon')
        for bd in beat_detectors:
            if bd is not None:
                try:
                    bd.stop()
                except Exception:
                    logging.exception('Error stopping beat detector during exception')
        root.destroy()
        