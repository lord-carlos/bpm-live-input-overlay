import tkinter as tk
from tkinter import ttk, messagebox, colorchooser
import logging
import json
from beat_detector import list_input_devices

class OverlayController:
    def __init__(self, root, beat_detectors, config, stop_event):
        self.root = root
        self.beat_detectors = beat_detectors
        self.config = config
        self.windows = []
        self.windows_visible = True
        self.stop_event = stop_event

    def create_windows(self):
        # Clear existing windows
        for w in self.windows:
            if w:
                try: w.destroy()
                except: pass
        self.windows = []

        for i, bd in enumerate(self.beat_detectors):
            try:
                cfg = self.config['input_devices'][i]
                w = self.create_single_window(bd, cfg)
                self.windows.append(w)
            except Exception:
                logging.exception('Failed to create window for slot %d', i)
                self.windows.append(None)

    def create_single_window(self, bd, cfg):
        x = cfg.get('x', 100)
        y = cfg.get('y', 100)
        # Use per-device text size if available, else global default
        font_size = cfg.get('text_size', self.config.get('font_size', 30))
        font_color = self.config.get('font_color', 'white')
        bg_color = self.config.get('bg_color', 'black')

        window = tk.Toplevel()
        window.overrideredirect(True)
        window.geometry(f'+{x}+{y}')
        window.attributes('-topmost', True)
        
        if bd is None:
            label = tk.Label(window, text='MISSING', font=("Helvetica", font_size), fg='red', bg=bg_color)
            label.pack()
            window._label = label
            return window

        label = tk.Label(window, text=str(bd.bpm), font=("Helvetica", font_size), fg=font_color, bg=bg_color)
        label.pack()

        # Store label for easy updates
        window._label = label

        def update_label():
            if self.stop_event and self.stop_event.is_set():
                return
            try:
                label.config(text=str(bd.bpm))
            except Exception:
                label.config(text='-')
            window.after(1000, update_label)

        window.after(1000, update_label)
        return window

    def update_appearance(self):
        """Update existing windows with new config values (X, Y, Size, Colors) without recreating them."""
        font_color = self.config.get('font_color', 'white')
        bg_color = self.config.get('bg_color', 'black')
        
        for i, bd in enumerate(self.beat_detectors):
            if i < len(self.windows) and self.windows[i]:
                cfg = self.config['input_devices'][i]
                x = cfg.get('x', 100)
                y = cfg.get('y', 100)
                font_size = cfg.get('text_size', self.config.get('font_size', 30))
                
                try:
                    self.windows[i].geometry(f'+{x}+{y}')
                    self.windows[i].config(bg=bg_color)
                    if hasattr(self.windows[i], '_label'):
                        # Ensure font_size is an int and valid
                        f_size = int(font_size) if font_size else 30
                        if f_size < 8: f_size = 8
                        self.windows[i]._label.config(
                            font=("Helvetica", f_size),
                            fg=font_color,
                            bg=bg_color
                        )
                except Exception as e:
                    logging.error(f"Error updating window appearance for slot {i}: {e}")

    def toggle_visibility(self):
        if not self.windows:
            return
        if self.windows_visible:
            for w in self.windows:
                try: w.withdraw()
                except: pass
            self.windows_visible = False
        else:
            for w in self.windows:
                try: w.deiconify(); w.lift()
                except: pass
            self.windows_visible = True
            
    def update_window_for_slot(self, slot_index, new_bd, new_cfg):
        # Ensure windows list is long enough
        while len(self.windows) <= slot_index:
            self.windows.append(None)
            
        # Destroy old
        if self.windows[slot_index]:
            try: self.windows[slot_index].destroy()
            except: pass
            
        # Create new
        self.windows[slot_index] = self.create_single_window(new_bd, new_cfg)
        
    def close_all(self):
        for w in self.windows:
            if w:
                try: w.destroy()
                except: pass
        self.windows = []


class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas = tk.Canvas(self, height=100, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )

        self.window_id = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Force the inner frame to match the canvas width
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.window_id, width=event.width)

