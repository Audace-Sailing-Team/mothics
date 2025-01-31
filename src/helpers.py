import sys
import logging
from datetime import datetime, timedelta


def tipify(s):
    """
    Convert a string into the best matching type.

    Example:
    -------
        2 -> int
        2.32 -> float
        text -> str

    The only risk is if a variable is required to be float,
    but is passed without dot.

    Tests:
    -----
        print type(tipify("2.0")) is float
        print type(tipify("2")) is int
        print type(tipify("t2")) is str
        print map(tipify, ["2.0", "2"])
    """
    if '_' in s:
        return s
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s

    
def setup_logger(name, level=logging.INFO, fname=None, silent=False):
    """Logger with custom prefix"""

    logger = logging.getLogger()
    logger.setLevel(level)

    # Create console handler
    if fname is None:
        ch = logging.StreamHandler(sys.stdout)
    else:
        ch = logging.FileHandler(fname, mode='w')
    if silent:
        ch = logging.NullHandler()
        
    ch.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Add formatter to console handler
    ch.setFormatter(formatter)

    # Add console handler to logger
    logger.addHandler(ch)


def compute_status(timestamp, timeout_offline=60, timeout_noncomm=30):
    """
    Compute status of a remote unit by checking timestamp against current time.
    """

    # Get current time
    now = datetime.now()
    
    # Compare timestamps
    if timestamp is None or now - timedelta(seconds=timeout_offline) > timestamp:
        return "offline"
    elif now - timedelta(seconds=timeout_noncomm) > timestamp:
        return "noncomm"
    else:
        return "online"
