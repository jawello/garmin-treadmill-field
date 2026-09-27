import Toybox.Lang;

// Kingsmith/WalkingPad FE00 protocol, verified on an R1 Pro.
module WalkingPadProtocol {
    const BELT_STOPPED = 0;
    const BELT_RUNNING = 1;
    const BELT_STOPPING = 3;
    const MIN_STATUS_LENGTH = 19;

    function statusQuery() as ByteArray {
        return [0xF7, 0xA2, 0x00, 0x00, 0xA2, 0xFD]b;
    }

    function startCommand() as ByteArray {
        return [0xF7, 0xA2, 0x04, 0x01, 0xA7, 0xFD]b;
    }

    function stopCommand() as ByteArray {
        return [0xF7, 0xA2, 0x01, 0x00, 0xA3, 0xFD]b;
    }

    // States 9..6 are the pre-start countdown.
    function isCountdown(state as Number) as Boolean {
        return state >= 6 && state <= 9;
    }

    // Returns {:state, :speedTenths, :timeS, :distTens, :steps} or null for anything
    // that is not a valid status packet.
    function parseStatus(bytes as ByteArray?) as Dictionary? {
        if (bytes == null) {
            return null;
        }
        var n = bytes.size();
        if (n < MIN_STATUS_LENGTH) {
            return null;
        }
        if (bytes[0] != 0xF8 || bytes[1] != 0xA2 || bytes[n - 1] != 0xFD) {
            return null;
        }
        var sum = 0;
        for (var i = 1; i <= n - 3; i++) {
            sum += bytes[i];
        }
        if ((sum & 0xFF) != bytes[n - 2]) {
            return null;
        }
        return {
            :state => bytes[2],
            :speedTenths => bytes[3],
            :timeS => readU24(bytes, 5),
            :distTens => readU24(bytes, 8),
            :steps => readU24(bytes, 11)
        };
    }

    function readU24(bytes as ByteArray, offset as Number) as Number {
        return (bytes[offset] << 16) | (bytes[offset + 1] << 8) | bytes[offset + 2];
    }

    (:debug)
    function buildStatusPacket(state as Number, speedTenths as Number, timeS as Number,
            distTens as Number, steps as Number) as ByteArray {
        var b = new [20]b;
        b[0] = 0xF8;
        b[1] = 0xA2;
        b[2] = state;
        b[3] = speedTenths;
        b[4] = 0x01;
        writeU24(b, 5, timeS);
        writeU24(b, 8, distTens);
        writeU24(b, 11, steps);
        var sum = 0;
        for (var i = 1; i <= 17; i++) {
            sum += b[i];
        }
        b[18] = sum & 0xFF;
        b[19] = 0xFD;
        return b;
    }

    (:debug)
    function writeU24(b as ByteArray, offset as Number, value as Number) as Void {
        b[offset] = (value >> 16) & 0xFF;
        b[offset + 1] = (value >> 8) & 0xFF;
        b[offset + 2] = value & 0xFF;
    }
}
