import Toybox.Lang;
import Toybox.Test;

(:debug)
function st(state as Number, speedTenths as Number, distTens as Number, steps as Number) as Dictionary {
    return {:state => state, :speedTenths => speedTenths, :timeS => 0, :distTens => distTens, :steps => steps};
}

(:test)
function accFirstPacketMidWorkoutIsBaseline(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    Test.assert(!a.hasData());
    a.onStatus(st(1, 45, 16, 230), 1000);
    Test.assert(a.hasData());
    Test.assert(TestUtil.near(a.getTotalDistM(), 0.0));
    Test.assertEqual(a.getTotalSteps(), 0);
    return true;
}

(:test)
function accAddsDeltasWhileRunning(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 10, 100), 0);
    a.onStatus(st(1, 45, 12, 130), 1000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 20.0));
    Test.assertEqual(a.getTotalSteps(), 30);
    return true;
}

(:test)
function accPauseExcludesWalking(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 10, 100), 0);
    a.setTimerRunning(false);
    a.onStatus(st(1, 45, 12, 130), 1000);
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 13, 140), 2000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 10.0));
    Test.assertEqual(a.getTotalSteps(), 10);
    return true;
}

(:test)
function accTreadmillResetCountsRawValue(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 16, 230), 0);
    a.onStatus(st(1, 45, 1, 5), 1000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 10.0));
    Test.assertEqual(a.getTotalSteps(), 5);
    a.onStatus(st(1, 45, 2, 8), 2000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 20.0));
    Test.assertEqual(a.getTotalSteps(), 8);
    return true;
}

(:test)
function accResetDuringPauseThenResume(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 10, 100), 0);
    a.onStatus(st(1, 45, 16, 230), 1000);
    a.setTimerRunning(false);
    a.onStatus(st(0, 0, 16, 230), 2000);
    a.onStatus(st(9, 0, 0, 0), 3000);
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 1, 3), 4000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 70.0));
    Test.assertEqual(a.getTotalSteps(), 133);
    return true;
}

(:test)
function accReconnectGapIsCounted(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 10, 100), 0);
    a.onStatus(st(1, 45, 14, 150), 30000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 40.0));
    Test.assertEqual(a.getTotalSteps(), 50);
    return true;
}

(:test)
function accSpeedFollowsBeltState(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.onStatus(st(1, 45, 0, 0), 0);
    Test.assert(TestUtil.near(a.getSpeedMps(0) as Float, 1.25));
    Test.assertEqual(a.getBeltState(0), 1);
    a.onStatus(st(3, 7, 0, 0), 1000);
    Test.assert(TestUtil.near(a.getSpeedMps(1000) as Float, 0.0));
    Test.assertEqual(a.getBeltState(1000), 3);
    a.onStatus(st(9, 0, 0, 0), 2000);
    Test.assert(TestUtil.near(a.getSpeedMps(2000) as Float, 0.0));
    return true;
}

(:test)
function accStaleAfterFiveSeconds(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    Test.assert(a.getSpeedMps(0) == null);
    Test.assert(a.getBeltState(0) == null);
    a.onStatus(st(1, 45, 0, 0), 1000);
    Test.assert(a.getSpeedMps(6000) != null);
    Test.assert(a.getSpeedMps(6001) == null);
    Test.assert(a.getBeltState(6001) == null);
    return true;
}

(:test)
function accSmoothsDistanceWithCap(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 0, 0), 0);
    a.tick(0);
    a.tick(4000);
    Test.assert(TestUtil.near(a.getDisplayDistM(), 5.0));
    a.onStatus(st(1, 45, 0, 0), 4000);
    a.onStatus(st(1, 45, 0, 0), 8000);
    a.tick(12000);
    Test.assert(TestUtil.near(a.getDisplayDistM(), 10.0));
    a.onStatus(st(1, 45, 1, 0), 12500);
    Test.assert(TestUtil.near(a.getTotalDistM(), 10.0));
    Test.assert(TestUtil.near(a.getDisplayDistM(), 10.0));
    a.tick(14500);
    Test.assert(TestUtil.near(a.getDisplayDistM(), 13.125));
    return true;
}

(:test)
function accDisplayNeverDecreases(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 0, 0), 0);
    a.tick(0);
    a.tick(4000);
    var before = a.getDisplayDistM();
    a.onStatus(st(1, 45, 0, 0), 4000);
    Test.assert(a.getDisplayDistM() >= before);
    return true;
}

(:test)
function accNoSmoothingWhenPausedOrStale(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.onStatus(st(1, 45, 0, 0), 0);
    a.tick(0);
    a.tick(2000);
    Test.assert(TestUtil.near(a.getDisplayDistM(), 0.0));
    a.setTimerRunning(true);
    a.tick(20000);
    a.tick(22000);
    Test.assert(TestUtil.near(a.getDisplayDistM(), 0.0));
    return true;
}

(:test)
function accResetKeepsBaseline(logger as Logger) as Boolean {
    var a = new SessionAccumulator();
    a.setTimerRunning(true);
    a.onStatus(st(1, 45, 10, 100), 0);
    a.onStatus(st(1, 45, 12, 130), 1000);
    a.reset();
    Test.assert(TestUtil.near(a.getTotalDistM(), 0.0));
    Test.assert(TestUtil.near(a.getDisplayDistM(), 0.0));
    Test.assertEqual(a.getTotalSteps(), 0);
    a.onStatus(st(1, 45, 13, 135), 2000);
    Test.assert(TestUtil.near(a.getTotalDistM(), 10.0));
    Test.assertEqual(a.getTotalSteps(), 5);
    return true;
}
