import Toybox.Activity;
import Toybox.Application;
import Toybox.FitContributor;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.Time;
import Toybox.WatchUi;

class TreadmillView extends WatchUi.DataField {
    const CONNECTED_BANNER_MS = 3000;
    const TALL_MIN_HEIGHT = 90;
    const JUSTIFY = Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER;

    hidden var _acc as SessionAccumulator;
    hidden var _link;
    hidden var _belt as BeltController;
    hidden var _speedField as FitContributor.Field;
    hidden var _distField as FitContributor.Field;
    hidden var _stepsField as FitContributor.Field;
    hidden var _prevLinkState as Number = LinkState.SEARCHING;
    hidden var _connectedSinceMs as Number? = null;
    hidden var _subLeft as Number? = null;
    hidden var _subBottom as Number? = null;
    hidden var _txtSearching as String;
    hidden var _txtConnected as String;
    hidden var _txtError as String;
    hidden var _txtSteps as String;

    function initialize() {
        DataField.initialize();
        _acc = new SessionAccumulator();
        _link = makeLink();
        _belt = new BeltController(_link);
        _speedField = createField("treadmill_speed", 0, FitContributor.DATA_TYPE_FLOAT,
            {:mesgType => FitContributor.MESG_TYPE_RECORD, :units => "km/h"});
        _distField = createField("treadmill_distance", 1, FitContributor.DATA_TYPE_FLOAT,
            {:mesgType => FitContributor.MESG_TYPE_SESSION, :units => "km"});
        _stepsField = createField("treadmill_steps", 2, FitContributor.DATA_TYPE_UINT32,
            {:mesgType => FitContributor.MESG_TYPE_SESSION, :units => "steps"});
        _txtSearching = WatchUi.loadResource(Rez.Strings.StatusSearching) as String;
        _txtConnected = WatchUi.loadResource(Rez.Strings.StatusConnected) as String;
        _txtError = WatchUi.loadResource(Rez.Strings.StatusError) as String;
        _txtSteps = WatchUi.loadResource(Rez.Strings.StepsLabel) as String;
        _link.start();
    }

    (:debug)
    hidden function makeLink() {
        return new DemoLink(method(:onStatus));
    }

    (:release)
    hidden function makeLink() {
        return new TreadmillLink(method(:onStatus));
    }

    function onStatus(status as Dictionary) as Void {
        _acc.onStatus(status, System.getTimer());
    }

    function compute(info as Activity.Info) as Numeric or Time.Duration or String or Null {
        var now = System.getTimer();
        _link.tick(now);
        _acc.tick(now);
        var linkState = _link.getState() as Number;
        if (linkState == LinkState.CONNECTED && _prevLinkState != LinkState.CONNECTED) {
            _connectedSinceMs = now;
        }
        _prevLinkState = linkState;
        _belt.tick(linkState, _acc.getBeltState(now), now);

        var speed = _acc.getSpeedMps(now);
        _speedField.setData(speed == null ? 0.0 : speed * Fmt.KMH_PER_MPS);
        _distField.setData(_acc.getTotalDistM() / Fmt.M_PER_KM);
        _stepsField.setData(_acc.getTotalSteps());
        return null;
    }

    function onTimerStart() as Void {
        handleRun();
    }

    function onTimerResume() as Void {
        handleRun();
    }

    function onTimerPause() as Void {
        handleHalt();
    }

    function onTimerStop() as Void {
        handleHalt();
    }

