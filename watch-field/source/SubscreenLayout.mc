import Toybox.Lang;

// Keeps text rows clear of the Instinct round subscreen. subLeft and subBottom
// are the subscreen's left edge and bottom edge in field coordinates, or null
// when the field does not touch the subscreen.
module SubscreenLayout {
    // Half a text line: a row centred this far below the subscreen still overlaps it.
    const ROW_MARGIN = 10;

    function centerX(fieldWidth as Number, rowY as Numeric, subLeft as Number?, subBottom as Number?) as Number {
        return besideSubscreen(rowY, subLeft, subBottom) ? (subLeft as Number) / 2 : fieldWidth / 2;
    }

    function usableWidth(fieldWidth as Number, rowY as Numeric, subLeft as Number?, subBottom as Number?) as Number {
        return besideSubscreen(rowY, subLeft, subBottom) ? subLeft as Number : fieldWidth;
    }

    function besideSubscreen(rowY as Numeric, subLeft as Number?, subBottom as Number?) as Boolean {
        return subLeft != null && subBottom != null && subLeft > 0 && rowY < subBottom + ROW_MARGIN;
    }
}
