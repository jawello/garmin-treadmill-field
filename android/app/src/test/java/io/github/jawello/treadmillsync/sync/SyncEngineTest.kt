package io.github.jawello.treadmillsync.sync

import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.testing.FakeHealthConnectClient
import androidx.health.connect.client.testing.FakePermissionController
import androidx.health.connect.client.time.TimeRangeFilter
import io.github.jawello.treadmillsync.bridge.BridgeApi
import io.github.jawello.treadmillsync.bridge.BridgeException
import io.github.jawello.treadmillsync.bridge.Bucket
import io.github.jawello.treadmillsync.health.HealthConnectStore
import io.github.jawello.treadmillsync.health.HealthStore
import io.github.jawello.treadmillsync.net.NetworkGate
import io.github.jawello.treadmillsync.settings.Settings
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import java.io.IOException
import java.time.Instant
import java.time.ZoneId
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

private const val NOW = 1_759_500_000L
private const val DAY = 86_400L

class FakeBridge(var buckets: List<Bucket> = emptyList(), var error: BridgeException? = null) : BridgeApi {
    val calls = mutableListOf<LongRange>()
    override suspend fun steps(since: Long, until: Long): List<Bucket> {
        calls += since..until
        error?.let { throw it }
        return buckets.filter { it.start >= since && it.end <= until }
    }
    override suspend fun ping() {}
}

/** Wraps a real store and fails the n-th insert (1-based). */
class FlakyHealth(private val inner: HealthStore, private val failOn: Int, private val error: Exception) : HealthStore {
    var inserts = 0
    override suspend fun hasWritePermissions() = inner.hasWritePermissions()
    override suspend fun insert(records: List<Record>) {
        inserts++
        if (inserts == failOn) throw error
        inner.insert(records)
    }
}

class SyncEngineTest {
    private val fakeClient = FakeHealthConnectClient()
    private val health = HealthConnectStore(fakeClient)
    private val state = MemorySyncState()
    private val bridge = FakeBridge()
    private var settings = Settings(token = "t")
    private var ssid: String? = "home"

    private fun engine(store: HealthStore = health, now: Long = NOW) = SyncEngine(
        settings = { settings }, gate = NetworkGate { ssid }, bridge = { bridge }, health = store, state = state,
        clock = { Instant.ofEpochSecond(now) }, zone = { ZoneId.of("Europe/Riga") },
    )

    private fun minutes(count: Int, from: Long = NOW - 3_600) =
        (0 until count).map { Bucket(from + it * 60L, from + it * 60L + 60, 100, 70.0, (from + it * 60L + 70) * 1000) }

    private suspend fun stepRecords() = fakeClient.readRecords(
        ReadRecordsRequest(StepsRecord::class, TimeRangeFilter.after(Instant.EPOCH), pageSize = 5000)).records
    private suspend fun distanceRecords() = fakeClient.readRecords(
        ReadRecordsRequest(DistanceRecord::class, TimeRangeFilter.after(Instant.EPOCH), pageSize = 5000)).records

    @Test fun windowRules() {
        assertEquals((NOW - 30 * DAY)..(NOW - 60), SyncEngine.window(NOW, null))
        assertEquals((NOW - 7_200 - 3_600)..(NOW - 60), SyncEngine.window(NOW, NOW - 7_200))
        assertEquals((NOW - 30 * DAY)..(NOW - 60), SyncEngine.window(NOW, NOW - 40 * DAY))
    }

    @Test fun watermarkInFutureIsClamped() {
        val w = SyncEngine.window(NOW, NOW + 10 * DAY)
        assertEquals((NOW - 60 - 3_600)..(NOW - 60), w)
    }

    @Test fun firstRunBackfillsAndWritesStepsAndDistance() = runTest {
        bridge.buckets = minutes(3)
        val outcome = engine().sync()
        assertEquals(SyncOutcome.Success(6), outcome)
        assertEquals(listOf((NOW - 30 * DAY)..(NOW - 60)), bridge.calls)
        assertEquals(3, stepRecords().size)
        assertEquals(3, distanceRecords().size)
        assertEquals(NOW - 60, state.snapshot.watermark)
    }

    @Test fun resyncWritesNoDuplicates() = runTest {
        bridge.buckets = minutes(3)
        engine().sync()
        engine(now = NOW + 600).sync()
        assertEquals(300L, stepRecords().sumOf { (it as StepsRecord).count })
        assertEquals(3, stepRecords().size)
        assertEquals((NOW - 60 - 3_600)..(NOW + 540), bridge.calls[1])
    }

