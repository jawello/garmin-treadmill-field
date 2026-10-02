package io.github.jawello.treadmillsync.sync

import android.os.RemoteException
import io.github.jawello.treadmillsync.bridge.BridgeApi
import io.github.jawello.treadmillsync.bridge.BridgeException
import io.github.jawello.treadmillsync.health.HealthStore
import io.github.jawello.treadmillsync.health.RecordMapper
import io.github.jawello.treadmillsync.net.GateResult
import io.github.jawello.treadmillsync.net.NetworkGate
import io.github.jawello.treadmillsync.settings.Settings
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.IOException
import java.time.Instant
import java.time.ZoneId

/** One sync pass: bridge minute buckets → Health Connect, idempotent and resumable. */
class SyncEngine(
    private val settings: suspend () -> Settings,
    private val gate: NetworkGate,
    private val bridge: (Settings) -> BridgeApi,
    private val health: HealthStore,
    private val state: SyncStateStore,
    private val clock: () -> Instant = Instant::now,
    private val zone: () -> ZoneId = ZoneId::systemDefault,
) {
    suspend fun sync(): SyncOutcome = LOCK.withLock {
        val now = clock().epochSecond
        val outcome = pass(now)
        if (outcome !is SyncOutcome.Success) state.recordFailure(now, outcome.key)
        outcome
    }

    private suspend fun pass(now: Long): SyncOutcome {
        val s = settings().normalized()
        if (!s.configured) return SyncOutcome.NotConfigured
        when (gate.check(s.homeSsid)) {
            GateResult.NOT_HOME -> return SyncOutcome.NotHome
            GateResult.UNKNOWN -> return SyncOutcome.NetworkUnknown
            GateResult.OPEN -> Unit
        }
        healthCall { if (!health.hasWritePermissions()) return SyncOutcome.PermissionsMissing }?.let { return it }

        val window = window(now, state.read().watermark)
        val buckets = try {
            bridge(s).steps(window.first, window.last)
        } catch (e: BridgeException) {
            return e.toOutcome()
        }
        val zoneId = zone()
        val records = buckets.flatMap { RecordMapper.toRecords(it, zoneId) }
        healthCall { records.chunked(BATCH).forEach { health.insert(it) } }?.let { return it }

        state.recordSuccess(watermark = window.last, at = now, written = records.size)
        return SyncOutcome.Success(records.size)
    }

    /** Runs a Health Connect call; returns the failure outcome, or null when it succeeded. */
    private inline fun healthCall(block: () -> Unit): SyncOutcome? = try {
        block()
        null
    } catch (e: CancellationException) {
        throw e // a CancellationException is an IllegalStateException: never map it to an outcome
    } catch (e: SecurityException) {
        SyncOutcome.PermissionsMissing
    } catch (e: Exception) {
        if (e !is IOException && e !is RemoteException && e !is IllegalStateException) throw e
        val message = e.message.orEmpty().lowercase()
        if ("rate limit" in message || "quota" in message) SyncOutcome.RateLimited else SyncOutcome.HealthConnectUnavailable
    }

    private fun BridgeException.toOutcome(): SyncOutcome = when (this) {
        is BridgeException.Unreachable -> SyncOutcome.BridgeUnreachable
        is BridgeException.CleartextBlocked -> SyncOutcome.CleartextBlocked
        is BridgeException.Unauthorized, is BridgeException.BadToken -> SyncOutcome.WrongToken
        is BridgeException.BadResponse -> SyncOutcome.BridgeError(code)
        is BridgeException.BadUrl -> SyncOutcome.BridgeError(null)
    }

    companion object {
        const val BATCH = 1000
        private const val OVERLAP_S = 3_600L
        private const val SETTLE_S = 60L
        private const val HISTORY_S = 30 * 86_400L
        private val LOCK = Mutex() // the worker and "Sync now" never run a pass at the same time

        fun window(now: Long, watermark: Long?): LongRange {
            val until = now - SETTLE_S
            val floor = now - HISTORY_S
            val since = if (watermark == null) floor else maxOf(minOf(watermark, until) - OVERLAP_S, floor)
            return since..until
        }
    }
}
