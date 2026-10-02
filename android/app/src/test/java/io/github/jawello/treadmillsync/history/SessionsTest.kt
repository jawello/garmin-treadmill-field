package io.github.jawello.treadmillsync.history

import io.github.jawello.treadmillsync.bridge.Bucket
import java.time.LocalDate
import java.time.ZoneId
import kotlin.test.Test
import kotlin.test.assertEquals

class SessionsTest {
    private val riga = ZoneId.of("Europe/Riga")
    private fun minute(start: Long, steps: Long = 100, distance: Double = 70.0) = Bucket(start, start + 60, steps, distance, start * 1000)

    @Test fun consecutiveMinutesFormOneSession() {
        val sessions = sessionsOf(listOf(minute(1000), minute(1060), minute(1120)))
        assertEquals(listOf(Session(1000, 1180, 300, 210.0)), sessions)
    }

    @Test fun shortPauseKeepsTheSessionLongPauseSplitsIt() {
        val sessions = sessionsOf(listOf(minute(1000), minute(1180), minute(1240 + 121)))
        assertEquals(listOf(Session(1000, 1240, 200, 140.0), Session(1361, 1421, 100, 70.0)), sessions)
    }

    @Test fun unsortedInputAndEmptyInput() {
        assertEquals(listOf(Session(1000, 1120, 200, 140.0)), sessionsOf(listOf(minute(1060), minute(1000))))
        assertEquals(emptyList(), sessionsOf(emptyList()))
    }

    @Test fun sessionDerivedValues() {
        val s = Session(0, 1800, 3000, 2250.0)
        assertEquals(1800, s.durationS)
        assertEquals(4.5, s.speedKmh, 1e-9)
        assertEquals(0.0, Session(0, 0, 0, 0.0).speedKmh)
    }

    @Test fun daysAreNewestFirstWithTotalsAndSessionsByStartDay() {
        // 2026-10-01 23:50 EEST → 2026-10-02 00:10 is one session on Oct 1; another on Oct 2 at 10:00.
        val lateStart = java.time.ZonedDateTime.of(2026, 10, 1, 23, 50, 0, 0, riga).toEpochSecond()
        val morning = java.time.ZonedDateTime.of(2026, 10, 2, 10, 0, 0, 0, riga).toEpochSecond()
        val buckets = (0 until 20).map { minute(lateStart + it * 60L) } + (0 until 2).map { minute(morning + it * 60L) }
        val days = daysOf(buckets, riga)
        assertEquals(listOf(LocalDate.of(2026, 10, 2), LocalDate.of(2026, 10, 1)), days.map { it.date })
        assertEquals(200, days[0].steps)
        assertEquals(140.0, days[0].distanceM)
        assertEquals(120, days[0].durationS)
        assertEquals(1, days[1].sessions.size)
        assertEquals(2000, days[1].steps)
    }
}
