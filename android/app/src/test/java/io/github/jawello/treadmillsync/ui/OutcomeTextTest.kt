package io.github.jawello.treadmillsync.ui

import io.github.jawello.treadmillsync.R
import io.github.jawello.treadmillsync.sync.SyncOutcome
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

class OutcomeTextTest {
    @Test fun everyOutcomeHasText() {
        val outcomes = listOf(SyncOutcome.Success(1), SyncOutcome.NotConfigured, SyncOutcome.NotHome, SyncOutcome.NetworkUnknown,
            SyncOutcome.BridgeUnreachable, SyncOutcome.CleartextBlocked, SyncOutcome.WrongToken, SyncOutcome.BridgeError(400),
            SyncOutcome.BridgeError(null), SyncOutcome.PermissionsMissing, SyncOutcome.HealthConnectUnavailable, SyncOutcome.RateLimited)
        for (o in outcomes) assertNotEquals(R.string.outcome_unknown, outcomeTextRes(o.key), o.key)
        assertEquals(R.string.outcome_bridge_error, outcomeTextRes("BridgeError:400"))
        assertEquals(0, outcomeTextRes(null))
        assertEquals(R.string.outcome_unknown, outcomeTextRes("Something"))
    }
}
