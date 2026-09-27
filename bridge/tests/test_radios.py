import os

from treadmill_bridge.radios import find_controllers


def make_hci(root, name, target):
    device_dir = root / "devices" / target
    device_dir.mkdir(parents=True)
    hci = root / "class" / name
    hci.mkdir(parents=True)
    os.symlink(device_dir, hci / "device")


def test_maps_uart_and_usb(tmp_path):
    make_hci(tmp_path, "hci0", "platform/soc/serial0/serial0-0")
    make_hci(tmp_path, "hci1", "platform/soc/usb1/1-1/1-1.2/1-1.2:1.0")
    assert find_controllers(str(tmp_path / "class")) == {"uart": 0, "usb": 1}


def test_missing_root_or_usb(tmp_path):
    assert find_controllers(str(tmp_path / "none")) == {}
    make_hci(tmp_path, "hci0", "platform/soc/serial0/serial0-0")
    assert find_controllers(str(tmp_path / "class")) == {"uart": 0}
