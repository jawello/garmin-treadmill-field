package io.github.jawello.treadmillsync.history

import io.github.jawello.treadmillsync.bridge.Bucket
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import java.io.File
import java.io.IOException

/** Minute buckets already written to Health Connect, kept for the on-screen history. */
interface HistoryStore {
    /** True until the first merge, so the next pass fetches the whole 30-day window once. */
    suspend fun needsBackfill(): Boolean
    suspend fun buckets(): List<Bucket>
    suspend fun merge(buckets: List<Bucket>, now: Long)
}

class FileHistoryStore(private val file: File, private val retentionS: Long = 30 * 86_400L) : HistoryStore {
    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun needsBackfill() = read() == null

    override suspend fun buckets() = read().orEmpty()

    override suspend fun merge(buckets: List<Bucket>, now: Long) = withContext(Dispatchers.IO) {
        val byStart = read().orEmpty().associateByTo(LinkedHashMap()) { it.start }
        for (b in buckets) {
            val old = byStart[b.start]
            if (old == null || b.version >= old.version) byStart[b.start] = b
        }
        val kept = byStart.values.filter { it.start >= now - retentionS }.sortedBy { it.start }
        val tmp = File(file.path + ".tmp")
        tmp.writeText(json.encodeToString(kept))
        if (!tmp.renameTo(file)) throw IOException("cannot replace $file")
    }

    /** Null when there is no readable history yet. */
    private suspend fun read(): List<Bucket>? = withContext(Dispatchers.IO) {
        try {
            if (file.isFile) json.decodeFromString<List<Bucket>>(file.readText()) else null
        } catch (e: SerializationException) {
            null
        } catch (e: IllegalArgumentException) {
            null
        }
    }
}
