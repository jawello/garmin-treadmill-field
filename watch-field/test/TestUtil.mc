import Toybox.Lang;

(:debug)
module TestUtil {
    function bytesEqual(a as ByteArray, b as ByteArray) as Boolean {
        if (a.size() != b.size()) {
            return false;
        }
        for (var i = 0; i < a.size(); i++) {
            if (a[i] != b[i]) {
                return false;
            }
        }
        return true;
    }

    function near(a as Numeric, b as Numeric) as Boolean {
        return (a - b).abs() < 0.001;
    }
}
