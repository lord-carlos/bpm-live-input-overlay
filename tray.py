import logging
import os
import threading
import pystray
from PIL import Image, ImageDraw


def _create_image(size=64, color1=(30, 144, 255), color2=(255, 255, 255)):
    # Simple circular icon with 'B' in the middle
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = size // 2
    draw.ellipse((0, 0, size, size), fill=color1)
    text = 'B'
    # Rough centering
    draw.text((size * 0.38, size * 0.18), text, fill=color2)
    return img


class Tray:
    def __init__(self, root, on_settings, on_toggle, on_quit):
        self.root = root
        self.on_settings = on_settings
        self.on_toggle = on_toggle
        self.on_quit = on_quit
        self.icon = None
        self.thread = None

    def _menu_settings(self, icon, item):
        # schedule on main thread
        try:
            logging.info('Tray: Settings selected')
            self.root.after(0, self.on_settings)
        except Exception:
            logging.exception('Error scheduling settings from tray')

    def _menu_toggle(self, icon, item):
        try:
            logging.info('Tray: Toggle display selected')
            self.root.after(0, self.on_toggle)
        except Exception:
            logging.exception('Error scheduling toggle from tray')

    def _menu_quit(self, icon, item):
        # schedule quit then stop icon
        try:
            logging.info('Tray: Quit selected')
            self.root.after(0, self.on_quit)
        except Exception:
            logging.exception('Error scheduling quit from tray')
        try:
            icon.stop()
        except Exception:
            pass

    def start(self):
        # prefer repo icon asset if provided (assets/icon.png or icon.png)
        image = None
        for candidate in (os.path.join('assets', 'icon.png'), 'icon.png'):
            try:
                if os.path.exists(candidate):
                    image = Image.open(candidate).convert('RGBA')
                    logging.info('Loaded tray icon from %s', candidate)
                    break
            except Exception:
                logging.exception('Failed to load tray icon from %s', candidate)

        if image is None:
            image = _create_image()
            logging.info('Using generated fallback tray icon')
        menu = pystray.Menu(
            # make Settings the default action so a click opens it
            pystray.MenuItem('Settings', self._menu_settings, default=True),
            pystray.MenuItem('Toggle display', self._menu_toggle),
            pystray.MenuItem('Quit', self._menu_quit),
        )
        self.icon = pystray.Icon('bpm-overlay', image, 'BPM Overlay', menu)
        # run in background thread
        self.thread = threading.Thread(target=self.icon.run, daemon=True)
        self.thread.start()

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
