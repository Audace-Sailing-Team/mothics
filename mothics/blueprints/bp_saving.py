from flask import Blueprint, render_template, jsonify, request, Response, current_app


save_bp = Blueprint('save', __name__)


@save_bp.route('/start_save', methods=['POST'])
def start_save():
    try:
        current_app.config['SETTERS']['start_save']()
        return jsonify({'status': 'success', 'message': 'Continuous sampling started.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@save_bp.route('/end_save', methods=['POST'])
def end_save():
    try:
        current_app.config['SETTERS']['stop_save']()
        return jsonify({'status': 'success', 'message': 'Continuous sampling ended.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@save_bp.route('/sampling_status')
def sampling_status():
    try:
        save_status = current_app.config['GETTERS']['save_status']()
        # Return the current sampling mode
        return jsonify({'save_mode': save_status})
    except Exception as e:
        return jsonify({'save_mode': 'unknown', 'error': str(e)}), 500

