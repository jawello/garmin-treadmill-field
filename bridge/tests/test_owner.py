from bumble.hci import Address, Role

from treadmill_bridge.owner import OwnerPresence


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Conn:
    def __init__(self, address, role=Role.PERIPHERAL):
        self.peer_address = Address(address)
        self.role = role


class Radio:
    def __init__(self, *connections):
        self.connections = {i: c for i, c in enumerate(connections)}


WATCH = "DD:73:BB:C6:19:64"


def test_bonded_watch_connected_counts():
    clock = Clock()
    radio = Radio(Conn(WATCH))
    owner = OwnerPresence([radio], clock, grace_s=300)
    owner.set_owners({WATCH})
    assert owner.present()


def test_unbonded_watch_does_not_count():
    owner = OwnerPresence([Radio(Conn("C1:22:33:44:55:66"))], Clock(), grace_s=300)
    owner.set_owners({WATCH})
    assert not owner.present()


def test_treadmill_central_link_is_not_a_watch():
    owner = OwnerPresence([Radio(Conn(WATCH, role=Role.CENTRAL))], Clock(), grace_s=300)
    owner.set_owners({WATCH})
    assert not owner.present()


def test_grace_after_watch_leaves():
    clock = Clock()
    radio = Radio(Conn(WATCH))
    owner = OwnerPresence([radio], clock, grace_s=300)
    owner.set_owners({WATCH})
    assert owner.present()
    radio.connections = {}
    clock.t = 300.0
    assert owner.present()
    clock.t = 300.1
    assert not owner.present()


def test_watch_on_any_radio_counts_and_absent_radio_is_ignored():
    owner = OwnerPresence([Radio(), None, Radio(Conn(WATCH))], Clock(), grace_s=300)
    owner.set_owners({WATCH.lower()})
    assert owner.present()
