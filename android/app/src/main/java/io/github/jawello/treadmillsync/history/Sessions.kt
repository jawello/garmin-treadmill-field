package io.github.jawello.treadmillsync.history

import io.github.jawello.treadmillsync.bridge.Bucket
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/** Minutes further apart than this start a new session. */
const val SESSION_GAP_S = 120L

/** Consecutive treadmill minutes. */
data class Session(val start: Long, val end: Long, val steps: Long, val distanceM: Double) {
    val durationS: Long get() = end - start
    val speedKmh: Double get() = if (durationS > 0) distanceM / durationS * 3.6 else 0.0
}

data class DaySummary(val date: LocalDate, val sessions: List<Session>) {
    val steps: Long get() = sessions.sumOf { it.steps }
    val distanceM: Double get() = sessions.sumOf { it.distanceM }
    val durationS: Long get() = sessions.sumOf { it.durationS }
}

fun sessionsOf(buckets: List<Bucket>): List<Session> {
    val sessions = mutableListOf<Session>()
    for (b in buckets.sortedBy { it.start }) {
        val last = sessions.lastOrNull()
        if (last != null && b.start - last.end <= SESSION_GAP_S) {
            sessions[sessions.lastIndex] = Session(last.start, maxOf(last.end, b.end), last.steps + b.steps, last.distanceM + b.distanceM)
        } else {
            sessions += Session(b.start, b.end, b.steps, b.distanceM)
        }
    }
    return sessions
}

/** Sessions grouped by the local day they started on, newest day first. */
fun daysOf(buckets: List<Bucket>, zone: ZoneId): List<DaySummary> =
    sessionsOf(buckets)
        .groupBy { Instant.ofEpochSecond(it.start).atZone(zone).toLocalDate() }
        .map { (date, sessions) -> DaySummary(date, sessions) }
        .sortedByDescending { it.date }