class SettingsWindow:
    def __init__(self, root, config, on_save_callback, on_close_callback, on_change_callback=None):
        self.root = root
        self.config = config
        self.on_save = on_save_callback
        self.on_close = on_close_callback
        self.on_change = on_change_callback
        self.window = None
        self.entries = [] # List of dicts {name_var, x_var, y_var, size_var, ...}
        self._updating = False

    def open(self):
        if self.window:
            self.window.lift()
            return

        self.window = tk.Toplevel(self.root)
        self.window.title('Settings')
        self.window.geometry("650x300")
        self.window.minsize(600, 250)
        self.window.protocol('WM_DELETE_WINDOW', self.close)

        # Main layout
        main_frame = ttk.Frame(self.window, padding=10)
        main_frame.pack(fill='both', expand=True)

        # Header
        header_frame = ttk.Frame(main_frame)
        # Add right padding to approximate scrollbar width for alignment
        header_frame.pack(fill='x', pady=(0, 5), padx=(0, 17))
        
        # Fixed widths for alignment
        self.col_widths = [40, 200, 40, 60, 60, 60, 60, 70]
        cols = ["Slot", "Name", "ID", "X", "Y", "Size", "Status", "Action"]
        
        for i, (col, width) in enumerate(zip(cols, self.col_widths)):
            lbl = ttk.Label(header_frame, text=col, font=('Helvetica', 10, 'bold'), anchor='w')
            lbl.grid(row=0, column=i, padx=5, sticky='ew')
            header_frame.columnconfigure(i, minsize=width, weight=1 if col == "Name" else 0)

        # Scrollable list
        self.scroll_frame = ScrollableFrame(main_frame)
        self.scroll_frame.pack(fill='both', expand=True)
        
        self.refresh_list()

        # Global Appearance Section
        global_frame = ttk.LabelFrame(main_frame, text="Global Appearance", padding=10)
        global_frame.pack(fill='x', pady=(10, 0))
        
        ttk.Label(global_frame, text="Font Color:").pack(side='left', padx=5)
        self.font_color_btn = tk.Button(global_frame, width=10, command=lambda: self.pick_color('font_color'))
        self.font_color_btn.pack(side='left', padx=5)
        
        ttk.Label(global_frame, text="Background:").pack(side='left', padx=(20, 5))
        self.bg_color_btn = tk.Button(global_frame, width=10, command=lambda: self.pick_color('bg_color'))
        self.bg_color_btn.pack(side='left', padx=5)
        
        self.update_color_buttons()

        # Footer buttons
        btn_frame = ttk.Frame(main_frame, padding=(0, 10, 0, 0))
        btn_frame.pack(fill='x')
        
        ttk.Button(btn_frame, text="Add Device", command=self.add_device_dialog).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Save & Apply", command=self.save).pack(side='right', padx=5)
        ttk.Button(btn_frame, text="Close", command=self.close).pack(side='right', padx=5)

    def refresh_list(self):
        # Clear existing
        for widget in self.scroll_frame.scrollable_frame.winfo_children():
            widget.destroy()
        self.entries = []
        self._updating = True

        for i, dev in enumerate(self.config['input_devices']):
            row_frame = ttk.Frame(self.scroll_frame.scrollable_frame)
            row_frame.pack(fill='x', pady=2)
            
            for j, width in enumerate(self.col_widths):
                row_frame.columnconfigure(j, minsize=width, weight=1 if j==1 else 0)

            # Slot
            ttk.Label(row_frame, text=str(i), anchor='w').grid(row=0, column=0, padx=5, sticky='ew')
            
            # Name
            name_var = tk.StringVar(value=dev.get('name', ''))
            name_var.trace_add("write", lambda *args, idx=i: self.on_value_change(idx))
            ttk.Entry(row_frame, textvariable=name_var, state='readonly').grid(row=0, column=1, padx=5, sticky='ew')
            
            # ID
            ttk.Label(row_frame, text=str(dev.get('id', '?')), anchor='w').grid(row=0, column=2, padx=5, sticky='ew')
            
            # X
            x_var = tk.StringVar(value=str(dev.get('x', 100)))
            x_var.trace_add("write", lambda *args, idx=i: self.on_value_change(idx))
            ttk.Spinbox(row_frame, from_=0, to=4000, textvariable=x_var, width=5).grid(row=0, column=3, padx=5, sticky='ew')
            
            # Y
            y_var = tk.StringVar(value=str(dev.get('y', 100)))
            y_var.trace_add("write", lambda *args, idx=i: self.on_value_change(idx))
            ttk.Spinbox(row_frame, from_=0, to=4000, textvariable=y_var, width=5).grid(row=0, column=4, padx=5, sticky='ew')
            
            # Size
            size_var = tk.StringVar(value=str(dev.get('text_size', self.config.get('font_size', 30))))
            size_var.trace_add("write", lambda *args, idx=i: self.on_value_change(idx))
            ttk.Spinbox(row_frame, from_=8, to=200, textvariable=size_var, width=5).grid(row=0, column=5, padx=5, sticky='ew')
            
            # Status
            status = "OK" if dev.get('_resolved') is not None else "MISSING"
            lbl = ttk.Label(row_frame, text=status, anchor='w')
            lbl.grid(row=0, column=6, padx=5, sticky='ew')
            if status == "MISSING": lbl.configure(foreground='red')
            else: lbl.configure(foreground='green')

            # Remove Button
            ttk.Button(row_frame, text="Remove", command=lambda idx=i: self.remove_device(idx)).grid(row=0, column=7, padx=5, sticky='ew')

            self.entries.append({
                'name': name_var,
                'x': x_var,
                'y': y_var,
                'text_size': size_var
            })
        
        self._updating = False

    def on_value_change(self, index):
        if self._updating: return
        try:
            entry = self.entries[index]
            self.config['input_devices'][index]['name'] = entry['name'].get()
            self.config['input_devices'][index]['x'] = int(entry['x'].get() or 0)
            self.config['input_devices'][index]['y'] = int(entry['y'].get() or 0)
            self.config['input_devices'][index]['text_size'] = int(entry['text_size'].get() or 30)
            
            if self.on_change:
                self.on_change(self.config)
        except (ValueError, IndexError):
            pass

    def add_device_dialog(self):
        avail = list_input_devices()
        sel_win = tk.Toplevel(self.window)
        sel_win.title('Choose device')
        
        lb = ttk.Treeview(sel_win, columns=('id', 'name'), show='headings')
        lb.heading('id', text='ID'); lb.heading('name', text='Name')
        for a in avail:
            lb.insert('', 'end', values=(a['id'], a['name']))
        lb.pack(fill='both', expand=True)
        
        def confirm():
            sel = lb.selection()
            if not sel: return
            item = lb.item(sel[0])
            dev_id = item['values'][0]
            dev_name = item['values'][1]
            
            new_dev = {
                'id': dev_id,
                'name': dev_name,
                'x': 100,
                'y': 100,
                'text_size': self.config.get('font_size', 30)
            }
            self.config['input_devices'].append(new_dev)
            self.refresh_list()
            sel_win.destroy()
            
        ttk.Button(sel_win, text="Add", command=confirm).pack()

    def remove_device(self, index):
        if messagebox.askyesno("Confirm", "Remove this device?"):
            del self.config['input_devices'][index]
            self.refresh_list()

    def pick_color(self, key):
        """Open color picker dialog and update config."""
        current_color = self.config.get(key, 'white' if key == 'font_color' else 'black')
        result = colorchooser.askcolor(initialcolor=current_color, title=f"Choose {key.replace('_', ' ')}")
        if result[1]:  # result is ((R, G, B), "#hexcolor")
            self.config[key] = result[1]
            self.update_color_buttons()
            if self.on_change:
                self.on_change(self.config)

    def update_color_buttons(self):
        """Update the color button backgrounds to reflect current config."""
        font_c = self.config.get('font_color', 'white')
        bg_c = self.config.get('bg_color', 'black')
        
        # Determine contrasting text color for readability
        def contrast(color):
            if color.lower() in ['white', '#ffffff', '#fff']:
                return 'black'
            return 'white'
        
        self.font_color_btn.config(bg=font_c, text=font_c, fg=contrast(font_c))
        self.bg_color_btn.config(bg=bg_c, text=bg_c, fg=contrast(bg_c))

    def save(self):
        # Update config from entries
        for i, entry in enumerate(self.entries):
            try:
                self.config['input_devices'][i]['name'] = entry['name'].get()
                self.config['input_devices'][i]['x'] = int(entry['x'].get())
                self.config['input_devices'][i]['y'] = int(entry['y'].get())
                self.config['input_devices'][i]['text_size'] = int(entry['text_size'].get())
            except ValueError:
                messagebox.showerror("Error", f"Invalid values in row {i}")
                return

        self.on_save(self.config)

    def close(self):
        if self.window:
            self.window.destroy()
            self.window = None
        self.on_close()
