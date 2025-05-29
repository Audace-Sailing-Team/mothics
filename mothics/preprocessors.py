import math
import logging
from datetime import datetime

class BaseProcessor:
    def __init__(self, name=None):
        """
        Base-class for all pre-processing steps applied by Communicator.raw_data.
        Sub-classes override `apply`, but should **always** return the full
        (possibly-modified) data dictionary so that processors can be chained.
        """
        self.name = name
        self.enabled = True
        # Setup logger
        self.logger = logging.getLogger(f"Preprocessor - {name}")

    def apply(self, data):
        """
        data: dict -> {topic: [{timestamp: data}, ...], ...}
        """
        pass


class UnitConversion(BaseProcessor):
    """
    In–place conversion of numerical samples.

    conversions : dict
        {
          "rm2/wind/speed": ("rm2/wind/speed", lambda v: v * 1000),
          "temp_C":        ("temp_K",          lambda c: c + 273.15)
        }

    Notes
    -----
    - If source and destination are identical the value is *over-written*.
    - Each timestamp is processed only once (tracked by _last_done).
    """

    def __init__(self, conversions, *, name=None):
        if name is None:
            name = "UnitConversion"
        else:
            name = "UnitConversion" + '_'+ name            
        super().__init__(name)
        self.conversions   = conversions
        self._last_done    = {}        # {topic: newest timestamp processed}
        self.logger.info("Preprocessor initialized.")
        
    def apply(self, data):
        for topic, samples in list(data.items()):
            _, _, qty = topic.split("/")          # fast split, no validation

            rule = self.conversions.get(topic) or self.conversions.get(qty)
            if rule is None:
                continue

            dst_topic, func = rule
            last_done = self._last_done.get(topic)

            # 1. in-place
            if dst_topic == topic:
                for ts_val in samples:
                    (ts, val), = ts_val.items()
                    if last_done is not None and ts <= last_done:
                        continue                  # already converted
                    try:
                        ts_val[ts] = func(val)    # overwrite
                    except Exception:
                        pass                      # leave original on error
                    last_done = ts
                self._last_done[topic] = last_done
                continue                          # done with this topic

            # 2. source to different destination
            dest = data.setdefault(dst_topic, [])
            for ts_val in samples:
                (ts, val), = ts_val.items()
                if last_done is not None and ts <= last_done:
                    continue
                try:
                    dest.append({ts: func(val)})
                except Exception:
                    dest.append({ts: val})
                last_done = ts
            self._last_done[topic] = last_done

        return data


class AngleOffset(BaseProcessor):
    """
    Calibrate Euler angles by adding a static offset once per sample.
    It works with either layout:

    - three distinct scalar topics, e.g.
        imu/yaw, imu/pitch, imu/roll: value is a single float

    - one combined topic, e.g.
        imu/euler: value is (roll, pitch, yaw)
    """

    def __init__(self, offsets=None, *, name=None):
        """
        offsets : dict
         - key   = topic **or** quantity name ('yaw' / 'pitch' / 'roll')
         - value = scalar: offset for that scalar topic, 
                           or (dR, dP, dY) for a 3-tuple topic
        """
        if name is None:
            name = "AngleOffset"
        else:
            name = "AngleOffset" + '_'+ name            
        super().__init__(name)
        self.offsets    = offsets or {}
        self._last_done = {}              # {topic: newest timestamp processed}
        self.logger.info("Preprocessor initialized.")
        
    def set_offset(self, key, offset):
        """Change/insert an offset on the fly (key = topic or quantity)."""
        self.offsets[key] = offset

    def zero_now(self, key, current):
        """
        Treat *current* reading as zero.
         - key      = topic or quantity
         - current  = float  (scalar topic)
                or (roll, pitch, yaw)  (tuple topic)
        """
        if isinstance(current, (tuple, list)):
            self.offsets[key] = tuple(-x for x in current)
        else:
            self.offsets[key] = -current

    @staticmethod
    def _split(topic):
        try:
            mod, sen, qty = topic.split("/")
            return mod, sen, qty
        except ValueError:
            return None, None, topic     # tolerate malformed topic

    def apply(self, data):
        for topic, samples in list(data.items()):
            _, _, qty = self._split(topic)

            # look up offset by full topic OR by quantity name
            offset = self.offsets.get(topic)
            if offset is None:
                offset = self.offsets.get(qty)
            if offset is None:
                continue

            last_ts = self._last_done.get(topic)

            # 1. scalar topic
            if not isinstance(offset, (tuple, list)):
                for ts_val in samples:
                    (ts, val), = ts_val.items()
                    if last_ts is not None and ts <= last_ts:
                        continue
                    ts_val[ts] = val + offset
                    last_ts = ts
                self._last_done[topic] = last_ts
                continue

            # 2. tuple topic
            dR, dP, dY = offset
            for ts_val in samples:
                (ts, vec), = ts_val.items()
                if last_ts is not None and ts <= last_ts:
                    continue
                try:
                    r, p, y = vec
                    ts_val[ts] = (r + dR, p + dP, y + dY)
                except Exception:
                    pass                               # leave value as-is
                last_ts = ts
            self._last_done[topic] = last_ts

        return data    

    
class KalmanFilter(BaseProcessor):
    pass


available_processors = {'unit_conversion': UnitConversion, 'imu_calibration': AngleOffset}
