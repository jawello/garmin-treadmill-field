import Toybox.BluetoothLowEnergy;
import Toybox.Lang;
import Toybox.System;

// Scans for the treadmill, keeps one connection, polls status once per tick and
// sends belt commands. Only one GATT operation is outstanding at a time.
class TreadmillLink extends BluetoothLowEnergy.BleDelegate {
    const ERROR_HOLD_MS = 3000;
    const NO_DATA_TIMEOUT_MS = 5000;
    const CONNECT_TIMEOUT_MS = 15000;
    const BUSY_TIMEOUT_MS = 2000;

    hidden var _onStatus as Method;
    hidden var _serviceUuid as BluetoothLowEnergy.Uuid;
    hidden var _notifyUuid as BluetoothLowEnergy.Uuid;
    hidden var _writeUuid as BluetoothLowEnergy.Uuid;
    hidden var _writeOptions as Dictionary;
    hidden var _state as Number = LinkState.SEARCHING;
    hidden var _device as BluetoothLowEnergy.Device? = null;
    hidden var _writeChar as BluetoothLowEnergy.Characteristic? = null;
    hidden var _ready as Boolean = false;
    hidden var _busySinceMs as Number? = null;
    hidden var _pending as Array<ByteArray> = [];
    hidden var _phaseStartMs as Number? = null;
    hidden var _lastPacketMs as Number? = null;
    hidden var _errorSinceMs as Number = 0;

    function initialize(onStatus as Method) {
        BleDelegate.initialize();
        _onStatus = onStatus;
        _serviceUuid = BluetoothLowEnergy.stringToUuid("0000fe00-0000-1000-8000-00805f9b34fb");
        _notifyUuid = BluetoothLowEnergy.stringToUuid("0000fe01-0000-1000-8000-00805f9b34fb");
        _writeUuid = BluetoothLowEnergy.stringToUuid("0000fe02-0000-1000-8000-00805f9b34fb");
        _writeOptions = {:writeType => BluetoothLowEnergy.WRITE_TYPE_DEFAULT};
    }

    function start() as Void {
        BluetoothLowEnergy.setDelegate(self);
        try {
            BluetoothLowEnergy.registerProfile({
                :uuid => _serviceUuid,
                :characteristics => [
                    {:uuid => _notifyUuid, :descriptors => [BluetoothLowEnergy.cccdUuid()]},
                    {:uuid => _writeUuid}
                ]
            });
        } catch (e) {
            // Registered by an earlier instance of the field in this session.
            log("profile register threw: " + e.getErrorMessage());
            startScan();
        }
    }

    function getState() as Number {
        return _state;
    }

    function sendStart() as Void {
        if (!_ready) {
            return;
        }
        _pending.add(WalkingPadProtocol.startCommand());
        flush(System.getTimer());
    }

    // A stop replaces anything still queued.
    function sendStop() as Void {
        if (!_ready) {
            return;
        }
        _pending = [WalkingPadProtocol.stopCommand()];
        flush(System.getTimer());
    }

    function tick(nowMs as Number) as Void {
        if (_state == LinkState.ERROR) {
            if (nowMs - _errorSinceMs >= ERROR_HOLD_MS) {
                startScan();
            }
            return;
        }
        if (_device == null) {
            return;
        }
        if (!_ready) {
            if (_phaseStartMs != null && nowMs - _phaseStartMs > CONNECT_TIMEOUT_MS) {
                enterError(nowMs, "connect timeout");
            }
            return;
        }
        var lastData = _lastPacketMs != null ? _lastPacketMs : _phaseStartMs;
        if (lastData != null && nowMs - lastData > NO_DATA_TIMEOUT_MS) {
            enterError(nowMs, "no data");
            return;
        }
        if (_busySinceMs != null && nowMs - _busySinceMs >= BUSY_TIMEOUT_MS) {
            _busySinceMs = null;
        }
        if (_pending.size() == 0) {
            _pending.add(WalkingPadProtocol.statusQuery());
        }
        flush(nowMs);
    }

    function onProfileRegister(uuid as BluetoothLowEnergy.Uuid, status as BluetoothLowEnergy.Status) as Void {
        log("profile status " + status);
        if (status == BluetoothLowEnergy.STATUS_SUCCESS) {
            startScan();
        } else {
            enterError(System.getTimer(), "profile register failed");
        }
    }

    function onScanResults(scanResults as BluetoothLowEnergy.Iterator) as Void {
        if (_device != null || _state != LinkState.SEARCHING) {
            return;
        }
        for (var r = scanResults.next(); r != null; r = scanResults.next()) {
            var result = r as BluetoothLowEnergy.ScanResult;
            if (advertisesTreadmill(result)) {
                BluetoothLowEnergy.setScanState(BluetoothLowEnergy.SCAN_STATE_OFF);
                try {
                    log("pair rssi=" + result.getRssi());
                    _device = BluetoothLowEnergy.pairDevice(result);
                    _phaseStartMs = System.getTimer();
                } catch (e) {
                    enterError(System.getTimer(), "pair exception");
                }
                return;
            }
        }
    }

