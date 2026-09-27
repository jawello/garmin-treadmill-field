import Toybox.Lang;
import Toybox.Test;

(:test)
function protocolCommandBytes(logger as Logger) as Boolean {
    Test.assert(TestUtil.bytesEqual(WalkingPadProtocol.statusQuery(), [0xF7, 0xA2, 0x00, 0x00, 0xA2, 0xFD]b));
    Test.assert(TestUtil.bytesEqual(WalkingPadProtocol.startCommand(), [0xF7, 0xA2, 0x04, 0x01, 0xA7, 0xFD]b));
    Test.assert(TestUtil.bytesEqual(WalkingPadProtocol.stopCommand(), [0xF7, 0xA2, 0x01, 0x00, 0xA3, 0xFD]b));
    return true;
}

(:test)
function protocolParsesStopped(logger as Logger) as Boolean {
    var s = WalkingPadProtocol.parseStatus(Fixtures.stopped());
    Test.assert(s != null);
    Test.assertEqual(s[:state], 0);
    Test.assertEqual(s[:speedTenths], 0);
    Test.assertEqual(s[:timeS], 0);
    Test.assertEqual(s[:distTens], 0);
    Test.assertEqual(s[:steps], 0);
    return true;
}

(:test)
function protocolParsesWalking(logger as Logger) as Boolean {
    var s = WalkingPadProtocol.parseStatus(Fixtures.walking());
    Test.assert(s != null);
    Test.assertEqual(s[:state], 1);
    Test.assertEqual(s[:speedTenths], 45);
    Test.assertEqual(s[:timeS], 130);
    Test.assertEqual(s[:distTens], 16);
    Test.assertEqual(s[:steps], 230);
    return true;
}

(:test)
function protocolParsesButtonPress(logger as Logger) as Boolean {
    var s = WalkingPadProtocol.parseStatus(Fixtures.buttonPress());
    Test.assert(s != null);
    Test.assertEqual(s[:speedTenths], 50);
    Test.assertEqual(s[:timeS], 42);
    Test.assertEqual(s[:distTens], 4);
    Test.assertEqual(s[:steps], 69);
    return true;
}

(:test)
function protocolParsesCountdownAndStopping(logger as Logger) as Boolean {
    var c = WalkingPadProtocol.parseStatus(Fixtures.countdown());
    Test.assert(c != null);
    Test.assertEqual(c[:state], 9);
    var s = WalkingPadProtocol.parseStatus(Fixtures.stopping());
    Test.assert(s != null);
    Test.assertEqual(s[:state], WalkingPadProtocol.BELT_STOPPING);
    Test.assertEqual(s[:speedTenths], 7);
    Test.assertEqual(s[:steps], 14);
    return true;
}

(:test)
function protocolCountdownRange(logger as Logger) as Boolean {
    Test.assert(!WalkingPadProtocol.isCountdown(5));
    Test.assert(WalkingPadProtocol.isCountdown(6));
    Test.assert(WalkingPadProtocol.isCountdown(9));
    Test.assert(!WalkingPadProtocol.isCountdown(10));
    Test.assert(!WalkingPadProtocol.isCountdown(1));
    return true;
}

(:test)
function protocolRejectsMalformed(logger as Logger) as Boolean {
    var badChecksum = Fixtures.walking();
    badChecksum[18] = 0x48;
    Test.assert(WalkingPadProtocol.parseStatus(badChecksum) == null);

    var wrongType = Fixtures.walking();
    wrongType[1] = 0xA7;
    Test.assert(WalkingPadProtocol.parseStatus(wrongType) == null);

    var wrongHeader = Fixtures.walking();
    wrongHeader[0] = 0xF7;
    Test.assert(WalkingPadProtocol.parseStatus(wrongHeader) == null);

    var noFooter = Fixtures.walking();
    noFooter[19] = 0x00;
    Test.assert(WalkingPadProtocol.parseStatus(noFooter) == null);

    Test.assert(WalkingPadProtocol.parseStatus(Fixtures.walking().slice(0, 10)) == null);
    Test.assert(WalkingPadProtocol.parseStatus([]b) == null);
    Test.assert(WalkingPadProtocol.parseStatus(null) == null);
    return true;
}

(:test)
function protocolParsesLargeCounters(logger as Logger) as Boolean {
    var s = WalkingPadProtocol.parseStatus(
        WalkingPadProtocol.buildStatusPacket(1, 45, 0x010000, 0x00ABCD, 0x012345));
    Test.assert(s != null);
    Test.assertEqual(s[:timeS], 65536);
    Test.assertEqual(s[:distTens], 43981);
    Test.assertEqual(s[:steps], 74565);
    return true;
}

(:test)
function protocolBuilderMatchesCapture(logger as Logger) as Boolean {
    Test.assert(TestUtil.bytesEqual(
        WalkingPadProtocol.buildStatusPacket(1, 45, 130, 16, 230), Fixtures.walking()));
    return true;
}
