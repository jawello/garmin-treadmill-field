package io.github.jawello.treadmillsync.health

import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.StepsRecord
import io.github.jawello.treadmillsync.bridge.Bucket
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

class RecordMapperTest {
    private val riga = ZoneId.of("Europe/Riga")

    @Test fun stepsAndDistanceFromOneBucket() {
        val records = RecordMapper.toRecords(Bucket(1_759_400_000, 1_759_400_060, 105, 80.0, 1_759_400_061_250), riga)
        val steps = assertIs<StepsRecord>(records[0])
        val distance = assertIs<DistanceRecord>(records[1])
        assertEquals(105, steps.count)
        assertEquals(Instant.ofEpochSecond(1_759_400_000), steps.startTime)
        assertEquals(Instant.ofEpochSecond(1_759_400_060), steps.endTime)
        assertEquals("tmb-1759400000", steps.metadata.clientRecordId)
        assertEquals(1_759_400_061_250, steps.metadata.clientRecordVersion)
        assertEquals(80.0, distance.distance.inMeters)
        assertEquals("tmb-dist-1759400000", distance.metadata.clientRecordId)
        assertEquals(1_759_400_061_250, distance.metadata.clientRecordVersion)
        assertEquals(ZoneOffset.ofHours(3), steps.startZoneOffset) // EEST
    }

    @Test fun zeroValuesAreSkipped() {
        assertEquals(emptyList(), RecordMapper.toRecords(Bucket(1000, 1060, 0, 0.0, 1), riga))
        assertIs<StepsRecord>(RecordMapper.toRecords(Bucket(1000, 1060, 5, 0.0, 1), riga).single())
        assertIs<DistanceRecord>(RecordMapper.toRecords(Bucket(1000, 1060, 0, 10.0, 1), riga).single())
    }

    @Test fun offsetsAcrossTheAutumnDstChange() {
        // 2026-10-25 04:00 EEST (01:00 UTC) clocks go back to 03:00 EET.
        val start = Instant.parse("2026-10-25T00:59:30Z").epochSecond
        val steps = RecordMapper.toRecords(Bucket(start, start + 60, 10, 0.0, 1), riga).single() as StepsRecord
        assertEquals(ZoneOffset.ofHours(3), steps.startZoneOffset)
        assertEquals(ZoneOffset.ofHours(2), steps.endZoneOffset)
    }

    @Test fun invalidBucketYieldsNoRecords() {
        assertTrue(RecordMapper.toRecords(Bucket(1060, 1000, 10, 5.0, 1), riga).isEmpty())   // end before start
        assertTrue(RecordMapper.toRecords(Bucket(1000, 1060, 2_000_000, 5.0, 1), riga).isEmpty()) // steps over the HC limit
    }
}
