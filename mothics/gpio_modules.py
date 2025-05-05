"""
This module contains the base class and board-specific classes to
receive and push messages to hardware connected via the Raspberry Pi
GPIO pins.
"""
import time
import board
from datetime import datetime
import adafruit_dht

# GPIO interface base class

class GPIOModuleBase:
    """GPIO-attached device base interface."""
    def __init__(self, name, topic_root, poll_interval=2.0):
        """
        topic_root: e.g. 'rm1/env/dht22'
        Derived classes will append '/temp', '/hum' etc.
        """
        self.name = name
        self.topic_root = topic_root.rstrip("/")
        self.poll_interval = poll_interval
        self.last_poll = None
        """Datetime of last successful read."""

    def setup(self):
        pass
    
    def read(self) -> dict:
        """
        Returns { '<topic>': value, ... }  (already **typed**, not strings)
        """
        pass
    
    def cleanup(self):
        pass

    
# DHT22 (temperature/humidity module) interface

class DHT22Module(GPIOModuleBase):
    """
    DHT22 sensor module using CircuitPython's `adafruit_dht` library. `libgpiod2` is needed.
    """
    def __init__(self, pin, name="dht22", topic_root="env",
                 poll_interval=5.0):
        super().__init__(name, topic_root.rstrip("/"), poll_interval)
        self.gpio_pin = pin
        self.sensor = None

    def setup(self):
        # Convert integer pin to board.Dxx
        try:
            board_pin = getattr(board, f"D{self.gpio_pin}")
        except AttributeError:
            raise ValueError(f"Invalid GPIO pin: D{self.gpio_pin} not found on board")

        self.sensor = adafruit_dht.DHT22(board_pin)

    def read(self):
        try:
            temperature = self.sensor.temperature
            humidity = self.sensor.humidity

            if temperature is None or humidity is None:
                raise RuntimeError("Received None from sensor")

            return {
                f"{self.topic_root}/temp": round(temperature, 2),
                f"{self.topic_root}/hum":  round(humidity, 1)
            }

        except RuntimeError as e:
            # DHT sensors are noisy — allow transient failures
            raise RuntimeError(f"DHT22 read failed: {e}")
        except Exception as e:
            self.sensor.exit()
            raise e

    def cleanup(self):
        if self.sensor:
            self.sensor.exit()

            
# Registry
MODULE_REGISTRY = {
    "dht22": DHT22Module
}

def register_module(name: str, cls):
    MODULE_REGISTRY[name.lower()] = cls
