import requests
import os
import sys
import logging
from datetime import datetime, timedelta
import dateutil.parser as parser 
import threading


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


def compute_status(timestamp, now=None, timeout_offline=60, timeout_noncomm=30):
    """
    Compute status of a remote unit by checking timestamp against current time.
    """
    
    # Get current time
    if now is None:
        now = datetime.now()
    
    # Convert timestamp to datetime object
    if isinstance(timestamp, str):
        timestamp = parser.parse(timestamp)
    if isinstance(now, str):
        now = parser.parse(now)
    
    # Compare timestamps
    if timestamp is None or now - timedelta(seconds=timeout_offline) > timestamp:
        return "offline"
    elif now - timedelta(seconds=timeout_noncomm) > timestamp:
        return "noncomm"
    else:
        return "online"

def format_duration(seconds):
    """
    Convert seconds into a string in the format "Hh Mm Ss".
    """
    if seconds is None:
        return "N/A"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}h:{minutes}m:{secs}s"


def download_file(url, dest_path):
    """Download a file from the URL if it doesn't already exist."""
    if os.path.exists(dest_path):
        return

    response = requests.get(url)
    response.raise_for_status()  # Raise an error for bad status codes

    # Create the destination directory if it doesn't exist
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    with open(dest_path, 'wb') as f:
        f.write(response.content)

    
def download_cdn(urls=None, outdir='static'):
    if urls is None:
        urls = [
            "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css",
            "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"
        ]
    
    for url in urls:
        # Extract the filename from the URL
        filename = os.path.basename(url)
        # Generate the destination path
        dest = os.path.join(outdir, filename)
        download_file(url, dest)


def check_cdn_availability(urls=None, outdir='static'):
    """
    Check whether the CDN files are available in the output directory.
    Returns a list of missing files (empty if all are present).
    """
    missing_files = []
    if urls is None:
        urls = [
            "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css",
            "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"
        ]
    
    for url in urls:
        filename = os.path.basename(url)
        dest = os.path.join(outdir, filename)
        if not os.path.exists(dest):
            missing_files.append(dest)
    
    return missing_files
