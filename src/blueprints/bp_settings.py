from flask import Blueprint, render_template, jsonify, request, Response, current_app
from ..helpers import tipify

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/settings', methods=['GET', 'POST'])
def settings():
    # Process settings here with form submission or any other logic
    if request.method == 'POST':

        # Update table refresh rate
        if request.form['auto_refresh_table']:
            current_app.config['AUTO_REFRESH_TABLE'] = tipify(request.form['auto_refresh_table'])*1000
            current_app.config['LOGGER'].info(f'set auto refresh rate for table at {current_app.config["AUTO_REFRESH_TABLE"]/1000} s')

        # Update Aggregator refresh rate
        if request.form['aggregator_interval']:
            aggregator_refresh_rate = tipify(request.form['aggregator_interval'])
            try:
                current_app.config['SETTERS']['aggregator_refresh_rate'](aggregator_refresh_rate)
                current_app.config['LOGGER'].info(f'set Aggregator refresh rate at {aggregator_refresh_rate} s')
            except:
                current_app.config['LOGGER'].warning(f'could not set Aggregator refresh rate')
        # ADD OTHER TOGGLES HERE

        # Update settings
        return render_template('settings.html', success=True)
    return render_template('settings.html', success=False)
