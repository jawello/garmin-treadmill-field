from treadmill_bridge.schedule import FixedRate


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_waits_until_the_next_slot_not_a_full_period_after_the_work():
    clock = Clock()
    rate = FixedRate(1.0, clock)
    clock.t = 0.03  # the tick's own work took 30 ms
    assert abs(rate.delay() - 0.97) < 1e-9


def test_slots_stay_on_the_grid_however_long_each_tick_takes():
    clock = Clock()
    rate = FixedRate(1.0, clock)
    for n in range(1, 100):
        clock.t += 0.031  # work
        clock.t += rate.delay()
        assert abs(clock.t - n) < 1e-6


def test_a_late_tick_skips_missed_slots_instead_of_bursting():
    clock = Clock()
    rate = FixedRate(1.0, clock)
    clock.t = 2.6  # a stall (an SD card write) swallowed two slots
    assert abs(rate.delay() - 0.4) < 1e-9
