package io.github.jawello.treadmillsync.bridge

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals

class ContractTest {
    @Test fun parsesTheBridgeSample() {
        val json = File(System.getProperty("contractDir"), "steps-response.json").readText()
        val buckets = parseStepsResponse(json)
        assertEquals(
            listOf(
                Bucket(1_759_400_000, 1_759_400_060, 105, 80.0, 1_759_400_061_250),
                Bucket(1_759_400_060, 1_759_400_120, 63, 40.0, 1_759_400_121_500),
                Bucket(1_759_400_120, 1_759_400_180, 0, 0.0, 1_759_400_181_000),
            ),
            buckets,
        )
    }
}
