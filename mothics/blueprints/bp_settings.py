from flask import Blueprint, render_template, jsonify, request, current_app
import json
from .settings_registry import SETTINGS_REGISTRY
from ..helpers import tipify, list_required_tiles, download_tiles, check_cdn_availability, download_cdn, check_internet_connectivity

settings_bp = Blueprint("settings", __name__)

def lookup_config_value(path, cfg):
    ref = cfg
    for key in path:
        ref = ref.get(key, {})
    return ref if ref != {} else ""

def parse_value(raw, typ):
    if typ == "int":
        return int(raw)
    if typ == "float":
        return float(raw)
    if typ == "bool":
        return raw.lower() in ["true", "1", "yes"]
    if typ == "taglist":
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        return [x.strip() for x in raw.split(",") if x.strip()]
    if typ == "kvtable":
        if isinstance(raw, dict):
            return raw
        return json.loads(raw)
    if typ == "text":
        return str(raw)
    return str(raw)

def apply_runtime_setter(spec, value, mgr):
    """
    1) Apply the live effect (real_time_setter or setter_name)
    2) Mirror the new value into current_app.config["CONFIG_DATA"]
    """
    # 1) Live effect
    if "real_time_setter" in spec:
        result = spec["real_time_setter"](value, mgr)
    else:
        setter_name = spec.get("setter_name")
        setter_fn = current_app.config["SETTERS"].get(setter_name)
        if not setter_fn:
            raise RuntimeError(f"Setter '{setter_name}' not found.")
        result = setter_fn(value)

    # 2) Persist into CONFIG_DATA
    cfg = current_app.config["CONFIG_DATA"]
    node = cfg
    for key in spec["config_path"][:-1]:
        node = node.setdefault(key, {})
    node[spec["config_path"][-1]] = value

    return result

@settings_bp.route("/settings", methods=["GET", "POST"])
def settings():
    mgr = current_app.config["SYSTEM_MGR"]
    success_message = None
    error_message = None

    if request.method == "POST":
        for field, raw_value in request.form.items():
            if field not in SETTINGS_REGISTRY:
                continue

            spec = SETTINGS_REGISTRY[field]
            try:
                # Button‐type settings just fire and mirror (value is ignored)
                if spec.get("type") == "button":
                    apply_runtime_setter(spec, None, mgr)
                    success_message = spec.get("log_success", "").format(value="")
                    continue

                # Parse & validate
                value = parse_value(raw_value, spec["type"])
                if "validate" in spec and not spec["validate"](value):
                    raise ValueError(f"Validation failed for {field} = {value}")

                # Apply & persist
                apply_runtime_setter(spec, value, mgr)
                success_message = spec.get("log_success",
                                           f"Updated {field} to {value}").format(value=value)

            except Exception as e:
                error_message = f"Error processing {field}: {e}"

    # Always rebuild current values from CONFIG_DATA
    cfg_data = current_app.config["CONFIG_DATA"]
    current_vals = {
        k: lookup_config_value(field["config_path"], cfg_data)
        for k, field in SETTINGS_REGISTRY.items()
    }

    return render_template(
        "settings.html",
        success=success_message,
        error=error_message,
        current=current_vals,
        registry=SETTINGS_REGISTRY
    )

@settings_bp.route("/api/estimate_tiles")
def estimate_tiles():
    bbox = request.args.get("bbox", "")
    zooms = request.args.get("zooms", "")

    try:
        lat_min, lon_min, lat_max, lon_max = map(float, bbox.split(","))
        zoom_levels = list(map(int, zooms.split(",")))
        tiles = list_required_tiles((lat_min, lat_max), (lon_min, lon_max), zoom_levels)
        count = len(tiles)
        size_mb = count * 20 / 1024  # 20 kB per tile, rough average
        return jsonify({"count": count, "size_mb": round(size_mb, 1)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@settings_bp.route("/api/download_tiles", methods=["POST"])
def download_tiles_api():
    """
    Download map tiles for a given bbox & zoom levels.
    Logs the count of tiles requested and saved, and returns JSON:
      { "requested": <total_tiles>, "saved": <tiles_actually_saved> }
    """
    bbox = request.args.get("bbox", "")
    zooms = request.args.get("zooms", "")

    try:
        # 1) Parse inputs
        lat_min, lon_min, lat_max, lon_max = map(float, bbox.split(","))
        zoom_levels = list(map(int, zooms.split(",")))

        # 2) Compute which tiles we need
        tiles = list_required_tiles(
            lat_range=(lat_min, lat_max),
            lon_range=(lon_min, lon_max),
            zoom_levels=zoom_levels
        )
        total = len(tiles)
        tile_dir = current_app.config["CONFIG_DATA"]["files"]["tile_dir"]

        current_app.logger.info(
            f"Requesting download of {total} tiles to '{tile_dir}'"
        )

        # 3) Perform the download
        saved = download_tiles(
            lat_range=(lat_min, lat_max),
            lon_range=(lon_min, lon_max),
            zoom_levels=zoom_levels,
            output_dir=tile_dir
        )

        # 4) Log the result
        current_app.logger.info(
            f"Tile download complete: {saved} of {total} tiles saved to '{tile_dir}'"
        )

        # 5) Return counts
        return jsonify({"requested": total, "saved": saved})

    except ValueError as ve:
        current_app.logger.error(f"Invalid parameters for download_tiles: {ve}")
        return jsonify({"error": "Invalid bbox or zooms format"}), 400

    except Exception as e:
        current_app.logger.error(f"Error during tile download: {e}")
        return jsonify({"error": str(e)}), 500
    
    
@settings_bp.route("/api/download_cdns", methods=["POST"])
def download_cdns_api():
    """
    Download any missing CDN files configured under [webapp].cdns → files/{cdn_dir}.
    Returns JSON: { "saved": <number_of_new_files> } or { "error": "<msg>" }.
    """
    # 1) Read URLs & output directory from our in-memory config
    cfg      = current_app.config["CONFIG_DATA"]
    cdn_urls = cfg.get("webapp", {}).get("cdns") or []
    cdn_dir  = cfg.get("files", {}).get("cdn_dir")

    if not cdn_urls:
        # Nothing to download
        return jsonify({"saved": 0})

    # 2) Determine which files are missing
    missing_before = check_cdn_availability(urls=cdn_urls, outdir=cdn_dir)
    if not missing_before:
        # All already present
        return jsonify({"saved": 0})

    # 3) Must have internet
    if not check_internet_connectivity():
        return jsonify({"error": "Internet connectivity unavailable"}), 500

    # 4) Download & then re-check what’s still missing
    before_set = set(missing_before)
    download_cdn(urls=cdn_urls, outdir=cdn_dir)
    missing_after = set(check_cdn_availability(urls=cdn_urls, outdir=cdn_dir))

    # 5) Count how many files appeared
    saved = len(before_set - missing_after)
    return jsonify({"saved": saved})
