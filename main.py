import pyaudio
import argparse
import logging
import threading
import json
import tkinter as tk
import os
from beat_detector import BeatDetector, resolve_device_index, DeviceDetector
from ui import OverlayController, SettingsWindow

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
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        config = {'input_devices': [], 'font_size': 30, 'font_color': 'white', 'bg_color': 'black'}

    # Cleanup deprecated keys
    for d in config.get('input_devices', []):
        if 'bpm_scale' in d:
            del d['bpm_scale']

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
            config['input_devices'][i]['_resolved'] = True
        except Exception:
            logging.exception("Error persisting device name for slot %d", i)

        try:
            beat_detector = BeatDetector(METHOD, BUFFER_SIZE, SAMPLE_RATE, CHANNELS, FORMAT, resolved)
            beat_detector.start()
            beat_detectors.append(beat_detector)
        except Exception:
            logging.exception("Failed to start BeatDetector for slot %d (device index %s)", i, resolved)
            beat_detectors.append(None)
    p.terminate()


    root = tk.Tk()
    root.withdraw()  # Hide main window

    # Set app icon
    try:
        from tray import setup_app_icon
        setup_app_icon(root)
    except Exception:
        logging.exception('Failed to set app icon')

    # Initialize OverlayController
    overlay_controller = OverlayController(root, beat_detectors, config, stop_event)
    overlay_controller.create_windows()

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

    def sync_detectors_and_windows():
        # Stop all existing
        for bd in beat_detectors:
            if bd: 
                bd.stop()
                bd.join(timeout=1)
        
        beat_detectors.clear()
        
        # Re-init
        p = pyaudio.PyAudio()
        for i, device in enumerate(config['input_devices']):
            try:
                resolved = resolve_device_index(p, device)
                if resolved is None:
                    beat_detectors.append(None)
                    config['input_devices'][i]['_resolved'] = None
                    continue
                
                config['input_devices'][i]['_resolved'] = True
                bd = BeatDetector(METHOD, BUFFER_SIZE, SAMPLE_RATE, CHANNELS, FORMAT, resolved)
                bd.start()
                beat_detectors.append(bd)
            except Exception:
                beat_detectors.append(None)
        p.terminate()
        
        # Update controller
        overlay_controller.beat_detectors = beat_detectors
        overlay_controller.config = config
        overlay_controller.create_windows()

    def on_settings_save(new_config):
        global config
        config = new_config
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=4)
        
        sync_detectors_and_windows()

    def on_settings_change(new_config):
        global config
        config = new_config
        overlay_controller.config = config
        overlay_controller.update_appearance()

    settings_window = None
    def open_settings_window():
        global settings_window
        if settings_window:
            settings_window.open()
            return
        
        def on_close():
            global settings_window
            settings_window = None

        settings_window = SettingsWindow(root, config, on_settings_save, on_close, on_settings_change)
        settings_window.open()

    # start tray icon (pystray) if available
    try:
        from tray import Tray
        tray = Tray(root, open_settings_window, overlay_controller.toggle_visibility, quit_from_tray)
        try:
            tray.start()
            logging.info('Tray icon started')
        except Exception:
            logging.exception('Failed to start tray icon')
            tray = None
    except Exception:
        logging.exception('pystray not available or failed to import')
        tray = None

    if args.settings:
        root.after(100, open_settings_window)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        logging.info('KeyboardInterrupt, shutting down')
        stop_event.set()
        for beat_detector in beat_detectors:
            if beat_detector is not None:
                try:
                    beat_detector.stop()
                except Exception:
                    pass
        if tray is not None:
            try: tray.stop()
            except: pass
        root.destroy()
    except Exception:
        logging.exception('Unhandled exception in mainloop')
        stop_event.set()
        if tray is not None:
            try: tray.stop()
            except: pass
        for bd in beat_detectors:
            if bd is not None:
                try: bd.stop()
                except: pass
        root.destroy()
        