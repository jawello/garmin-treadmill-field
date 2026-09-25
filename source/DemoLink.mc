import Toybox.Lang;
import Toybox.System;

// Simulator stand-in for TreadmillLink: a 70 s loop of 5 s searching,
// 55 s connected at 4.5 km/h, 10 s link error. The treadmill keeps
// counting during the error, like the real one does.
(:debug)
class DemoLink {
    const CYCLE_S = 70;
    const SEARCH_END_S = 5;
    const CONNECTED_END_S = 60;
    const SPEED_TENTHS = 45;
    const STEPS_PER_S = 1.8;

    hidden var _onStatus as Method;
    hidden var _state as Number = LinkState.SEARCHING;
    hidden var _belt as Number = WalkingPadProtocol.BELT_RUNNING;
    hidden var _startMs as Number? = null;
    hidden var _lastMs as Number? = null;
    hidden var _timeS as Float = 0.0;
    hidden var _distM as Float = 0.0;
    hidden var _steps as Float = 0.0;

    function initialize(onStatus as Method) {
        _onStatus = onStatus;
    }

    function start() as Void {
    }

    function getState() as Number {
        return _state;
    }

    function sendStart() as Void {
        System.println("demo: start belt");
        _belt = WalkingPadProtocol.BELT_RUNNING;
    }

    function sendStop() as Void {
        System.println("demo: stop belt");
        _belt = WalkingPadProtocol.BELT_STOPPED;
    }

    function tick(nowMs as Number) as Void {
        if (_startMs == null) {
            _startMs = nowMs;
        }
        if (_lastMs != null && _belt == WalkingPadProtocol.BELT_RUNNING) {
            var dt = (nowMs - _lastMs) / 1000.0;
            _timeS += dt;
            _distM += SPEED_TENTHS / 36.0 * dt;
            _steps += STEPS_PER_S * dt;
        }
        _lastMs = nowMs;

        var phase = ((nowMs - _startMs) / 1000) % CYCLE_S;
        var previous = _state;
        if (phase < SEARCH_END_S) {
            _state = LinkState.SEARCHING;
        } else if (phase < CONNECTED_END_S) {
            _state = LinkState.CONNECTED;
            var speed = _belt == WalkingPadProtocol.BELT_RUNNING ? SPEED_TENTHS : 0;
            var packet = WalkingPadProtocol.buildStatusPacket(_belt, speed,
                _timeS.toNumber(), (_distM / 10).toNumber(), _steps.toNumber());
            var status = WalkingPadProtocol.parseStatus(packet);
            if (status != null) {
                _onStatus.invoke(status);
            }
        } else {
            _state = LinkState.ERROR;
        }
        if (_state != previous) {
            System.println("demo: link state " + _state + " at " + phase + " s");
        }
    }
}
