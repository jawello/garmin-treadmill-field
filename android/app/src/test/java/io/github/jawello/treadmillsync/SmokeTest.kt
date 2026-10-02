package io.github.jawello.treadmillsync

import java.io.File
import kotlin.test.Test
import kotlin.test.assertTrue

class SmokeTest {
    @Test
    fun contractFixtureIsReachable() {
        val file = File(System.getProperty("contractDir"), "steps-response.json")
        assertTrue(file.isFile, "missing ${file.absolutePath}")
    }
}