    @Test fun batchesOfAtMostOneThousand() = runTest {
        bridge.buckets = minutes(600, from = NOW - 2 * DAY) // 1200 records
        val counting = FlakyHealth(health, failOn = -1, error = IOException())
        assertEquals(SyncOutcome.Success(1200), engine(counting).sync())
        assertEquals(2, counting.inserts)
    }

    @Test fun failureInTheMiddleKeepsWatermarkAndNextPassCompletes() = runTest {
        bridge.buckets = minutes(600, from = NOW - 2 * DAY)
        val flaky = FlakyHealth(health, failOn = 2, error = IOException("binder died"))
        assertEquals(SyncOutcome.HealthConnectUnavailable, engine(flaky).sync())
        assertEquals(null, state.snapshot.watermark)
        assertEquals("HealthConnectUnavailable", state.snapshot.lastOutcome)
        assertEquals(SyncOutcome.Success(1200), engine().sync())
        assertEquals(600, stepRecords().size)
    }

    @Test fun rateLimitIsRetried() = runTest {
        bridge.buckets = minutes(1)
        val limited = FlakyHealth(health, failOn = 1, error = IOException("Rate limit exceeded"))
        val outcome = engine(limited).sync()
        assertEquals(SyncOutcome.RateLimited, outcome)
        assertTrue(outcome.retry)
    }

    @Test fun securityExceptionMeansPermissions() = runTest {
        bridge.buckets = minutes(1)
        val denied = FlakyHealth(health, failOn = 1, error = SecurityException())
        assertEquals(SyncOutcome.PermissionsMissing, engine(denied).sync())
    }

    @Test fun missingPermissionsStopBeforeTheBridge() = runTest {
        val noPerms = FakeHealthConnectClient(permissionController = FakePermissionController(grantAll = false))
        assertEquals(SyncOutcome.PermissionsMissing, engine(HealthConnectStore(noPerms)).sync())
        assertTrue(bridge.calls.isEmpty())
    }

    @Test fun notConfiguredWhenTokenBlank() = runTest {
        settings = Settings(token = "  ")
        assertEquals(SyncOutcome.NotConfigured, engine().sync())
        assertTrue(bridge.calls.isEmpty())
    }

    @Test fun gateOutcomes() = runTest {
        settings = Settings(token = "t", homeSsid = "home")
        ssid = "cafe"
        assertEquals(SyncOutcome.NotHome, engine().sync())
        ssid = null
        assertEquals(SyncOutcome.NetworkUnknown, engine().sync())
        assertTrue(bridge.calls.isEmpty())
        ssid = "home"
        assertEquals(SyncOutcome.Success(0), engine().sync())
        settings = Settings(token = "t", homeSsid = "")
        ssid = null
        assertEquals(SyncOutcome.Success(0), engine().sync())
    }

    @Test fun bridgeErrorsMapToOutcomes() = runTest {
        val cases = mapOf(
            BridgeException.Unreachable(IOException()) to SyncOutcome.BridgeUnreachable,
            BridgeException.Unauthorized() to SyncOutcome.WrongToken,
            BridgeException.BadToken() to SyncOutcome.WrongToken,
            BridgeException.BadResponse(400) to SyncOutcome.BridgeError(400),
            BridgeException.BadUrl() to SyncOutcome.BridgeError(null),
            BridgeException.CleartextBlocked() to SyncOutcome.CleartextBlocked,
        )
        for ((error, expected) in cases) {
            bridge.error = error
            assertEquals(expected, engine().sync(), error::class.simpleName)
        }
        assertEquals(null, state.snapshot.watermark)
    }

    @Test fun retryOnlyForTransientOutcomes() {
        val retried = listOf(SyncOutcome.BridgeUnreachable, SyncOutcome.HealthConnectUnavailable, SyncOutcome.RateLimited)
        val all = retried + listOf(SyncOutcome.Success(1), SyncOutcome.NotConfigured, SyncOutcome.NotHome,
            SyncOutcome.NetworkUnknown, SyncOutcome.CleartextBlocked, SyncOutcome.WrongToken, SyncOutcome.BridgeError(400),
            SyncOutcome.PermissionsMissing)
        assertEquals(retried, all.filter { it.retry })
    }

    @Test fun concurrentPassesDoNotOverlap() = runTest {
        bridge.buckets = minutes(3)
        val a = async { engine().sync() }
        val b = async { engine().sync() }
        assertEquals(SyncOutcome.Success(6), a.await())
        assertEquals(SyncOutcome.Success(6), b.await())
        assertEquals(3, stepRecords().size)
    }
}
