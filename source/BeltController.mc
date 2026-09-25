import Toybox.Lang;

// Decides when the activity timer may start or stop the belt.
class BeltController {
    const STOP_RETRY_MS = 3000;

    hidden var _link;
    hidden var _stopSentMs as Number? = null;

    function initialize(link) {
        _link = link;
    }

    // Timer start/resume: start only now, only from a known stopped state.
    function onRun(enabled as Boolean, linkState as Number, beltState as Number?) as Void {
        _stopSentMs = null;
        if (enabled && linkState == LinkState.CONNECTED && beltState == WalkingPadProtocol.BELT_STOPPED) {
            _link.sendStart();
        }
    }

    // Timer pause/stop.
    function onHalt(enabled as Boolean, linkState as Number, beltState as Number?, nowMs as Number) as Void {
        if (!enabled || linkState != LinkState.CONNECTED || beltState == null) {
            return;
        }
        if (beltState == WalkingPadProtocol.BELT_RUNNING || WalkingPadProtocol.isCountdown(beltState)) {
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
