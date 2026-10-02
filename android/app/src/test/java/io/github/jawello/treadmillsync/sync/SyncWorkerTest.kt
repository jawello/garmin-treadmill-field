package io.github.jawello.treadmillsync.sync

import androidx.work.ListenableWorker.Result
import kotlin.test.Test
import kotlin.test.assertEquals

class SyncWorkerTest {
    @Test fun outcomesMapToWorkResults() {
        assertEquals(Result.success(), workResult(SyncOutcome.Success(3)))
        assertEquals(Result.retry(), workResult(SyncOutcome.BridgeUnreachable))
        assertEquals(Result.retry(), workResult(SyncOutcome.RateLimited))
        assertEquals(Result.failure(), workResult(SyncOutcome.WrongToken))
        assertEquals(Result.failure(), workResult(SyncOutcome.NotHome))
    }
}
