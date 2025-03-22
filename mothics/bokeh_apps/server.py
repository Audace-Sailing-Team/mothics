from datetime import datetime, timedelta
from bokeh.layouts import row, column, layout
from bokeh.plotting import figure
from bokeh.models import ColumnDataSource, Tabs, TabPanel, Slider
from bokeh.models import WMTSTileSource
from bokeh.document import Document
from pyproj import Transformer


def create_realtime_bokeh_app(doc: Document, database):
    sources = {}
    tab_panels = []
    periodic_callback_id = None

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    gps_source = ColumnDataSource(data=dict(x=[], y=[], speed=[]))

    default_time_window = 120
    
    # Time window slider (10 sec to 10 min)
    time_window_slider = Slider(
        start=10, end=600, step=10, value=default_time_window,
        title="Time Window (seconds)"
    )
    
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

    initial_data = extract_time_series()

    # Dynamically discover GPS keys
    lat_key = next((k for k in initial_data if k.endswith('/gps/lat')), None)
    lon_key = next((k for k in initial_data if k.endswith('/gps/lon')), None)

    for key, data in initial_data.items():
        if not data["timestamp"] or not data["value"]:
            continue

        source = ColumnDataSource(data={
            "x": data["timestamp"],
            "y": data["value"]
        })
        sources[key] = source
        
        # Get initial x-axis range based on the default time window
        max_time = max(data["timestamp"]) if data["timestamp"] else datetime.now()
        min_time = max_time - timedelta(seconds=default_time_window)

        fig = figure(
            title=f"Time Series: {key}",
            x_axis_type="datetime",
            height=400,
            sizing_mode="stretch_width",
            x_range=(min_time, max_time)  # Set initial time window
        )
        fig.line("x", "y", source=source, line_width=2)

        tab_panels.append(TabPanel(child=fig, title=key))

    # Optional GPS tab
    if lat_key and lon_key:
        lat_vals = initial_data[lat_key]["value"]
        lon_vals = initial_data[lon_key]["value"]
        if lat_vals and lon_vals:
            lon, lat = lon_vals[-1], lat_vals[-1]
            x, y = transformer.transform(lon, lat)
            gps_source.data = dict(x=[x], y=[y])

        map_fig = figure(
            title="Live GPS Track",
            x_axis_type="mercator",
            y_axis_type="mercator",
            sizing_mode="stretch_both",
            height=500
        )

        # Choose tile provider based on internet availability
        tile_provider = WMTSTileSource(url="https://tile.openstreetmap.org/{Z}/{X}/{Y}.png")
        map_fig.add_tile(tile_provider)
        map_fig.circle("x", "y", source=gps_source, size=10, color="blue")
        gps_tab = TabPanel(child=map_fig, title="GPS")
        tab_panels.append(gps_tab)

    tabs = Tabs(tabs=tab_panels, sizing_mode="stretch_both")
    
    # Refresh rate slider
    refresh_slider = Slider(
        start=100, end=10000, step=100, value=500,
        title="Refresh Interval (ms)"
    )

    def update_sources():
        updated = extract_time_series()
        current_time = datetime.now()
        time_window = time_window_slider.value
        
        for key, src in sources.items():
            if key in updated:
                src.data = {
                    "x": updated[key]["timestamp"],
                    "y": updated[key]["value"]
                }

        for panel in tab_panels:
            panel.child.x_range.start = current_time - timedelta(seconds=time_window)
            panel.child.x_range.end = current_time
            
        # Update GPS
        if lat_key and lon_key:
            lat_vals = updated.get(lat_key, {}).get('value', [])
            lon_vals = updated.get(lon_key, {}).get('value', [])
            if lat_vals and lon_vals:
                lon, lat = lon_vals[-1], lat_vals[-1]
                x, y = transformer.transform(lon, lat)
                gps_source.data = dict(x=[x], y=[y])

    # Event handler for the sliders
    def update_x_range(attr, old, new):
        update_sources()
    
    def on_refresh_change(attr, old, new):
        nonlocal periodic_callback_id
        if periodic_callback_id is not None:
            doc.remove_periodic_callback(periodic_callback_id)
        periodic_callback_id = doc.add_periodic_callback(update_sources, new)

    refresh_slider.on_change("value", on_refresh_change)
    time_window_slider.on_change("value", update_x_range)

    # Create a row for the sliders
    slider_column = column(
        refresh_slider, 
        time_window_slider, 
        sizing_mode="stretch_width"
    )
    
    # Sliders in a row, then tabs
    layout = column(
        slider_column,
        tabs,
        sizing_mode="stretch_width"
    )

    doc.add_root(layout)
    periodic_callback_id = doc.add_periodic_callback(update_sources, refresh_slider.value)
