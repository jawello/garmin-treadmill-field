import Toybox.Lang;

// Decides when the activity timer may start or stop the belt.
class BeltController {
    const STOP_RETRY_MS = 3000;
    // A start this recent may not be visible in the belt state yet (~4 s countdown).
    const START_GRACE_MS = 6000;

    hidden var _link;
    hidden var _stopSentMs as Number? = null;
    hidden var _startSentMs as Number? = null;

    function initialize(link) {
        _link = link;
    }

    // Timer start/resume: start only now, only from a known stopped state.
    function onRun(enabled as Boolean, linkState as Number, beltState as Number?, nowMs as Number) as Void {
        _stopSentMs = null;
        if (enabled && linkState == LinkState.CONNECTED && beltState == WalkingPadProtocol.BELT_STOPPED) {
            _link.sendStart();
            _startSentMs = nowMs;
        }
    }

    // Timer pause/stop.
    function onHalt(enabled as Boolean, linkState as Number, beltState as Number?, nowMs as Number) as Void {
        var recentStart = _startSentMs != null && nowMs - _startSentMs < START_GRACE_MS;
        _startSentMs = null;
        if (!enabled || linkState != LinkState.CONNECTED) {
            return;
        }
        var moving = beltState != null
            && (beltState == WalkingPadProtocol.BELT_RUNNING || WalkingPadProtocol.isCountdown(beltState));
        if (recentStart || moving) {
            _link.sendStop();
            _stopSentMs = nowMs;
        }
    }

    // Resends the stop once if the belt is still running 3 s later.
    function tick(linkState as Number, beltState as Number?, nowMs as Number) as Void {
        if (_stopSentMs == null || nowMs - _stopSentMs < STOP_RETRY_MS) {
            return;
        }
        _stopSentMs = null;
        if (linkState == LinkState.CONNECTED && beltState == WalkingPadProtocol.BELT_RUNNING) {
            _link.sendStop();
        }
    }
}
