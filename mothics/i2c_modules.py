import time
import struct
import math
import logging
import board
import busio
from smbus2 import SMBus

from adafruit_dps310.basic import DPS310
import adafruit_bno055


from .comm_interface import *

class I2CModuleBase:
    """Base class for I2C-attached devices."""
    def __init__(self, name=None, topic_root=None, address=None, bus=1, poll_interval=0.1):
        self.name = name
        self.topic_root = topic_root.rstrip("/")
        self.address = address
        self.bus_num = bus
        self.poll_interval = poll_interval
        self.last_poll = None
        self.bus = None
        self.logger = logging.getLogger(f"I2CModule - {self.name}")

    def setup(self):
        try:
            self.bus = SMBus(self.bus_num)
            self.logger.info(f"{self.name}: opened I2C bus /dev/i2c-{self.bus_num}")
        except Exception as e:
            self.logger.critical(f"{self.name}: error opening I2C bus - {e}")
            raise

    def read(self) -> dict:
        raise NotImplementedError

    def cleanup(self):
        if self.bus:
            self.bus.close()
            self.logger.info(f"{self.name}: closed I2C bus")



# i2c_modules.py

# ---------------------------------------------------------
#   MPU6050
# ---------------------------------------------------------

class MPU6050Module(I2CModuleBase):
    """
    Modulo per MPU6050 (GY-521).
    Usa SMBus e lettura raw come nei test originali.
    """
    def __init__(self, name="mpu6050", topic_root="imu/mpu6050",
                 address=0x68, bus=1, poll_interval=0.05):
        super().__init__(name, topic_root, address, bus, poll_interval)

        # Mappa topic finale → valore
        self.field_map = {
            "accel_x": "ax",
            "accel_y": "ay",
            "accel_z": "az",
            "gyro_x": "gx",
            "gyro_y": "gy",
            "gyro_z": "gz",
            "temperature": "temp"
        }

    def setup(self):
        super().setup()
        try:
            # Wake-up + configurazione base
            self.bus.write_byte_data(self.address, 0x6B, 0x00)
            self.bus.write_byte_data(self.address, 0x1C, 0x00)  # ±2g
            self.bus.write_byte_data(self.address, 0x1B, 0x00)  # ±250°/s

            whoami = self.bus.read_byte_data(self.address, 0x75)
            self.logger.info(f"{self.name}: WHO_AM_I = {hex(whoami)}")
        except Exception as e:
            self.logger.error(f"{self.name}: setup error → {e}")

    def read(self):
        try:
            # Letture raw
            accel = self.bus.read_i2c_block_data(self.address, 0x3B, 6)
            ax = struct.unpack('>h', bytes(accel[0:2]))[0] / 16384.0 * 9.80665
            ay = struct.unpack('>h', bytes(accel[2:4]))[0] / 16384.0 * 9.80665
            az = struct.unpack('>h', bytes(accel[4:6]))[0] / 16384.0 * 9.80665

            gyro = self.bus.read_i2c_block_data(self.address, 0x43, 6)
            gx = struct.unpack('>h', bytes(gyro[0:2]))[0] / 131.0 * math.pi / 180.0
            gy = struct.unpack('>h', bytes(gyro[2:4]))[0] / 131.0 * math.pi / 180.0
            gz = struct.unpack('>h', bytes(gyro[4:6]))[0] / 131.0 * math.pi / 180.0

            temp_raw = struct.unpack('>h', bytes(
                self.bus.read_i2c_block_data(self.address, 0x41, 2)
            ))[0]
            temp = temp_raw / 340.0 + 36.53

            # Dizionario valori
            values = {
                "ax": ax, "ay": ay, "az": az,
                "gx": gx, "gy": gy, "gz": gz,
                "temp": temp
            }

            out = {}

            for full_topic in self.topics:
                key = full_topic.split("/")[-1]  # accel_x
                if key not in self.field_map:
                    continue

                attr = self.field_map[key]
                out[full_topic] = values[attr]

            return out

        except Exception as e:
            self.logger.warning(f"{self.name}: read error → {e}")
            return {}


# ---------------------------------------------------------
#   BNO055
# ---------------------------------------------------------

class AdafruitBNO055Module(I2CModuleBase):
    """Modulo per sensore Adafruit BNO055."""
    def __init__(self, name="bno055", topic_root="rm1/IMU", address=0x29, bus=1, poll_interval=0.1, pins=None):
        super().__init__(name, topic_root, address, bus, poll_interval)
        if pins is None:
            pins = (board.D5, board.D6)
        self.pins = pins
        self.bno = None

    def setup(self):
        try:
            self.bus = busio.I2C(*self.pins)
            self.bno = adafruit_bno055.BNO055_I2C(self.bus, address=self.address)
            self.logger.info(f"{self.name}: BNO055 initialized on I2C address {hex(self.address)}")
        except Exception as e:
            self.logger.critical(f"{self.name}: error initializing BNO055 - {e}")
            raise

    def read(self) -> dict:
        try:
            ax, ay, az = self.bno.acceleration
            gx, gy, gz = self.bno.gyro
            roll, pitch, yaw = self.bno.euler
        except Exception as e:
            self.logger.warning(f"{self.name}: read error: {e}")
            return {}

        # The sensor can return None if data isn't ready
        if ax is None or gx is None or roll is None:
            return {}

        out = {
            f"{self.topic_root}/ax": ax, f"{self.topic_root}/ay": ay, f"{self.topic_root}/az": az,
            f"{self.topic_root}/gx": gx, f"{self.topic_root}/gy": gy, f"{self.topic_root}/gz": gz,
            f"{self.topic_root}/roll" : roll, f"{self.topic_root}/pitch" : pitch, f"{self.topic_root}/yaw" : yaw
        }

        return out

    def cleanup(self):
        if self.bus:
            self.bus.deinit()
            self.logger.info(f"{self.name}: closed I2C bus")



i2c_module_registry = {
    "mpu6050": MPU6050Module,
    "bno055": AdafruitBNO055Module
}
