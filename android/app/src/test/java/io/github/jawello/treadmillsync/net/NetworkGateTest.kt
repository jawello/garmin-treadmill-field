package io.github.jawello.treadmillsync.net

import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class NetworkGateTest {
    private var asked = 0
    private fun gate(ssid: String?) = NetworkGate { asked++; ssid }

    @Test fun emptyHomeSsidIsOpenWithoutAsking() = runTest {
        assertEquals(GateResult.OPEN, gate(null).check("  "))
        assertEquals(0, asked)
    }

    @Test fun matchingSsidIsOpen() = runTest { assertEquals(GateResult.OPEN, gate("jawello-wifi").check("jawello-wifi")) }
    @Test fun otherSsidIsNotHome() = runTest { assertEquals(GateResult.NOT_HOME, gate("cafe").check("jawello-wifi")) }
    @Test fun unknownSsidIsUnknown() = runTest { assertEquals(GateResult.UNKNOWN, gate(null).check("jawello-wifi")) }

    @Test fun normalizeSsidStripsQuotesAndUnknown() {
        assertEquals("jawello-wifi", normalizeSsid("\"jawello-wifi\""))
        assertNull(normalizeSsid("<unknown ssid>"))
        assertNull(normalizeSsid("\"\""))
        assertNull(normalizeSsid(null))
    }
}
