package io.github.jawello.treadmillsync.history

import io.github.jawello.treadmillsync.bridge.Bucket
import kotlinx.coroutines.test.runTest
import org.junit.Rule
import org.junit.rules.TemporaryFolder
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class FileHistoryStoreTest {
    @get:Rule val tmp = TemporaryFolder()
    private val day = 86_400L
    private val now = 100 * day

    @Test fun backfillNeededUntilTheFirstMerge() = runTest {
        val store = FileHistoryStore(tmp.root.resolve("h.json"))
        assertTrue(store.needsBackfill())
        store.merge(emptyList(), now)
        assertFalse(store.needsBackfill())
        assertEquals(emptyList(), store.buckets())
    }

    @Test fun mergeKeepsNewestVersionPrunesOldAndPersists() = runTest {
        val file = tmp.root.resolve("h.json")
        val store = FileHistoryStore(file)
        store.merge(listOf(Bucket(now - 31 * day, now - 31 * day + 60, 5, 1.0, 1), Bucket(now - 600, now - 540, 50, 30.0, 1)), now)
        store.merge(listOf(Bucket(now - 600, now - 540, 80, 55.0, 2), Bucket(now - 540, now - 480, 10, 7.0, 1)), now)
        store.merge(listOf(Bucket(now - 600, now - 540, 1, 1.0, 0)), now) // older version is ignored
        val expected = listOf(Bucket(now - 600, now - 540, 80, 55.0, 2), Bucket(now - 540, now - 480, 10, 7.0, 1))
        assertEquals(expected, store.buckets())
        assertEquals(expected, FileHistoryStore(file).buckets())
    }

    @Test fun unreadableFileIsTreatedAsEmpty() = runTest {
        val file = tmp.root.resolve("h.json").apply { writeText("not json") }
        val store = FileHistoryStore(file)
        assertEquals(emptyList(), store.buckets())
        assertTrue(store.needsBackfill())
    }
}
