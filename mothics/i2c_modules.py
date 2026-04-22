import time
import struct
import math
import logging
import board
import busio
from smbus2 import SMBus

from adafruit_dps310.basic import DPS310
from BNO08x import BNO08x

from .comm_interface import *

class I2CModuleBase:
    """Base class for I2C-attached devices."""
    def __init__(self, name, topic_root, address, bus=1, poll_interval=0.1):
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
                 address=0x68, bus=1, topics=None, poll_interval=0.05):
        super().__init__(name, topic_root, address, bus, poll_interval)

        self.topics = topics

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
#   DPS310
# ---------------------------------------------------------

class DPS310Module(I2CModuleBase):
    """
    Modulo per sensore barometrico DPS310.
    Usa la libreria Adafruit come nei test originali.
    """
    def __init__(self, name="dps310", topic_root="env/dps310",
                 address=0x77, bus=1, poll_interval=0.2, topics=None):
        super().__init__(name, topic_root, address, bus, poll_interval)
        self.i2c = None
        self.sensor = None
        self.topics = topics

        self.field_map = {
            "pressure": "pressure",
            "temperature": "temperature"
        }

    def setup(self):
        super().setup()
        try:
            # Adafruit DPS310 usa busio.I2C, non SMBus
            self.i2c = busio.I2C(board.SCL, board.SDA)
            self.sensor = DPS310(self.i2c)
            self.logger.info(f"{self.name}: DPS310 inizializzato")
        except Exception as e:
            self.logger.error(f"{self.name}: setup error → {e}")

    def read(self):
        try:
            pressure = self.sensor.pressure
            temp = self.sensor.temperature

            values = {
                "pressure": pressure,
                "temperature": temp
            }

            out = {}

            for full_topic in self.topics:
                key = full_topic.split("/")[-1]
                if key not in self.field_map:
                    continue

                out[full_topic] = values[self.field_map[key]]

            return out

        except Exception as e:
            self.logger.warning(f"{self.name}: read error → {e}")
            return {}




# ---------------------------------------------------------
#   BNO08x (driver C++ via pybind11)
# ---------------------------------------------------------

class BNO08xModule(I2CModuleBase):
    """
    Modulo per IMU BNO08x usando driver C++ via pybind11.
    Usa readBlock() per ottenere tutti i dati in un'unica chiamata.
    """
    def __init__(self, name="bno08x", topic_root="imu/bno08x",
                 address=0x4A, bus=1, poll_interval=0.02, topics=None,
                 period_us=10000):
        # NON apriamo SMBus → ma manteniamo i parametri base
        super().__init__(name, topic_root, address, bus, poll_interval)
        self.bno = None
        self.period_us = period_us
        # Se topics è una lista di topic COMPLETI → usali così come sono
        self.topics = topics  # lista completa, es: rm3/imu/accel_x

        # Mappa topic finale → attributo del blocco
        self.field_map = {
            "accel_x": "ax", "accel_y": "ay", "accel_z": "az",
            "gyro_x": "gx", "gyro_y": "gy", "gyro_z": "gz",
            "mag_x": "mx", "mag_y": "my", "mag_z": "mz",
            "quat_w": "qw", "quat_x": "qx", "quat_y": "qy", "quat_z": "qz",
            "linacc_x": "lax", "linacc_y": "lay", "linacc_z": "laz",
            "grav_x": "gvx", "grav_y": "gvy", "grav_z": "gvz",
            "girot_w": "giw", "girot_x": "gix", "girot_y": "giy", "girot_z": "giz"
        }

    def setup(self):
        # NON chiamare super().setup() → evita apertura SMBus
        try:
            # Il driver apre direttamente /dev/i2c-X
            self.bno = BNO08x(f"/dev/i2c-{self.bus_num}", self.address)
            self.bno.begin()

            # Abilita i sensori necessari
            self.bno.enableAccelerometer(self.period_us)
            self.bno.enableGyroscope(self.period_us)
            self.bno.enableMagnetometer(self.period_us)
            self.bno.enableRotationVector(self.period_us)
            self.bno.enableLinearAcceleration(self.period_us)
            self.bno.enableGravity(self.period_us)
            self.bno.enableGameRotationVector(self.period_us)
            self.bno.enableGyroIntegratedRotation(self.period_us)

            # Warm-up
            for _ in range(10):
                self.bno.poll()
                time.sleep(0.005)

            self.logger.info(f"{self.name}: BNO08x inizializzato")

        except Exception as e:
            self.logger.error(f"{self.name}: setup error → {e}")

    def read(self):
        try:
            self.bno.poll()
            blk = self.bno.readBlock()
            if blk is None:
                return {}

            out = {}

            for full_topic in self.topics:
                # es: rm3/imu/accel_x → accel_x
                key = full_topic.split("/")[-1]

                if key not in self.field_map:
                    continue

                attr = self.field_map[key]
                value = getattr(blk, attr, None)

                if value is not None:
                    out[full_topic] = value

            return out

        except Exception as e:
            self.logger.warning(f"{self.name}: read error → {e}")
            return {}


    def cleanup(self):
        # Il driver non richiede chiusura esplicita
        pass

i2c_module_registry = {
    "mpu6050": MPU6050Module,
    "dps310": DPS310Module,
    "bno08x": BNO08xModule
}
