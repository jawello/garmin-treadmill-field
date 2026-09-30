import Toybox.Lang;
import Toybox.Test;

(:test)
function beltStartsWhenEnabledConnectedStopped(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onRun(true, LinkState.CONNECTED, 0, 0);
    Test.assertEqual(link.starts, 1);
    return true;
}

(:test)
function beltNoStartWhenDisabled(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onRun(false, LinkState.CONNECTED, 0, 0);
    Test.assertEqual(link.starts, 0);
    return true;
}

(:test)
function beltNoStartWhenNotConnectedAndNoLateStart(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onRun(true, LinkState.SEARCHING, null, 0);
    belt.onRun(true, LinkState.ERROR, 0, 0);
    belt.tick(LinkState.CONNECTED, 0, 10000);
    belt.tick(LinkState.CONNECTED, 0, 20000);
    Test.assertEqual(link.starts, 0);
    return true;
}

(:test)
function beltNoStartWhenRunningOrUnknown(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onRun(true, LinkState.CONNECTED, 1, 0);
    belt.onRun(true, LinkState.CONNECTED, 3, 1000);
    belt.onRun(true, LinkState.CONNECTED, 8, 0);
    belt.onRun(true, LinkState.CONNECTED, null, 0);
    Test.assertEqual(link.starts, 0);
    return true;
}

(:test)
function beltStopsWhenRunningOrCountdown(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onHalt(true, LinkState.CONNECTED, 1, 0);
    belt.onHalt(true, LinkState.CONNECTED, 7, 100);
    Test.assertEqual(link.stops, 2);
    return true;
}

(:test)
function beltNoStopWhenStoppedOrDisabled(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onHalt(true, LinkState.CONNECTED, 0, 0);
    belt.onHalt(true, LinkState.CONNECTED, 3, 0);
    belt.onHalt(false, LinkState.CONNECTED, 1, 0);
    belt.onHalt(true, LinkState.SEARCHING, 1, 0);
    Test.assertEqual(link.stops, 0);
    return true;
}

(:test)
function beltNoStopWhenStateUnknown(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onHalt(true, LinkState.CONNECTED, null, 0);
    belt.tick(LinkState.CONNECTED, 1, 5000);
    Test.assertEqual(link.stops, 0);
    return true;
}

(:test)
function beltRetriesStopOnceAfterThreeSeconds(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onHalt(true, LinkState.CONNECTED, 1, 0);
    belt.tick(LinkState.CONNECTED, 1, 2999);
    Test.assertEqual(link.stops, 1);
    belt.tick(LinkState.CONNECTED, 1, 3000);
    Test.assertEqual(link.stops, 2);
    belt.tick(LinkState.CONNECTED, 1, 6000);
    belt.tick(LinkState.CONNECTED, 1, 9000);
    Test.assertEqual(link.stops, 2);
    return true;
}

(:test)
function beltNoRetryWhenStopping(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onHalt(true, LinkState.CONNECTED, 1, 0);
    belt.tick(LinkState.CONNECTED, 3, 3000);
    Test.assertEqual(link.stops, 1);
    return true;
}

(:test)
function beltResumeCancelsPendingRetry(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onHalt(true, LinkState.CONNECTED, 1, 0);
    belt.onRun(true, LinkState.CONNECTED, 3, 1000);
    belt.tick(LinkState.CONNECTED, 1, 3000);
    Test.assertEqual(link.stops, 1);
    Test.assertEqual(link.starts, 0);
    return true;
}

(:test)
function beltIgnoresPauseRightAfterRun(logger as Logger) as Boolean {
    // Garmin Auto Pause pauses again within a second of a resume (the belt is still in its
    // countdown, speed 0). That pause must not stop the belt we just started.
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onRun(true, LinkState.CONNECTED, 0, 0);
    belt.onHalt(true, LinkState.CONNECTED, 7, 500);
    belt.onHalt(true, LinkState.CONNECTED, 1, 4999);
    Test.assertEqual(link.starts, 1);
    Test.assertEqual(link.stops, 0);
    return true;
}

(:test)
function beltStopsOnPauseAfterTheGuard(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onRun(true, LinkState.CONNECTED, 0, 0);
    belt.onHalt(true, LinkState.CONNECTED, 1, 5000);
    Test.assertEqual(link.stops, 1);
    return true;
}

(:test)
function beltGuardAppliesEvenWhenNoStartWasNeeded(logger as Logger) as Boolean {
    // Auto-resumed because the belt was already running: an instant auto-pause glitch
    // must not stop it either.
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onRun(true, LinkState.CONNECTED, 1, 0);
    belt.onHalt(true, LinkState.CONNECTED, 1, 800);
    Test.assertEqual(link.stops, 0);
    return true;
}

(:test)
function beltNoStopLongAfterStartWhenStopped(logger as Logger) as Boolean {
    var link = new FakeLink();
    var belt = new BeltController(link);
    belt.onRun(true, LinkState.CONNECTED, 0, 0);
    belt.onHalt(true, LinkState.CONNECTED, 0, 10000);
    Test.assertEqual(link.stops, 0);
    return true;
}
