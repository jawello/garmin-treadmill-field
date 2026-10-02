package io.github.jawello.treadmillsync.health

import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.metadata.Device
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.units.Length
import io.github.jawello.treadmillsync.bridge.Bucket
import java.time.Instant
import java.time.ZoneId

/** Turns a bridge minute bucket into Health Connect records with stable ids for upserts. */
object RecordMapper {
    const val STEPS_PREFIX = "tmb-"
    const val DISTANCE_PREFIX = "tmb-dist-"

    private val treadmill = Device(type = Device.TYPE_UNKNOWN, manufacturer = "Kingsmith", model = "R1 Pro")

    fun toRecords(bucket: Bucket, zone: ZoneId): List<Record> {
        val start = Instant.ofEpochSecond(bucket.start)
        val end = Instant.ofEpochSecond(bucket.end)
        val startOffset = zone.rules.getOffset(start)
        val endOffset = zone.rules.getOffset(end)
        return try {
            buildList {
                if (bucket.steps > 0) {
                    add(StepsRecord(
                        startTime = start, startZoneOffset = startOffset,
                        endTime = end, endZoneOffset = endOffset,
                        count = bucket.steps,
                        metadata = Metadata.autoRecorded(treadmill, "$STEPS_PREFIX${bucket.start}", bucket.version),
                    ))
                }
                if (bucket.distanceM > 0) {
                    add(DistanceRecord(
                        startTime = start, startZoneOffset = startOffset,
                        endTime = end, endZoneOffset = endOffset,
                        distance = Length.meters(bucket.distanceM),
                        metadata = Metadata.autoRecorded(treadmill, "$DISTANCE_PREFIX${bucket.start}", bucket.version),
                    ))
                }
            }
        } catch (e: IllegalArgumentException) { // HC validates times and value ranges in constructors
            emptyList()
        }
    }
}
