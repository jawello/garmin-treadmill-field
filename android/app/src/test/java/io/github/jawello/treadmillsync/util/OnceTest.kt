package io.github.jawello.treadmillsync.util

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.Test
import kotlin.test.assertEquals

class OnceTest {
    @Test fun concurrentCallersShareOneInstance() {
        val created = AtomicInteger()
        val once = Once<String, Any> { created.incrementAndGet(); Thread.sleep(50); Any() }
        val start = CountDownLatch(1)
        val pool = Executors.newFixedThreadPool(8)
        val results = (1..8).map { pool.submit<Any> { start.await(); once.get("ctx") } }
        start.countDown()
        val instances = results.map { it.get(5, TimeUnit.SECONDS) }.toSet()
        pool.shutdown()
        assertEquals(1, created.get())
        assertEquals(1, instances.size)
    }
}
