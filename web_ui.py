#!/usr/bin/env python3
"""
DualSense Web Interface - Real-time controller testing via browser
Pure REST API - no WebSocket needed
"""

from flask import Flask, render_template, request, jsonify
from dualsense import DualSense, PlayerLED, TriggerMode

app = Flask(__name__)

# Global controller instance
ds = None


@app.route('/')
def index():
    return render_template('index.html')


# REST API endpoints for fast polling (avoids WebSocket issues)
@app.route('/api/connect', methods=['POST'])
def api_connect():
    """Connect to controller"""
    global ds
    if ds is None:
        ds = DualSense()
        if ds.open():
            conn_type = ds.connection_type
            print(f"Controller connected via REST API! Mode: {conn_type}")
            return jsonify({
                'connected': True,
                'mode': conn_type,
                'using_evdev': ds._use_evdev,
                'using_sysfs': ds._use_sysfs
            })
        else:
            return jsonify({'connected': False, 'error': 'Failed to open controller'})
    return jsonify({
        'connected': True,
        'mode': ds.connection_type,
        'using_evdev': ds._use_evdev,
        'using_sysfs': ds._use_sysfs
    })


@app.route('/api/stream')
def api_stream():
    """Server-Sent Events stream for real-time updates"""
    import json
    import time
    from flask import Response

    def generate():
        global ds
        while True:
            if ds:
                state = ds.read_blocking(timeout_ms=50)
                if state:
                    data = json.dumps({
                        'left_stick': {'x': state.left_stick_x, 'y': state.left_stick_y},
                        'right_stick': {'x': state.right_stick_x, 'y': state.right_stick_y},
                        'l2': state.l2_trigger,
                        'r2': state.r2_trigger,
                        'dpad': state.dpad.name if state.dpad else 'NONE',
                        'buttons': {
                            'cross': state.cross, 'circle': state.circle,
                            'square': state.square, 'triangle': state.triangle,
                            'l1': state.l1, 'r1': state.r1,
                            'l2_click': state.l2_button, 'r2_click': state.r2_button,
                            'l3': state.l3, 'r3': state.r3,
                            'create': state.create, 'options': state.options,
                            'ps': state.ps, 'touchpad': state.touchpad_click, 'mute': state.mute,
                        },
                        'touch': [
                            {'active': state.touch1.active, 'x': state.touch1.x, 'y': state.touch1.y},
                            {'active': state.touch2.active, 'x': state.touch2.x, 'y': state.touch2.y},
                        ],
                        'gyro': {'x': state.gyro_x, 'y': state.gyro_y, 'z': state.gyro_z},
                        'accel': {'x': state.accel_x, 'y': state.accel_y, 'z': state.accel_z},
                        'battery': state.battery_level,
                        'charging': state.battery_charging,
                    })
                    yield f"data: {data}\n\n"

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/state')
def api_state():
    """Get current controller state - polling fallback"""
    global ds
    if ds is None:
        return jsonify({'error': 'Not connected'}), 400

    state = ds.read()
    if state:
        return jsonify({
            'left_stick': {'x': state.left_stick_x, 'y': state.left_stick_y},
            'right_stick': {'x': state.right_stick_x, 'y': state.right_stick_y},
            'l2': state.l2_trigger,
            'r2': state.r2_trigger,
            'dpad': state.dpad.name if state.dpad else 'NONE',
            'buttons': {
                'cross': state.cross,
                'circle': state.circle,
                'square': state.square,
                'triangle': state.triangle,
                'l1': state.l1,
                'r1': state.r1,
                'l2_click': state.l2_button,
                'r2_click': state.r2_button,
                'l3': state.l3,
                'r3': state.r3,
                'create': state.create,
                'options': state.options,
                'ps': state.ps,
                'touchpad': state.touchpad_click,
                'mute': state.mute,
            },
            'touch': [
                {'active': state.touch1.active, 'x': state.touch1.x, 'y': state.touch1.y},
                {'active': state.touch2.active, 'x': state.touch2.x, 'y': state.touch2.y},
            ],
            'gyro': {'x': state.gyro_x, 'y': state.gyro_y, 'z': state.gyro_z},
            'accel': {'x': state.accel_x, 'y': state.accel_y, 'z': state.accel_z},
            'battery': state.battery_level,
            'charging': state.battery_charging,
        })
    return jsonify({'error': 'No data'}), 500


@app.route('/api/lightbar', methods=['POST'])
def api_lightbar():
    """Set lightbar color"""
    global ds
    if ds is None:
        return jsonify({'error': 'Not connected'}), 400
    data = request.json
    ds.set_lightbar(data['r'], data['g'], data['b'])
    ds.send()
    return jsonify({'ok': True})


@app.route('/api/haptic', methods=['POST'])
def api_haptic():
    """Set haptic feedback"""
    global ds
    if ds is None:
        return jsonify({'error': 'Not connected'}), 400
    data = request.json
    ds.set_haptic(data['left'], data['right'])
    ds.send()
    return jsonify({'ok': True})


@app.route('/api/player_leds', methods=['POST'])
def api_player_leds():
    """Set player LEDs"""
    global ds
    if ds is None:
        return jsonify({'error': 'Not connected'}), 400
    data = request.json
    ds.set_player_leds(PlayerLED(data['pattern']))
    ds.send()
    return jsonify({'ok': True})


@app.route('/api/trigger', methods=['POST'])
def api_trigger():
    """Set trigger effect"""
    global ds
    if ds is None:
        return jsonify({'error': 'Not connected'}), 400
    data = request.json
    trigger = data['trigger']
    mode = data['mode']

    if mode == 'off':
        ds.clear_trigger_effect(trigger)
    elif mode == 'rigid':
        ds.set_trigger_effect(trigger, TriggerMode.RIGID,
                              start=data.get('start', 50),
                              force=data.get('force', 200))
    elif mode == 'pulse':
        ds.set_trigger_effect(trigger, TriggerMode.PULSE,
                              start=data.get('start', 50),
                              force=data.get('force', 200))
    ds.send()
    return jsonify({'ok': True})


def cleanup():
    global ds
    if ds:
        ds.set_lightbar(0, 0, 0)
        ds.set_haptic(0, 0)
        ds.clear_trigger_effect('both')
        ds.set_player_leds(PlayerLED.OFF)
        ds.send()
        ds.close()


if __name__ == '__main__':
    import atexit
    atexit.register(cleanup)

    print("=" * 50)
    print("DualSense Web Interface")
    print("=" * 50)
    print("\nOpen http://localhost:5000 in your browser")
    print("Press Ctrl+C to exit\n")

    try:
        # Use Flask threaded server - better for SSE streaming
        from werkzeug.serving import run_simple
        run_simple('0.0.0.0', 5000, app, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        cleanup()