    function onConnectedStateChanged(device as BluetoothLowEnergy.Device,
            state as BluetoothLowEnergy.ConnectionState) as Void {
        var now = System.getTimer();
        log("connection state " + state);
        if (state != BluetoothLowEnergy.CONNECTION_STATE_CONNECTED) {
            enterError(now, "disconnected state=" + state);
            return;
        }
        var service = device.getService(_serviceUuid);
        if (service == null) {
            enterError(now, "no FE00 service");
            return;
        }
        var notifyChar = service.getCharacteristic(_notifyUuid);
        _writeChar = service.getCharacteristic(_writeUuid);
        var cccd = notifyChar != null ? notifyChar.getDescriptor(BluetoothLowEnergy.cccdUuid()) : null;
        if (cccd == null || _writeChar == null) {
            enterError(now, "no FE01 CCCD or FE02");
            return;
        }
        _phaseStartMs = now;
        try {
            cccd.requestWrite([0x01, 0x00]b);
            _busySinceMs = now;
        } catch (e) {
            enterError(now, "CCCD write exception");
        }
    }

    function onDescriptorWrite(descriptor as BluetoothLowEnergy.Descriptor,
            status as BluetoothLowEnergy.Status) as Void {
        _busySinceMs = null;
        if (status == BluetoothLowEnergy.STATUS_SUCCESS) {
            _ready = true;
            log("notifications on");
            _phaseStartMs = System.getTimer();
        } else {
            enterError(System.getTimer(), "CCCD write status=" + status);
        }
    }

    function onCharacteristicWrite(characteristic as BluetoothLowEnergy.Characteristic,
            status as BluetoothLowEnergy.Status) as Void {
        _busySinceMs = null;
    }

    function onCharacteristicChanged(characteristic as BluetoothLowEnergy.Characteristic,
            value as ByteArray) as Void {
        if (_state == LinkState.ERROR || !characteristic.getUuid().equals(_notifyUuid)) {
            return;
        }
        var status = WalkingPadProtocol.parseStatus(value);
        if (status == null) {
            return;
        }
        if (_state != LinkState.CONNECTED) {
            log("first packet");
        }
        _state = LinkState.CONNECTED;
        _lastPacketMs = System.getTimer();
        _onStatus.invoke(status);
    }

    hidden function flush(nowMs as Number) as Void {
        if (_busySinceMs != null || _pending.size() == 0 || _writeChar == null) {
            return;
        }
        var bytes = _pending[0];
        _pending = _pending.slice(1, null);
        try {
            _writeChar.requestWrite(bytes, _writeOptions);
            _busySinceMs = nowMs;
        } catch (e) {
            enterError(nowMs, "write exception");
        }
    }

    hidden function advertisesTreadmill(result as BluetoothLowEnergy.ScanResult) as Boolean {
        var uuids = result.getServiceUuids();
        for (var u = uuids.next(); u != null; u = uuids.next()) {
            if ((u as BluetoothLowEnergy.Uuid).equals(_serviceUuid)) {
                return true;
            }
        }
        return false;
    }

    hidden function startScan() as Void {
        log("scan");
        _state = LinkState.SEARCHING;
        _device = null;
        _writeChar = null;
        _ready = false;
        _busySinceMs = null;
        _pending = [];
        _phaseStartMs = null;
        _lastPacketMs = null;
        BluetoothLowEnergy.setScanState(BluetoothLowEnergy.SCAN_STATE_SCANNING);
    }

    // Idempotent: unpairing below triggers a disconnect callback that lands here again.
    hidden function enterError(nowMs as Number, reason as String) as Void {
        if (_state == LinkState.ERROR) {
            return;
        }
        log("error: " + reason);
        _state = LinkState.ERROR;
        _errorSinceMs = nowMs;
        _ready = false;
        _busySinceMs = null;
        _pending = [];
        _writeChar = null;
        BluetoothLowEnergy.setScanState(BluetoothLowEnergy.SCAN_STATE_OFF);
        var device = _device;
        _device = null;
        if (device != null) {
            try {
                BluetoothLowEnergy.unpairDevice(device);
            } catch (e) {
                // Already gone; nothing else to release.
            }
        }
    }

    // Printed to GARMIN/APPS/LOGS/<app>.TXT on the watch when that file exists.
    hidden function log(message as String) as Void {
        System.println(System.getTimer().toString() + " link: " + message);
    }
}
