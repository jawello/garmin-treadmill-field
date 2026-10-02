package io.github.jawello.treadmillsync.history

import io.github.jawello.treadmillsync.bridge.Bucket

class MemoryHistory : HistoryStore {
    var merged: List<Bucket>? = null
    override suspend fun needsBackfill() = merged == null
    override suspend fun buckets() = merged.orEmpty()
    override suspend fun merge(buckets: List<Bucket>, now: Long) {
        merged = (merged.orEmpty() + buckets).associateBy { it.start }.values.sortedBy { it.start }
    }
}
