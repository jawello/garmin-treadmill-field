import Toybox.Lang;
import Toybox.Test;

(:test)
function layoutFullWidthWithoutSubscreen(logger as Logger) as Boolean {
    Test.assertEqual(SubscreenLayout.centerX(176, 40, null, null), 88);
    Test.assertEqual(SubscreenLayout.usableWidth(176, 40, null, null), 176);
    return true;
}

(:test)
function layoutShiftsRowsBesideSubscreen(logger as Logger) as Boolean {
    Test.assertEqual(SubscreenLayout.centerX(176, 40, 114, 62), 57);
    Test.assertEqual(SubscreenLayout.usableWidth(176, 40, 114, 62), 114);
    // Row centre just below the subscreen still has glyphs beside it.
    Test.assertEqual(SubscreenLayout.centerX(176, 63, 114, 62), 57);
    return true;
}

(:test)
function layoutFullWidthBelowSubscreen(logger as Logger) as Boolean {
    Test.assertEqual(SubscreenLayout.centerX(176, 91, 114, 62), 88);
    Test.assertEqual(SubscreenLayout.usableWidth(176, 91, 114, 62), 176);
    return true;
}

(:test)
function layoutIgnoresSubscreenOutsideField(logger as Logger) as Boolean {
    Test.assertEqual(SubscreenLayout.centerX(80, 20, -30, 62), 40);
    Test.assertEqual(SubscreenLayout.usableWidth(80, 20, -30, 62), 80);
    return true;
}
