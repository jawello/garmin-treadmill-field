package io.github.jawello.treadmillsync.sync

class MemorySyncState(var snapshot: SyncSnapshot = SyncSnapshot()) : SyncStateStore {
    override suspend fun read() = snapshot
    override suspend fun recordSuccess(since: Long, watermark: Long, at: Long, written: Int) {
        snapshot = SyncSnapshot(watermark, at, written, at, "Success", since)
    }
    override suspend fun recordFailure(at: Long, outcomeKey: String) {
        snapshot = snapshot.copy(lastAttemptAt = at, lastOutcome = outcomeKey)
    }
}