    function onTimerReset() as Void {
        _acc.reset();
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var bg = getBackgroundColor();
        var fg = bg == Graphics.COLOR_BLACK ? Graphics.COLOR_WHITE : Graphics.COLOR_BLACK;
        dc.setColor(fg, bg);
        dc.clear();
        dc.setColor(fg, Graphics.COLOR_TRANSPARENT);

        var w = dc.getWidth();
        var h = dc.getHeight();
        locateSubscreen(w);
        var tall = h >= TALL_MIN_HEIGHT;
        var now = System.getTimer();
        var metric = System.getDeviceSettings().distanceUnits == System.UNIT_METRIC;
        var dist = Fmt.distance(_acc.getDisplayDistM(), metric);
        var totals = dist + " | " + _acc.getTotalSteps().toString();

        var status = statusText(now);
        if (status != null) {
            if (tall && _acc.hasData()) {
                drawLine(dc, h * 0.38, Graphics.FONT_SMALL, status);
                drawLine(dc, h * 0.68, Graphics.FONT_TINY, totals);
            } else {
                drawLine(dc, h / 2, tall ? Graphics.FONT_SMALL : Graphics.FONT_TINY, status);
            }
            return;
        }

        var speed = Fmt.speed(_acc.getSpeedMps(now), metric) + " " + Fmt.speedUnit(metric);
        if (tall) {
            drawLine(dc, h * 0.24, Graphics.FONT_MEDIUM, speed);
            drawLine(dc, h * 0.52, Graphics.FONT_SMALL, dist + " " + Fmt.distanceUnit(metric));
            drawLine(dc, h * 0.78, Graphics.FONT_SMALL, _acc.getTotalSteps().toString() + " " + _txtSteps);
        } else {
            drawLine(dc, h * 0.3, Graphics.FONT_TINY, speed);
            drawLine(dc, h * 0.72, Graphics.FONT_TINY, totals);
        }
    }

    hidden function handleRun() as Void {
        var now = System.getTimer();
        _acc.setTimerRunning(true);
        _belt.onRun(controlBelt(), _link.getState() as Number, _acc.getBeltState(now));
    }

    hidden function handleHalt() as Void {
        var now = System.getTimer();
        _acc.setTimerRunning(false);
        _belt.onHalt(controlBelt(), _link.getState() as Number, _acc.getBeltState(now), now);
    }

    hidden function controlBelt() as Boolean {
        return Application.Properties.getValue("controlBelt") == true;
    }

    hidden function statusText(nowMs as Number) as String? {
        var state = _link.getState() as Number;
        if (state == LinkState.ERROR) {
            return _txtError;
        }
        if (state == LinkState.SEARCHING) {
            return _txtSearching;
        }
        if (_connectedSinceMs != null && nowMs - _connectedSinceMs < CONNECTED_BANNER_MS) {
            return _txtConnected;
        }
        return null;
    }

    // The subscreen sits in the top-right screen corner, so only a field touching
    // both the top and the right edge can be under it.
    hidden function locateSubscreen(fieldWidth as Number) as Void {
        _subLeft = null;
        _subBottom = null;
        var flags = getObscurityFlags();
        if ((flags & OBSCURE_TOP) == 0 || (flags & OBSCURE_RIGHT) == 0 || !(WatchUi has :getSubscreen)) {
            return;
        }
        var box = WatchUi.getSubscreen();
        if (box == null) {
            return;
        }
        _subLeft = box.x - (System.getDeviceSettings().screenWidth - fieldWidth);
        _subBottom = box.y + box.height;
    }

    // Draws text centred in the free width of its row, stepping the font down until it fits.
    hidden function drawLine(dc as Graphics.Dc, y as Numeric, font as Graphics.FontDefinition, text as String) as Void {
        var w = dc.getWidth();
        var x = SubscreenLayout.centerX(w, y, _subLeft, _subBottom);
        var maxWidth = SubscreenLayout.usableWidth(w, y, _subLeft, _subBottom);
        var fonts = [Graphics.FONT_MEDIUM, Graphics.FONT_SMALL, Graphics.FONT_TINY, Graphics.FONT_XTINY];
        var i = fonts.indexOf(font);
        while (i < fonts.size() - 1 && dc.getTextWidthInPixels(text, fonts[i]) > maxWidth - 4) {
            i += 1;
        }
        dc.drawText(x, y, fonts[i], text, JUSTIFY);
    }
}
