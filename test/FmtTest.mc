import Toybox.Lang;
import Toybox.Test;

(:test)
function fmtSpeed(logger as Logger) as Boolean {
    Test.assertEqual(Fmt.speed(1.25, true), "4.5");
    Test.assertEqual(Fmt.speed(1.25, false), "2.8");
    Test.assertEqual(Fmt.speed(0.0, true), "0.0");
    Test.assertEqual(Fmt.speed(null, true), "--");
    return true;
}

(:test)
function fmtDistance(logger as Logger) as Boolean {
    Test.assertEqual(Fmt.distance(160.0, true), "0.16");
    Test.assertEqual(Fmt.distance(1340.0, true), "1.34");
    Test.assertEqual(Fmt.distance(1609.344, false), "1.00");
    Test.assertEqual(Fmt.distance(0.0, false), "0.00");
    return true;
}

(:test)
function fmtUnits(logger as Logger) as Boolean {
    Test.assertEqual(Fmt.speedUnit(true), "km/h");
    Test.assertEqual(Fmt.speedUnit(false), "mph");
    Test.assertEqual(Fmt.distanceUnit(true), "km");
    Test.assertEqual(Fmt.distanceUnit(false), "mi");
    return true;
}
