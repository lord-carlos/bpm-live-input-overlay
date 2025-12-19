"""
MIDI Clock output module for sending BPM synchronization signals.

Implements standard MIDI Clock protocol (24 pulses per quarter note).
"""

import threading
import time
import logging

try:
    import mido
    MIDO_AVAILABLE = True
except ImportError:
    MIDO_AVAILABLE = False
    logging.warning("mido library not available. MIDI Clock output disabled.")


def list_midi_ports():
    """
    List all available MIDI output ports.
    
    Returns:
        List of port name strings, or empty list if mido unavailable.
    """
    if not MIDO_AVAILABLE:
        return []
    
    try:
        ports = mido.get_output_names()
        logging.debug(f"Available MIDI ports: {ports}")
        return ports
    except Exception:
        logging.exception("Failed to list MIDI ports")
        return []


class MIDIClockSender:
    """
    Sends MIDI Clock messages at 24 PPQN (pulses per quarter note) based on BPM.
    
    Runs in a background thread with drift-compensated timing.
    """
    
    def __init__(self, port_name=None):
        """
        Initialize MIDI Clock sender.
        
        Args:
            port_name: Name of MIDI output port, or None to skip initialization
        """
        self.port = None
        self.port_name = port_name
        self.bpm = 120.0
        self.running = False
        self.started = False
        self.thread = None
        self._lock = threading.Lock()
        
        if port_name and MIDO_AVAILABLE:
            self._open_port(port_name)
    
    def _open_port(self, port_name):
        """Open MIDI output port."""
        try:
            self.port = mido.open_output(port_name)
            self.port_name = port_name
            logging.info(f"MIDI Clock: Opened port '{port_name}'")
        except Exception:
            logging.exception(f"MIDI Clock: Failed to open port '{port_name}'")
            self.port = None
            self.port_name = None
    
    def set_bpm(self, bpm):
        """
        Update the BPM for clock output.
        
        Args:
            bpm: Beats per minute (can be fractional, e.g., 125.5)
        """
        with self._lock:
            if bpm != self.bpm:
                old_bpm = self.bpm
                self.bpm = float(bpm)
                logging.debug(f"MIDI Clock: BPM changed from {old_bpm:.2f} to {self.bpm:.2f}")
    
    def _calculate_interval(self):
        """
        Calculate time between MIDI clock pulses in seconds.
        
        Returns:
            Interval in seconds (60 / (BPM * 24))
        """
        with self._lock:
            return 60.0 / (self.bpm * 24.0)
    
    def _clock_loop(self):
        """
        Background thread loop that sends MIDI clock messages.
        Uses drift compensation for accurate timing.
        """
        next_tick = time.perf_counter()
        
        while self.running:
            if not self.port:
                # Port was disconnected
                logging.debug("MIDI Clock: Port not available, exiting clock loop")
                break
            
            interval = self._calculate_interval()
            now = time.perf_counter()
            
            if now >= next_tick:
                try:
                    self.port.send(mido.Message('clock'))
                    next_tick += interval  # Drift compensation
                except Exception:
                    logging.exception("MIDI Clock: Failed to send clock message")
                    # Port likely disconnected
                    self.port = None
                    break
            else:
                # Sleep for a fraction of the interval to reduce CPU usage
                sleep_time = max(0.0001, (next_tick - now) * 0.5)
                time.sleep(sleep_time)
        
        logging.debug("MIDI Clock: Clock loop exited")
    
    def start(self):
        """
        Start sending MIDI clock messages.
        Sends MIDI Start message and begins clock thread.
        """
        if not MIDO_AVAILABLE:
            logging.warning("MIDI Clock: Cannot start - mido not available")
            return
        
        if not self.port:
            logging.warning(f"MIDI Clock: Cannot start - port '{self.port_name}' not open")
            return
        
        if self.running:
            logging.debug("MIDI Clock: Already running")
            return
        
        try:
            self.port.send(mido.Message('start'))
            logging.info(f"MIDI Clock: Sent START message at {self.bpm:.2f} BPM")
            self.started = True
        except Exception:
            logging.exception("MIDI Clock: Failed to send start message")
            self.port = None
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._clock_loop, daemon=True, name="MIDIClock")
        self.thread.start()
        logging.info("MIDI Clock: Started clock thread")
    
    def stop(self):
        """
        Stop sending MIDI clock messages.
        Sends MIDI Stop message and terminates clock thread.
        """
        if not self.running:
            return
        
        self.running = False
        
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None
        
        if self.port and self.started:
            try:
                self.port.send(mido.Message('stop'))
                logging.info("MIDI Clock: Sent STOP message")
                self.started = False
            except Exception:
                logging.exception("MIDI Clock: Failed to send stop message")
        
        logging.info("MIDI Clock: Stopped")
    
    def close(self):
        """Close the MIDI port and clean up resources."""
        self.stop()
        
        if self.port:
            try:
                self.port.close()
                logging.info(f"MIDI Clock: Closed port '{self.port_name}'")
            except Exception:
                logging.exception("MIDI Clock: Failed to close port")
            self.port = None
    
    def is_running(self):
        """Check if MIDI clock is currently running."""
        return self.running and self.port is not None
