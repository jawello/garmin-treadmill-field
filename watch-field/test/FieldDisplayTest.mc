import Toybox.Lang;
import Toybox.Test;

(:test)
function displayShowsStepsOnlyWhenConnectedAndFresh(logger as Logger) as Boolean {
    Test.assertEqual(FieldDisplay.choose(LinkState.CONNECTED, false, true), FieldDisplay.STEPS);
    return true;
}

(:test)
function displayShowsStatusOtherwise(logger as Logger) as Boolean {
    Test.assertEqual(FieldDisplay.choose(LinkState.SEARCHING, false, false), FieldDisplay.SEARCHING);
    Test.assertEqual(FieldDisplay.choose(LinkState.ERROR, false, true), FieldDisplay.ERROR);
    Test.assertEqual(FieldDisplay.choose(LinkState.CONNECTED, true, true), FieldDisplay.CONNECTED);
    // Connected but no fresh data: show the problem, not stale steps.
    Test.assertEqual(FieldDisplay.choose(LinkState.CONNECTED, false, false), FieldDisplay.ERROR);
    return true;
}
