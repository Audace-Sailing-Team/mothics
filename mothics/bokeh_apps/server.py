import socket
from bokeh.plotting import figure
from bokeh.models import ColumnDataSource
from bokeh.layouts import column
from bokeh.models import Tabs, Slider, ColumnDataSource, TabPanel
from pyproj import Transformer
from datetime import datetime, timedelta

from ..helpers import deg2num


# GPS tab
def create_gps_tab(database, transformer, tile_server_url, zoom_level=13, initial_margin=1024, bounds_margin=8192):
    from bokeh.models import ColumnDataSource
    from bokeh.plotting import figure
    from bokeh.models import WMTSTileSource
    from bokeh.models.widgets import TabPanel
    import math

    # Discover GPS keys
    initial_data = database.data_points[-1].to_dict() if database.data_points else {}
    lat_key = next((k for k in initial_data if k.endswith('/gps/lat')), None)
    lon_key = next((k for k in initial_data if k.endswith('/gps/long')), None)

    if not lat_key or not lon_key:
        return None

    try:
        lat = initial_data[lat_key]
        lon = initial_data[lon_key]
        if lat is None or lon is None:
            return None
        x, y = transformer.transform(lon, lat)
        if not math.isfinite(x) or not math.isfinite(y):
            return None
    except Exception as e:
        print(f"[GPS tab] transform failed: {e}")
        return None

    gps_source = ColumnDataSource(data=dict(x=[x], y=[y]))

    tile_provider = WMTSTileSource(url=tile_server_url)

    gps_fig = figure(
        title="Live GPS Track",
        x_axis_type="mercator",
        y_axis_type="mercator",
        tools="pan,wheel_zoom,reset",
        active_scroll="wheel_zoom",
        output_backend="webgl",
        height=500,
        sizing_mode="stretch_both",
        x_range=(x - initial_margin, x + initial_margin),
        y_range=(y - initial_margin, y + initial_margin)
    )

    gps_fig.x_range.bounds = (x - bounds_margin, x + bounds_margin)
    gps_fig.y_range.bounds = (y - bounds_margin, y + bounds_margin)

    gps_fig.add_tile(tile_provider)
    gps_fig.scatter("x", "y", source=gps_source, size=10, color="blue")

    return TabPanel(child=gps_fig, title="GPS")


# Bokeh server
def create_realtime_bokeh_app(doc, database):
    sources = {}
    tab_panels = []
    periodic_callback_id = None

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

    # Sliders
    time_window_slider = Slider(start=10, end=600, step=10, value=120, title="Time Window (seconds)")
    refresh_slider = Slider(start=500, end=10000, step=500, value=1000, title="Refresh Interval (ms)")

    def extract_time_series():
        series = {}
        for dp in database.data_points:
            for key, val in dp.to_dict().items():
                if key == 'timestamp' or 'last_timestamp' in key:
                    continue
                series.setdefault(key, {"timestamp": [], "value": []})
                if val is not None:
                    series[key]["timestamp"].append(dp.timestamp)
                    series[key]["value"].append(val)
        return series

    def update_sources():
        updated = extract_time_series()
        now = datetime.now()
        time_window = time_window_slider.value

        for key, src in sources.items():
            if key in updated:
                src.data = {
                    "x": updated[key]["timestamp"],
                    "y": updated[key]["value"]
                }

        for panel in tab_panels:
            if panel.title != "GPS":
                panel.child.x_range.start = now - timedelta(seconds=time_window)
                panel.child.x_range.end = now

    def update_x_range(attr, old, new):
        update_sources()

    def on_refresh_change(attr, old, new):
        nonlocal periodic_callback_id
        if periodic_callback_id is not None:
            doc.remove_periodic_callback(periodic_callback_id)
        periodic_callback_id = doc.add_periodic_callback(update_sources, new)

    time_window_slider.on_change("value", update_x_range)
    refresh_slider.on_change("value", on_refresh_change)

    # Build time series tabs
    initial_data = extract_time_series()
    for key, data in initial_data.items():
        if not data["timestamp"] or not data["value"]:
            continue

        source = ColumnDataSource(data={
            "x": data["timestamp"],
            "y": data["value"]
        })
        sources[key] = source

        max_time = max(data["timestamp"])
        min_time = max_time - timedelta(seconds=time_window_slider.value)

        fig = figure(
            title=f"Time Series: {key}",
            x_axis_type="datetime",
            height=400,
            sizing_mode="stretch_width",
            x_range=(min_time, max_time)
        )
        fig.line("x", "y", source=source, line_width=2)
        tab_panels.append(TabPanel(child=fig, title=key))

    # # Add GPS tab separately
    # hostname = socket.gethostname()
    # gps_tab = create_gps_tab(
    #     database=database,
    #     transformer=transformer,
    #     tile_server_url=f"http://{hostname}.local:5000/tiles/{{Z}}/{{X}}/{{Y}}.png",
    #     zoom_level=13
    # )
    # if gps_tab:
    #     tab_panels.append(gps_tab)

    tabs = Tabs(tabs=tab_panels, sizing_mode="stretch_both")

    layout = column(
        column(refresh_slider, time_window_slider, sizing_mode="stretch_width"),
        tabs,
        sizing_mode="stretch_width"
    )

    doc.add_root(layout)
    periodic_callback_id = doc.add_periodic_callback(update_sources, refresh_slider.value)
