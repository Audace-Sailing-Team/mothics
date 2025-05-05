import logging

class DisplayLogger(logging.Logger):
    """
    A Logger subclass that supports a `code=` kwarg for showing short debug codes
    on a TM1637 display via a directly attached display object.
    """
    def __init__(self, name, level=logging.NOTSET, display_iface=None):
        super().__init__(name, level)
        self.display_iface = display_iface  # should be a tm1637.TM1637 instance

    def _log_with_code(self, level, msg, args, code=None, **kwargs):
        super()._log(level, msg, args, **kwargs)

        if code and self.display_iface:
            try:
                text = str(code)[:4]
                self.display_iface.show(text)
            except Exception as e:
                self.warning(f"DisplayLogger: failed to show code '{code}': {e}")

    def info(self, msg, *args, code=None, **kwargs):
        self._log_with_code(logging.INFO, msg, args, code=code, **kwargs)

    def warning(self, msg, *args, code=None, **kwargs):
        self._log_with_code(logging.WARNING, msg, args, code=code, **kwargs)

    def error(self, msg, *args, code=None, **kwargs):
        self._log_with_code(logging.ERROR, msg, args, code=code, **kwargs)

    def debug(self, msg, *args, code=None, **kwargs):
        self._log_with_code(logging.DEBUG, msg, args, code=code, **kwargs)

    def critical(self, msg, *args, code=None, **kwargs):
        self._log_with_code(logging.CRITICAL, msg, args, code=code, **kwargs)
