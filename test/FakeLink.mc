import Toybox.Lang;

(:debug)
class FakeLink {
    var starts as Number = 0;
    var stops as Number = 0;

    function initialize() {
    }

    function sendStart() as Void {
        starts += 1;
    }

    function sendStop() as Void {
        stops += 1;
    }
}
