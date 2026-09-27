import Toybox.Lang;

module Fmt {
    const KMH_PER_MPS = 3.6;
    const MPH_PER_MPS = 2.2369363;
    const M_PER_KM = 1000.0;
    const M_PER_MILE = 1609.344;

    function speed(mps as Float?, metric as Boolean) as String {
        if (mps == null) {
            return "--";
        }
        return (mps * (metric ? KMH_PER_MPS : MPH_PER_MPS)).format("%.1f");
    }

    function distance(meters as Float, metric as Boolean) as String {
        return (meters / (metric ? M_PER_KM : M_PER_MILE)).format("%.2f");
    }

    function speedUnit(metric as Boolean) as String {
        return metric ? "km/h" : "mph";
    }

    function distanceUnit(metric as Boolean) as String {
        return metric ? "km" : "mi";
    }
}
