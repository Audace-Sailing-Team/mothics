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
    Calibrate Euler angles by adding a static offset once per **new** sample.
    Handles either 3-tuple topic (roll, pitch, yaw) or three scalar topics.
    """

    def __init__(self, offsets=None, *, name=None):
        super().__init__(name or "AngleOffset")
        if offsets is None:
            offsets = {
            'rm1/imu/yaw':   0.0,
            'rm1/imu/pitch': 0.0,
            'rm1/imu/roll':  0.0,
            }
        self.offsets      = offsets
        self._last_ts     = {}   # topic → newest timestamp processed
        self._latest_raw  = {}   # topic → last **raw** value seen

    def set_offset(self, topic, offset):
        """Set/replace an offset at runtime."""
        self.offsets[topic] = offset
        self.logger.info("offset[%s] = %s", topic, offset)

    def calibrate(self, topics=None):
        """
        Make the most-recent *raw* reading of each selected topic the new zero.

        Parameters
        ----------
        topics : iterable[str] | None
            • full MQTT topic(s)  → "rm1/imu/yaw"
            • OR quantity name(s) → "yaw", "pitch", "roll"
            • None                → every topic we have cached in `_latest_raw`
        """
        # ---------- 1. Build the effective topic list ---------------------
        if topics is None:
            # default: all topics for which we have raw data
            topics = list(self._latest_raw.keys())
        else:
            full_topics   = []
            short_names   = []
            for t in topics:
                (full_topics if "/" in t else short_names).append(t)

            # expand each short name into matching full topics
            for qty in short_names:
                for full in self._latest_raw.keys():
                    if full.rsplit("/", 1)[-1] == qty:
                        full_topics.append(full)

            topics = full_topics

        # ---------- 2. Apply zeroing -------------------------------------
        for topic in topics:
            raw_val = self._latest_raw.get(topic)
            if raw_val is None:
                continue                    # nothing received yet

            if isinstance(raw_val, (tuple, list)):
                self.offsets[topic] = tuple(-x for x in raw_val)
            else:
                self.offsets[topic] = -raw_val

        if topics:
            self.logger.info("IMU zeroed for topics: %s", ", ".join(topics))
        else:
            self.logger.warning("calibrate(): no matching topics found")

    def reset_offsets(self):
        """
        Set the offset of the given topics back to **zero**.
        If `topics` is None, reset every topic for which an offset exists.
        """
        topics = self.offsets.keys()
        for topic in topics:
            raw = self._latest_raw.get(topic)
            if isinstance(raw, (tuple, list)):
                self.offsets[topic] = (0.0, 0.0, 0.0)
            else:
                self.offsets[topic] = 0.0
        self.logger.info("Offsets reset for: %s", ", ".join(topics))
        
    @staticmethod
    def _split(topic):
        try:
            return topic.split("/", 2)           # (module, sensor, qty)
        except ValueError:
            return (None, None, topic)

    def apply(self, data):
        for topic, samples in list(data.items()):
            _, _, qty = self._split(topic)

            offset = self.offsets.get(topic)
            if offset is None:
                offset = self.offsets.get(qty)

            # Continue if topic has no offset
            if offset is None:
                continue
            
            last_ts = self._last_ts.get(topic)

            # scalar topic
            if not isinstance(offset, (tuple, list)):
                for ts_val in samples:
                    (ts, val), = ts_val.items()
                    self._latest_raw[topic] = val          # remember raw
                    if last_ts is not None and ts <= last_ts:
                        continue                           # already done
                    ts_val[ts] = val + offset
                    last_ts = ts
                self._last_ts[topic] = last_ts
                continue

            # tuple topic
            dR, dP, dY = offset
            for ts_val in samples:
                (ts, vec), = ts_val.items()
                self._latest_raw[topic] = vec              # remember raw
                if last_ts is not None and ts <= last_ts:
                    continue
                try:
                    r, p, y = vec
                    ts_val[ts] = (r + dR, p + dP, y + dY)
                except Exception:
                    pass
                last_ts = ts
            self._last_ts[topic] = last_ts

        return data

    
class KalmanFilter(BaseProcessor):
    pass


available_processors = {'unit_conversion': UnitConversion, 'imu_calibration': AngleOffset}
