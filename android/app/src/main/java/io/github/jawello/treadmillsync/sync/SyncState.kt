package io.github.jawello.treadmillsync.sync

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.flow.first

data class SyncSnapshot(
    val watermark: Long? = null,
    val lastSuccessAt: Long? = null,
    val lastWritten: Int = 0,
    val lastAttemptAt: Long? = null,
    val lastOutcome: String? = null,
)

interface SyncStateStore {
    suspend fun read(): SyncSnapshot
    suspend fun recordSuccess(watermark: Long, at: Long, written: Int)
    suspend fun recordFailure(at: Long, outcomeKey: String)
}

class DataStoreSyncState(private val store: DataStore<Preferences>) : SyncStateStore {
    private val watermark = longPreferencesKey("watermark")
    private val lastSuccessAt = longPreferencesKey("last_success_at")
    private val lastWritten = intPreferencesKey("last_written")
    private val lastAttemptAt = longPreferencesKey("last_attempt_at")
    private val lastOutcome = stringPreferencesKey("last_outcome")

    override suspend fun read(): SyncSnapshot {
        val p = store.data.first()
        return SyncSnapshot(p[watermark], p[lastSuccessAt], p[lastWritten] ?: 0, p[lastAttemptAt], p[lastOutcome])
    }

    override suspend fun recordSuccess(watermark: Long, at: Long, written: Int) {
        store.edit {
            it[this.watermark] = watermark
            it[lastSuccessAt] = at
            it[lastWritten] = written
            it[lastAttemptAt] = at
            it[lastOutcome] = "Success"
        }
    }

    override suspend fun recordFailure(at: Long, outcomeKey: String) {
        store.edit {
            it[lastAttemptAt] = at
            it[lastOutcome] = outcomeKey
        }
    }
}
