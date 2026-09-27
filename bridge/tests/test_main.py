from treadmill_bridge.main import open_optional_radio


class Device:
    def __init__(self, fail_power_on=False):
        self.fail_power_on = fail_power_on

    async def power_on(self):
        if self.fail_power_on:
            raise OSError("firmware rtl8761bu_fw.bin not found")


class Transport:
    closed = False

    async def close(self):
        self.closed = True


async def test_broken_usb_adapter_is_skipped():
    async def opener(index, name, keystore):
        raise OSError("hci1: device busy")

    assert await open_optional_radio(opener, 1, "b", "k") == (None, None)


async def test_adapter_that_fails_to_power_on_is_closed_and_skipped():
    transport = Transport()

    async def opener(index, name, keystore):
        return Device(fail_power_on=True), transport

    assert await open_optional_radio(opener, 1, "b", "k") == (None, None)
    assert transport.closed


async def test_working_adapter_is_returned_powered():
    device, transport = Device(), Transport()

    async def opener(index, name, keystore):
        return device, transport

    assert await open_optional_radio(opener, 1, "b", "k") == (device, transport)
