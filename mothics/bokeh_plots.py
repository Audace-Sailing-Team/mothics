from datetime import datetime, timedelta
from bokeh.embed import components, server_document
from bokeh.plotting import figure
from bokeh.models import ColumnDataSource, Range1d, Tabs, TabPanel, Slider
from bokeh.layouts import column
from bokeh.models import WMTSTileSource
from pyproj import Transformer
import math
import numbers

# Data fetching (shared)
def extract_time_series(database, hidden_data=None):
    hidden_set = set(hidden_data or [])
    time_series = {}

    for dp in database.data_points:
        ts = dp.timestamp
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)

        for key, value in dp.to_dict().items():
            if key == 'timestamp' or 'last_timestamp' in key or key in hidden_set:
                continue
            if value is not None:
                time_series.setdefault(key, {"timestamp": [], "value": []})
                time_series[key]["timestamp"].append(ts)
                time_series[key]["value"].append(value)

    return time_series


# Static plotting
def create_static_bokeh_plots(database, hidden_data=None, data_thesaurus=None):
    time_series = extract_time_series(database, hidden_data=hidden_data)
    plots = []
    
    for key, data in time_series.items():
        label = data_thesaurus.get(key, key) if data_thesaurus else key
        # Filter out invalid timestamp/value pairs
        x_vals = []
        y_vals = []
        for t, v in zip(data["timestamp"], data["value"]):
            if isinstance(t, str):
                try:
                    t = datetime.fromisoformat(t)
                except Exception:
                    continue
            if isinstance(t, datetime) and isinstance(v, numbers.Number):
                x_vals.append(t)
                y_vals.append(v)

        if not x_vals or not y_vals:
            continue  # Nothing to plot

        source = ColumnDataSource(data={"x": x_vals, "y": y_vals})

        p = figure(
            x_axis_type="datetime",
            title=f"Time Evolution of {label}",
            sizing_mode="stretch_width",
            height=300
        )
        p.line('x', 'y', source=source, line_width=2, legend_label=label)
        p.scatter('x', 'y', source=source, size=5, color='red')

        p.legend.location = "top_left"
        p.xaxis.axis_label = 'Timestamp'
        p.yaxis.axis_label = label

        if len(x_vals) > 1:
            p.x_range = Range1d(start=min(x_vals), end=max(x_vals))
        if len(y_vals) > 1:
            y_padding = (max(y_vals) - min(y_vals)) * 0.05
            p.y_range = Range1d(
                start=min(y_vals) - y_padding,
                end=max(y_vals) + y_padding
            )

        plots.append(p)

    if not plots:
        return "", "<p>No valid data to plot.</p>"

    layout = column(children=plots, sizing_mode="stretch_width", spacing=20)
    return components(layout)


# Real-time plotting
def create_gps_tab(database, transformer, tile_server_url, zoom_level=13, initial_margin=1024, bounds_margin=8192):
    if not database.data_points:
        return None

    initial_data = database.data_points[-1].to_dict()
    lat_key = next((k for k in initial_data if k.endswith('/gps/lat')), None)
    lon_key = next((k for k in initial_data if k.endswith('/gps/long')), None)

    if not lat_key or not lon_key:
        return None

    lat, lon = initial_data.get(lat_key), initial_data.get(lon_key)
    if lat is None or lon is None:
        return None

    try:
        x, y = transformer.transform(lon, lat)
        if not math.isfinite(x) or not math.isfinite(y):
            return None
    except Exception:
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


# Dispatcher
class PlotDispatcher:
    def __init__(self, config):
        self.config = config

    def render(self):
        if self.config['PLOT_MODE'] == 'real-time':
            return self._render_realtime()
        return self._render_static()

    def _render_static(self):
        database = self.config['GETTERS']['database']()
        hidden = set(self.config.get('HIDDEN_DATA_PLOTS') or [])
        thesaurus = self.config.get('DATA_THESAURUS', {})
        return create_static_bokeh_plots(database, hidden_data=hidden, data_thesaurus=thesaurus)

    def _render_realtime(self):
        return server_document(self.config['PLOT_REALTIME_URL']), ""


# Bokeh server app
def create_realtime_bokeh_app(doc, database, hidden_data=None, data_thesaurus=None):
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    sources = {}
    panels = []

    time_window_slider = Slider(start=10, end=600, step=10, value=120, title="Time Window (seconds)")
    refresh_slider = Slider(start=500, end=10000, step=500, value=1000, title="Refresh Interval (ms)")

    def update_sources():
        now = datetime.now()
        time_window = time_window_slider.value
        series = extract_time_series(database, hidden_data=hidden_data)

        for key, src in sources.items():
            if key in series:
                src.data = {"x": series[key]["timestamp"], "y": series[key]["value"]}

        for panel in panels:
            if panel.title != "GPS":
                panel.child.x_range.start = now - timedelta(seconds=time_window)
                panel.child.x_range.end = now

    def on_time_window_change(attr, old, new):
        update_sources()

    def on_refresh_change(attr, old, new):
        doc.remove_periodic_callback(update_sources)
        doc.add_periodic_callback(update_sources, new)

    time_window_slider.on_change("value", on_time_window_change)
    refresh_slider.on_change("value", on_refresh_change)

    series = extract_time_series(database, hidden_data=hidden_data)
    for key, data in series.items():
        if not data["timestamp"] or not data["value"]:
            continue
        label = data_thesaurus.get(key, key) if data_thesaurus else key
        
        source = ColumnDataSource(data={"x": data["timestamp"], "y": data["value"]})
        sources[key] = source

        max_time = max(data["timestamp"])
        min_time = max_time - timedelta(seconds=time_window_slider.value)

        fig = figure(
            title=f"Time Series: {label}",
            x_axis_type="datetime",
            height=400,
            sizing_mode="stretch_width",
            x_range=(min_time, max_time)
        )
        fig.line("x", "y", source=source, line_width=2)
        fig.yaxis.axis_label = label
        panels.append(TabPanel(child=fig, title=label))

    # Optional GPS tab
    # gps_tab = create_gps_tab(database, transformer, tile_server_url="http://host.local:5000/tiles/{Z}/{X}/{Y}.png")
    # if gps_tab:
    #     panels.append(gps_tab)

    tabs = Tabs(tabs=panels, sizing_mode="stretch_both")

    layout = column(
        column(refresh_slider, time_window_slider, sizing_mode="stretch_width"),
        tabs,
        sizing_mode="stretch_width"
    )
    doc.add_root(layout)
    doc.add_periodic_callback(update_sources, refresh_slider.value)
