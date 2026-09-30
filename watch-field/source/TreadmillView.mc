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
        // A field added mid-workout never saw onTimerStart; the belt stays event-driven.
        if (info has :timerState && info.timerState != null) {
            _acc.setTimerRunning(info.timerState == Activity.TIMER_STATE_ON);
        }
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

        var h = dc.getHeight();
        locateSubscreen(dc.getWidth());
        var tall = h >= TALL_MIN_HEIGHT;
        var now = System.getTimer();
        var kind = FieldDisplay.choose(_link.getState() as Number, bannerActive(now), _acc.getSpeedMps(now) != null);
        if (kind != FieldDisplay.STEPS) {
            drawLine(dc, h / 2, tall ? Graphics.FONT_SMALL : Graphics.FONT_TINY, statusText(kind));
            return;
        }
        drawLine(dc, h * 0.46, tall ? Graphics.FONT_TINY : Graphics.FONT_XTINY, _txtSteps);
        drawNumber(dc, h * 0.75, h * 0.45, _acc.getTotalSteps().toString());
    }

    hidden function handleRun() as Void {
        var now = System.getTimer();
        _acc.setTimerRunning(true);
        _belt.onRun(controlBelt(), _link.getState() as Number, _acc.getBeltState(now), now);
    }

    hidden function handleHalt() as Void {
        var now = System.getTimer();
        _acc.setTimerRunning(false);
        _belt.onHalt(controlBelt(), _link.getState() as Number, _acc.getBeltState(now), now);
    }

    hidden function controlBelt() as Boolean {
        return Application.Properties.getValue("controlBelt") == true;
    }

    hidden function bannerActive(nowMs as Number) as Boolean {
        return _connectedSinceMs != null && nowMs - _connectedSinceMs < CONNECTED_BANNER_MS;
    }

    hidden function statusText(kind as Number) as String {
        if (kind == FieldDisplay.SEARCHING) {
            return _txtSearching;
        }
        return kind == FieldDisplay.CONNECTED ? _txtConnected : _txtError;
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

    // The step count: the biggest number font that fits the free width and the given height.
    hidden function drawNumber(dc as Graphics.Dc, y as Numeric, maxHeight as Numeric, text as String) as Void {
        var w = dc.getWidth();
        var maxWidth = SubscreenLayout.usableWidth(w, y, _subLeft, _subBottom) - 4;
        var fonts = [Graphics.FONT_NUMBER_HOT, Graphics.FONT_NUMBER_MEDIUM, Graphics.FONT_NUMBER_MILD,
            Graphics.FONT_LARGE, Graphics.FONT_MEDIUM, Graphics.FONT_SMALL];
        var chosen = fonts[fonts.size() - 1];
        for (var i = 0; i < fonts.size(); i++) {
            if (dc.getTextWidthInPixels(text, fonts[i]) <= maxWidth && dc.getFontHeight(fonts[i]) <= maxHeight) {
                chosen = fonts[i];
                break;
            }
        }
        dc.drawText(SubscreenLayout.centerX(w, y, _subLeft, _subBottom), y, chosen, text, JUSTIFY);
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
