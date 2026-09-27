from treadmill_bridge import protocol as p
from treadmill_bridge.odometer import Odometer


def st(state, speed, dist_tens, steps):
    return p.parse_status(p.build_status(state, speed, 0, dist_tens, steps))


def test_first_packet_is_baseline():
    o = Odometer()
    assert o.update(st(1, 45, 16, 230), 0.0) == (0, 0.0)
    assert (o.steps_total, o.distance_m) == (0, 0.0)


def test_deltas_accumulate():
    o = Odometer()
    o.update(st(1, 45, 10, 100), 0.0)
    assert o.update(st(1, 45, 12, 130), 1.0) == (30, 20.0)
    assert (o.steps_total, o.distance_m) == (30, 20.0)


def test_counter_reset_continues_totals():
    o = Odometer()
    o.update(st(1, 45, 10, 100), 0.0)
    o.update(st(1, 45, 16, 230), 1.0)
    o.update(st(0, 0, 16, 230), 2.0)
    assert o.update(st(1, 45, 1, 5), 3.0) == (5, 10.0)
    assert (o.steps_total, o.distance_m) == (135, 70.0)


def test_smoothed_distance_capped_and_monotonic():
    o = Odometer()
    o.update(st(1, 45, 0, 0), 0.0)
    assert abs(o.smoothed_distance_m(4.0) - 5.0) < 1e-6
    assert abs(o.smoothed_distance_m(20.0) - 10.0) < 1e-6
    o.update(st(1, 45, 1, 0), 20.5)
    assert abs(o.smoothed_distance_m(20.5) - 10.0) < 1e-6
    assert abs(o.smoothed_distance_m(22.5) - 12.5) < 1e-6


def test_no_smoothing_when_stopped_or_stalled():
    o = Odometer()
    o.update(st(0, 0, 0, 0), 0.0)
    assert o.smoothed_distance_m(5.0) == 0.0
    o.update(st(1, 45, 0, 0), 5.0)
    o.stall()
    assert o.smoothed_distance_m(10.0) == 0.0


def test_cadence_over_window():
    o = Odometer()
    o.update(st(1, 45, 0, 0), 0.0)
    for i in range(1, 11):
        o.update(st(1, 45, 0, i * 2), float(i))  # 2 steps/s
    assert o.cadence_spm(10.0) == 120
    o.update(st(0, 0, 0, 20), 11.0)
    assert o.cadence_spm(11.0) == 0
