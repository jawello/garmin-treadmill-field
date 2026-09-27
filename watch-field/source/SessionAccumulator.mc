import Toybox.Lang;

// Turns the treadmill's own counters into workout totals.
class SessionAccumulator {
    const STALE_MS = 5000;
    const SMOOTH_CAP_M = 10.0;
    const DIST_UNIT_M = 10;

    hidden var _totalDistM as Float = 0.0;
    hidden var _displayDistM as Float = 0.0;
    hidden var _totalSteps as Number = 0;
    hidden var _lastRawDist as Number? = null;
    hidden var _lastRawSteps as Number? = null;
    hidden var _timerRunning as Boolean = false;
    hidden var _speedMps as Float = 0.0;
    hidden var _beltState as Number? = null;
    hidden var _lastPacketMs as Number? = null;
    hidden var _lastTickMs as Number? = null;

    function initialize() {
    }

    function setTimerRunning(running as Boolean) as Void {
        _timerRunning = running;
    }

    function onStatus(status as Dictionary, nowMs as Number) as Void {
        var rawDist = status[:distTens] as Number;
        var rawSteps = status[:steps] as Number;
        if (_lastRawDist != null && _timerRunning) {
            _totalDistM += (counterDelta(rawDist, _lastRawDist) * DIST_UNIT_M).toFloat();
            _totalSteps += counterDelta(rawSteps, _lastRawSteps as Number);
        }
        _lastRawDist = rawDist;
        _lastRawSteps = rawSteps;
        _beltState = status[:state] as Number;
        _speedMps = _beltState == WalkingPadProtocol.BELT_RUNNING
            ? (status[:speedTenths] as Number) / 36.0
            : 0.0;
        _lastPacketMs = nowMs;
        if (_displayDistM < _totalDistM) {
            _displayDistM = _totalDistM;
        }
    }

    // Grows the displayed distance between 10 m packets, never past total + 10 m.
    function tick(nowMs as Number) as Void {
        if (_lastTickMs != null && _timerRunning && !isStale(nowMs)) {
            var grown = _displayDistM + _speedMps * (nowMs - _lastTickMs) / 1000.0;
            var cap = _totalDistM + SMOOTH_CAP_M;
            var next = grown < cap ? grown : cap;
            if (next > _displayDistM) {
                _displayDistM = next;
            }
        }
        _lastTickMs = nowMs;
    }

    // New workout: zero the totals, keep the treadmill baseline.
    function reset() as Void {
        _totalDistM = 0.0;
        _displayDistM = 0.0;
        _totalSteps = 0;
    }

    function hasData() as Boolean {
        return _lastRawDist != null;
    }

    function getTotalDistM() as Float {
        return _totalDistM;
    }

    function getDisplayDistM() as Float {
        return _displayDistM;
    }

    function getTotalSteps() as Number {
        return _totalSteps;
    }

    function getSpeedMps(nowMs as Number) as Float? {
        return isStale(nowMs) ? null : _speedMps;
    }

    function getBeltState(nowMs as Number) as Number? {
        return isStale(nowMs) ? null : _beltState;
    }

    hidden function isStale(nowMs as Number) as Boolean {
        return _lastPacketMs == null || nowMs - _lastPacketMs > STALE_MS;
    }

    // A counter that went down means the treadmill started a new session from zero.
    hidden function counterDelta(raw as Number, last as Number) as Number {
        return raw >= last ? raw - last : raw;
    }
}
