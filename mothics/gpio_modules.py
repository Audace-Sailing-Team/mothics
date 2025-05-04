"""
This module contains the base class and board-specific classes to
receive and push messages to hardware connected via the Raspberry Pi
GPIO pins.
"""
from datetime import datetime


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
    # TODO: move
    try:
        import Adafruit_DHT
    except:
        # TODO: fix error mgmt
        pass
    
    def __init__(self, gpio_pin, name="dht22", topic_root="env/",
                 poll_interval=5.0):
        super().__init__(name, topic_root, poll_interval)
        self.gpio_pin = gpio_pin

    def setup(self):
        # nothing to init for Adafruit_DHT
        pass

    def read(self):
        humidity, temperature = Adafruit_DHT.read_retry(
            Adafruit_DHT.DHT22, self.gpio_pin, retries=3, delay_seconds=2
        )
        if humidity is None or temperature is None:
            raise RuntimeError("DHT22 read failed")
        return {
            f"{self.topic_root}/temp": round(temperature, 2),
            f"{self.topic_root}/hum":  round(humidity, 1)
        }


# Registry
MODULE_REGISTRY = {
    "dht22": DHT22Module
}

def register_module(name: str, cls):
    MODULE_REGISTRY[name.lower()] = cls

