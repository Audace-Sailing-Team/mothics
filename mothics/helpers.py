import requests
import os
import math
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

def check_internet_connectivity(test_url="https://www.google.com", timeout=5):
    """
    Checks for an active internet connection by sending a HEAD request to a well-known website.
    
    Args:
        test_url (str): The URL to test connectivity.
        timeout (int): The timeout for the request in seconds.
        
    Returns:
        bool: True if the internet is available, False otherwise.
    """
    try:
        response = requests.head(test_url, timeout=timeout)
        return response.status_code == 200
    except requests.RequestException as e:
        return False

def deg2num(lat_deg, lon_deg, zoom):
    """Convert latitude and longitude to tile numbers."""
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    return xtile, ytile

def download_tiles(lat_range, lon_range, zoom_levels, output_dir="static/tiles", timeout=5):
    """
    Downloads and stores OpenStreetMap tiles for a specified geographic
    bounding box and zoom levels.

    Parameters:
        lat_range (tuple): A tuple of two floats (lat_min, lat_max)
    defining the latitude bounds.
        lon_range (tuple): A tuple of two floats (lon_min, lon_max)
    defining the longitude bounds.
        zoom_levels (iterable): A list or range of integer zoom levels to
    download tiles for (e.g., range(12, 16)).
        output_dir (str): Path to the local directory where tiles should
    be stored, following the convention {z}/{x}/{y}.png.

    Overly large bounding boxes or zoom levels may result in high
    numbers of downloads and can be rate-limited by OSM.

    """

    headers = {
        "User-Agent": "MothicsTileFetcher/1.0"
    }
    
    for zoom in zoom_levels:
        x_start, y_start = deg2num(lat_range[1], lon_range[0], zoom)
        x_end, y_end = deg2num(lat_range[0], lon_range[1], zoom)

        for x in range(x_start, x_end + 1):
            for y in range(y_start, y_end + 1):
                url = f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
                tile_path = os.path.join(output_dir, f"{zoom}/{x}/{y}.png")

                if not os.path.exists(tile_path):
                    os.makedirs(os.path.dirname(tile_path), exist_ok=True)
                    try:
                        response = requests.get(url, timeout=timeout, headers=headers)
                        if response.status_code == 200:
                            with open(tile_path, 'wb') as f:
                                f.write(response.content)
                    except Exception as e:
                        print(f"Error downloading {url}: {e}")

def list_required_tiles(lat_range, lon_range, zoom_levels):
    """
    Computes a list of all tile coordinates (z, x, y) required to cover the specified bounding box.

    Parameters:
        lat_range (tuple): Latitude bounds as (min_lat, max_lat)
        lon_range (tuple): Longitude bounds as (min_lon, max_lon)
        zoom_levels (iterable): Zoom levels to include, e.g., [12, 13, 14]

    Returns:
        List[Tuple[int, int, int]]: A flat list of (z, x, y) tile coordinates
    """
    tiles = []
    lat_min, lat_max = min(lat_range), max(lat_range)
    lon_min, lon_max = min(lon_range), max(lon_range)

    for z in zoom_levels:
        x_start, y_start = deg2num(lat_max, lon_min, z)
        x_end, y_end = deg2num(lat_min, lon_max, z)

        for x in range(x_start, x_end + 1):
            for y in range(y_start, y_end + 1):
                tiles.append((z, x, y))

    return tiles                        
