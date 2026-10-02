package io.github.jawello.treadmillsync.settings

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class SettingsTest {
    @Test fun normalizedTrimsFields() {
        val s = Settings(" http://10.0.0.2:8080/ \n", " tok \n", " Home ").normalized()
        assertEquals(Settings("http://10.0.0.2:8080", "tok", "Home"), s)
    }

    @Test fun configuredNeedsUrlAndToken() {
        assertFalse(Settings(token = "").configured)
        assertFalse(Settings(bridgeUrl = " ", token = "t").configured)
        assertTrue(Settings(token = "t").configured)
        assertEquals("http://192.168.31.250:8080", Settings().bridgeUrl)
    }
}
