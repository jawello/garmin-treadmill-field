import Toybox.BluetoothLowEnergy;
import Toybox.Lang;
import Toybox.WatchUi;

class GateScanner extends BluetoothLowEnergy.BleDelegate {
    var found as Boolean = false;
    hidden var _service as BluetoothLowEnergy.Uuid;

    function initialize() {
        BleDelegate.initialize();
        _service = BluetoothLowEnergy.stringToUuid("0000fe00-0000-1000-8000-00805f9b34fb");
    }

    function start() as Void {
        BluetoothLowEnergy.setDelegate(self);
        BluetoothLowEnergy.setScanState(BluetoothLowEnergy.SCAN_STATE_SCANNING);
    }

    function onScanResults(scanResults as BluetoothLowEnergy.Iterator) as Void {
        for (var r = scanResults.next(); r != null; r = scanResults.next()) {
            var uuids = (r as BluetoothLowEnergy.ScanResult).getServiceUuids();
            for (var u = uuids.next(); u != null; u = uuids.next()) {
                if ((u as BluetoothLowEnergy.Uuid).equals(_service)) {
                    found = true;
                    WatchUi.requestUpdate();
                }
            }
        }
    }
}
