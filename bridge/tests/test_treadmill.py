import asyncio

from bumble.hci import Address, OwnAddressType

from treadmill_bridge import protocol as p
from treadmill_bridge.hub import StatusHub
from treadmill_bridge.treadmill import TreadmillClient, parse_address
from tests.fakes import FakeTreadmill, virtual_device

FAST = dict(poll_interval=0.05, write_gap=0.02, stale_after=0.5, backoff=(0.05,), scan_timeout=2.0, connect_timeout=2.0)


async def setup(link, address_known=True):
    tm = FakeTreadmill(virtual_device(link, "treadmill"))
    tm.install()
    await tm.start()
    radio = virtual_device(link, "bridge-a")
    await radio.power_on()
    hub = StatusHub()
    found = []
    client = TreadmillClient(
        radio,
        hub,
        str(tm.device.random_address) if address_known else None,
        OwnAddressType.RANDOM,
        on_address=found.append,
        **FAST,
    )
    task = asyncio.create_task(client.run())
    return tm, hub, client, task, found


async def wait_for(predicate, timeout=3.0):
    for _ in range(int(timeout / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met")


def test_parse_address():
    public = parse_address("57:4C:4D:2F:0C:93/P")
    assert public.address_type == Address.PUBLIC_DEVICE_ADDRESS
    assert str(public).startswith("57:4C:4D:2F:0C:93")
    assert parse_address("C0:00:00:00:00:01").address_type == Address.RANDOM_DEVICE_ADDRESS


async def test_connects_polls_and_publishes(link):
    tm, hub, _, task, _ = await setup(link)
    try:
        await wait_for(lambda: hub.link_up and hub.latest is not None)
        await wait_for(lambda: tm.writes.count(p.QUERY) >= 3)
        assert set(tm.writes) == {p.QUERY}
    finally:
        task.cancel()


async def test_discovers_address_by_scanning(link):
    tm, hub, _, task, found = await setup(link, address_known=False)
    try:
        await wait_for(lambda: hub.link_up)
        assert found and found[0].startswith(str(tm.device.random_address)[:17])
    finally:
        task.cancel()


async def test_stop_replaces_pending_start_and_goes_first(link):
    tm, hub, client, task, _ = await setup(link)
    try:
        await wait_for(lambda: hub.link_up)
        client.send_command(p.START)
        client.send_command(p.STOP)
        await wait_for(lambda: p.STOP in tm.writes)
        assert p.START not in tm.writes
        client.send_command(p.START)
        await wait_for(lambda: p.START in tm.writes)
        assert hub.last_start_at is not None
    finally:
        task.cancel()


async def test_reconnects_after_drop(link):
    tm, hub, _, task, _ = await setup(link)
    try:
        await wait_for(lambda: hub.link_up)
        changes = []
        hub.on_link(changes.append)
        await tm.drop()
        await wait_for(lambda: changes[:2] == [False, True])
    finally:
        task.cancel()
