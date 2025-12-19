import logging
import os
import sys
import threading
import pystray
from PIL import Image, ImageDraw


def get_resource_path(filename):
    """Get the path to a bundled resource, works for both dev and PyInstaller."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        base_path = sys._MEIPASS
    else:
        # Running as script
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, filename)


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


def setup_app_icon(root):
    """Set the window icon for the root and all future Toplevels."""
    ico_path = get_resource_path('icon.ico')
    png_path = get_resource_path('icon.png')
    
    # For frozen exe, also check current working directory for user-provided icon
    if getattr(sys, 'frozen', False):
        cwd_ico = 'icon.ico'
        cwd_png = 'icon.png'
        if os.path.exists(cwd_ico):
            ico_path = cwd_ico
        if os.path.exists(cwd_png):
            png_path = cwd_png
    
    # Ensure ico exists if png exists on Windows
    if os.name == 'nt' and not os.path.exists(ico_path) and os.path.exists(png_path):
        try:
            img = Image.open(png_path)
            # Save ico in temp location for frozen exe
            if getattr(sys, 'frozen', False):
                import tempfile
                ico_path = os.path.join(tempfile.gettempdir(), 'bpm_overlay_icon.ico')
            else:
                ico_path = 'icon.ico'
            img.save(ico_path, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
            logging.info(f"Generated icon.ico at {ico_path}")
        except Exception:
            logging.exception("Failed to generate icon.ico")

    if os.path.exists(ico_path):
        try:
            # Set default icon for all future Toplevels
            root.iconbitmap(default=ico_path)
            logging.info(f"Set app icon from {ico_path}")
            return
        except Exception:
            try:
                root.iconbitmap(ico_path)
                return
            except Exception:
                logging.exception("Failed to set iconbitmap")
            
    # Fallback to png if ico fails or doesn't exist
    for candidate in (png_path, get_resource_path('icon.png'), 'icon.png'):
        if os.path.exists(candidate):
            try:
                from PIL import ImageTk
                img = Image.open(candidate)
                # Use a large enough size for the taskbar
                img_small = img.resize((32, 32), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img_small)
                # True makes it the default for all Toplevels
                root.iconphoto(True, photo)
                # Keep a reference to prevent garbage collection
                root._app_icon = photo
                logging.info(f"Set app icon from {candidate}")
                return
            except Exception:
                logging.exception(f"Failed to load icon from {candidate}")


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
        # Check for icon.ico first (Windows preference)
        image = None
        ico_path = get_resource_path('icon.ico')
        png_path = get_resource_path('icon.png')
        
        # For frozen exe, also check current working directory
        if getattr(sys, 'frozen', False):
            if os.path.exists('icon.ico'):
                ico_path = 'icon.ico'
            if os.path.exists('icon.png'):
                png_path = 'icon.png'
        
        # If on Windows and no ico but png exists, convert it
        if os.name == 'nt' and not os.path.exists(ico_path) and os.path.exists(png_path):
            try:
                img = Image.open(png_path)
                if getattr(sys, 'frozen', False):
                    import tempfile
                    ico_path = os.path.join(tempfile.gettempdir(), 'bpm_overlay_tray.ico')
                else:
                    ico_path = 'icon.ico'
                img.save(ico_path, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
                logging.info('Converted icon.png to icon.ico for Windows tray at %s', ico_path)
            except Exception:
                logging.exception('Failed to convert icon.png to icon.ico')

        # Try loading ico first
        if os.path.exists(ico_path):
             try:
                image = Image.open(ico_path)
                logging.info('Loaded tray icon from %s', ico_path)
             except Exception:
                 logging.exception('Failed to load %s', ico_path)

        # Fallback to png
        if image is None:
            for candidate in (png_path, get_resource_path('icon.png'), 'icon.png'):
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
