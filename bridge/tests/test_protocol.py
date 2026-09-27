from treadmill_bridge import protocol as p
from tests import fixtures as f


def test_fixture_lengths():
    for pkt in (f.STOPPED, f.WALKING, f.BUTTON, f.COUNTDOWN, f.STOPPING):
        assert len(pkt) == 20


def test_commands():
    assert p.QUERY.hex() == "f7a20000a2fd"
    assert p.START.hex() == "f7a20401a7fd"
    assert p.STOP.hex() == "f7a20100a3fd"
    assert p.command_kind(p.QUERY) == "query"
    assert p.command_kind(p.START) == "start"
    assert p.command_kind(p.STOP) == "stop"
    assert p.command_kind(bytes.fromhex("f7a20102a5fd")) is None


def test_parses_walking():
    s = p.parse_status(f.WALKING)
    assert (s.state, s.speed_tenths, s.time_s, s.dist_tens, s.steps) == (1, 45, 130, 16, 230)
    assert s.running and abs(s.speed_mps - 1.25) < 1e-9
    assert s.raw == f.WALKING


def test_parses_other_states():
    assert p.parse_status(f.STOPPED).state == p.BELT_STOPPED
    b = p.parse_status(f.BUTTON)
    assert (b.speed_tenths, b.time_s, b.dist_tens, b.steps) == (50, 42, 4, 69)
    c = p.parse_status(f.COUNTDOWN)
    assert c.state == 9 and p.is_countdown(c.state) and c.speed_mps == 0.0
    s = p.parse_status(f.STOPPING)
    assert (s.state, s.speed_tenths, s.steps) == (p.BELT_STOPPING, 7, 14)
    assert s.speed_mps == 0.0


def test_countdown_range():
    assert [p.is_countdown(x) for x in (5, 6, 9, 10, 1)] == [False, True, True, False, False]


def test_rejects_malformed():
    bad = bytearray(f.WALKING)
    bad[18] ^= 1
    assert p.parse_status(bytes(bad)) is None
    wrong_type = bytearray(f.WALKING)
    wrong_type[1] = 0xA7
    assert p.parse_status(bytes(wrong_type)) is None
    assert p.parse_status(f.WALKING[:10]) is None
    assert p.parse_status(b"") is None
    no_footer = bytearray(f.WALKING)
    no_footer[-1] = 0
    assert p.parse_status(bytes(no_footer)) is None


def test_build_round_trip_and_large_counters():
    assert p.build_status(1, 45, 130, 16, 230) == f.WALKING
    s = p.parse_status(p.build_status(1, 45, 0x010000, 0x00ABCD, 0x012345))
    assert (s.time_s, s.dist_tens, s.steps) == (65536, 43981, 74565)
