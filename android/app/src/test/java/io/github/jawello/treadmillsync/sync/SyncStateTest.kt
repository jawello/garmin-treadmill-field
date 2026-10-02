package io.github.jawello.treadmillsync.sync

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Rule
import org.junit.rules.TemporaryFolder
import kotlin.test.Test
import kotlin.test.assertEquals

class SyncStateTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun successAndFailureAreKeptSeparately() = runTest(UnconfinedTestDispatcher()) {
        val file = tmp.root.resolve("s.preferences_pb")
        val state = DataStoreSyncState(PreferenceDataStoreFactory.create(scope = backgroundScope) { file })
        assertEquals(SyncSnapshot(), state.read())
        state.recordSuccess(watermark = 5000, at = 5060, written = 12)
        state.recordFailure(at = 6000, outcomeKey = "BridgeUnreachable")
        assertEquals(SyncSnapshot(5000, 5060, 12, 6000, "BridgeUnreachable"), state.read())
        state.recordSuccess(watermark = 7000, at = 7060, written = 0)
        assertEquals(SyncSnapshot(7000, 7060, 0, 7060, "Success"), state.read())
    }
}
