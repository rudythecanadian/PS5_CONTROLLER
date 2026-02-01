#!/usr/bin/env python3
"""
DualSense Web Interface - Real-time controller testing via browser
"""

import threading
import time
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from dualsense import DualSense, PlayerLED, TriggerMode

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dualsense-test'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global controller instance
ds = None
reader_thread = None
running = False


def controller_reader():
    """Background thread that reads controller and emits state"""
    global running, ds

    while running:
        if ds:
            state = ds.read()
            if state:
                data = {
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
                }
                socketio.emit('controller_state', data)
        time.sleep(0.016)  # ~60Hz


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    global ds, reader_thread, running

    if ds is None:
        ds = DualSense()
        if ds.open():
            print("Controller connected!")
            running = True
            reader_thread = threading.Thread(target=controller_reader, daemon=True)
            reader_thread.start()
            emit('status', {'connected': True})
        else:
            emit('status', {'connected': False, 'error': 'Failed to open controller'})
    else:
        emit('status', {'connected': True})


@socketio.on('disconnect')
def handle_disconnect():
    print("Client disconnected")


@socketio.on('set_lightbar')
def handle_lightbar(data):
    if ds:
        ds.set_lightbar(data['r'], data['g'], data['b'])
        ds.send()


@socketio.on('set_haptic')
def handle_haptic(data):
    if ds:
        ds.set_haptic(data['left'], data['right'])
        ds.send()


@socketio.on('set_player_leds')
def handle_player_leds(data):
    if ds:
        ds.set_player_leds(PlayerLED(data['pattern']))
        ds.send()


@socketio.on('set_trigger')
def handle_trigger(data):
    if ds:
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


@socketio.on('set_mute_led')
def handle_mute_led(data):
    if ds:
        ds.set_mute_led(data['on'])
        ds.send()


def cleanup():
    global running, ds
    running = False
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
        socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        cleanup()
