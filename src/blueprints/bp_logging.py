from flask import Blueprint, render_template, jsonify, request, Response, current_app


log_bp = Blueprint('log', __name__)


@log_bp.route('/logs')
def logs():
    return render_template('logs.html')

@log_bp.route('/stream_logs')
def stream_logs():
    logger_fname = current_app.config['LOGGER_FNAME']
    def generate():
        with open(logger_fname, 'r') as f:
            while True:
                line = f.readline()
                if line:
                    yield f"data: {line}\n\n"
    return Response(generate(), content_type='text/event-stream')

@log_bp.route('/empty_log_file', methods=['POST'])
def empty_log_file():
    try:
        open(current_app.config['LOGGER_FNAME'], 'w').close()
        return jsonify({'status': 'success', 'message': 'Log file emptied successfully.'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
