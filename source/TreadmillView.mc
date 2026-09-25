import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

class TreadmillView extends WatchUi.DataField {
    hidden var _gate as GateScanner;

    function initialize() {
        DataField.initialize();
        _gate = new GateScanner();
        _gate.start();
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var bg = getBackgroundColor();
        var fg = bg == Graphics.COLOR_BLACK ? Graphics.COLOR_WHITE : Graphics.COLOR_BLACK;
        dc.setColor(fg, bg);
        dc.clear();
        dc.setColor(fg, Graphics.COLOR_TRANSPARENT);
        dc.drawText(dc.getWidth() / 2, dc.getHeight() / 2, Graphics.FONT_SMALL,
            _gate.found ? "FOUND FE00" : "SCANNING",
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }
}
