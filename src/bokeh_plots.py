from datetime import datetime
from bokeh.embed import components
from bokeh.plotting import figure, show
from bokeh.models import ColumnDataSource, Range1d, Slider
from bokeh.layouts import gridplot, column
from pprint import pprint


def create_bokeh_plots(database):
    """Creates Bokeh plots for the time evolution of data."""
    time_series = {}
    for dp in database.data_points:
        for key, value in dp.to_dict().items():
            if key == 'timestamp':
                continue
            if key not in time_series:
                time_series[key] = {"timestamp": [], "value": []}
            if value is not None:
                time_series[key]["timestamp"].append(dp.timestamp)
                time_series[key]["value"].append(value)

    plots = []
    for key, data in time_series.items():
        if len(data["timestamp"]) == 0 or len(data["value"]) == 0 or key.split('/')[1] == 'status':
            continue
        
        source = ColumnDataSource(data={
            'x': data["timestamp"],
            'y': data["value"]
        })

        p = figure(
            x_axis_type="datetime",
            title=f"Time Evolution of {key}",
            sizing_mode="stretch_width",
            height=300  # Reduced height for better stacking
        )

        p.line('x', 'y', source=source, line_width=2, legend_label=key)
        p.scatter('x', 'y', source=source, size=5, color='red')
        
        p.legend.location = "top_left"
        p.xaxis.axis_label = 'Timestamp'
        p.yaxis.axis_label = key
        
        p.min_border_left = 50
        p.min_border_right = 50
        p.min_border_top = 20
        p.min_border_bottom = 20
        
        min_x, max_x = min(data["timestamp"]), max(data["timestamp"])
        min_y, max_y = min(data["value"]), max(data["value"])

        print(min_y, max_y)
        
        y_padding = (max_y - min_y) * 0.05 if max_y != min_y else max_y * 0.05
        
        if min_x != max_x:
            p.x_range = Range1d(start=min_x, end=max_x)
        if min_y != max_y:
            p.y_range = Range1d(
                start=min_y - y_padding,
                end=max_y + y_padding
            )
        
        plots.append(p)

    if not plots:
        return "", "<p>No valid data to plot.</p>"

    layout = column(children=plots, sizing_mode="stretch_width", spacing=20)
    script, div = components(layout)
    return script, div
