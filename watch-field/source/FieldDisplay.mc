import Toybox.Lang;

// What the field shows: treadmill steps only while the link is healthy, otherwise the status.
module FieldDisplay {
    const STEPS = 0;
    const SEARCHING = 1;
    const ERROR = 2;
    const CONNECTED = 3;

    function choose(linkState as Number, connectedBanner as Boolean, dataFresh as Boolean) as Number {
        if (linkState == LinkState.SEARCHING) {
            return SEARCHING;
        }
        if (linkState == LinkState.ERROR || !dataFresh) {
            return ERROR;
        }
        return connectedBanner ? CONNECTED : STEPS;
    }
}
