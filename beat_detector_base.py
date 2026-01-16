"""Abstract base class for beat detectors."""

import threading
from abc import ABC, abstractmethod


class BaseBeatDetector(threading.Thread, ABC):
    """
    Abstract base class for beat detection implementations.
    
    Subclasses must implement:
    - run(): Main thread loop for audio processing
    - stop(): Signal the thread to stop
    - bpm (property): Current BPM estimate
    """

    def __init__(self, input_device_index=None):
        super().__init__()
        self.input_device_index = input_device_index
        self._bpm = 0.0
        self.running = False

    @property
    def bpm(self) -> float:
        """Current BPM estimate."""
        return self._bpm

    @bpm.setter
    def bpm(self, value: float):
        self._bpm = value

    @abstractmethod
    def run(self):
        """Main thread loop - must be implemented by subclass."""
        pass

    @abstractmethod
    def stop(self):
        """Signal the thread to stop - must be implemented by subclass."""
        pass
