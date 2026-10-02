package io.github.jawello.treadmillsync.health

import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.StepsRecord

interface HealthStore {
    suspend fun hasWritePermissions(): Boolean
    suspend fun insert(records: List<Record>)
}

class HealthConnectStore(private val client: HealthConnectClient) : HealthStore {
    override suspend fun hasWritePermissions() =
        client.permissionController.getGrantedPermissions().containsAll(PERMISSIONS)

    override suspend fun insert(records: List<Record>) {
        client.insertRecords(records)
    }

    companion object {
        val PERMISSIONS = setOf(
            HealthPermission.getWritePermission(StepsRecord::class),
            HealthPermission.getWritePermission(DistanceRecord::class),
        )
    }
}

/** Stands in when Health Connect is missing or needs an update on this phone. */
class UnavailableHealthStore : HealthStore {
    override suspend fun hasWritePermissions(): Boolean = throw IllegalStateException("Health Connect unavailable")
    override suspend fun insert(records: List<Record>) = throw IllegalStateException("Health Connect unavailable")
}
