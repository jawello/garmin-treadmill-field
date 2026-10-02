package io.github.jawello.treadmillsync.ui

import java.util.Locale
import kotlin.test.Test
import kotlin.test.assertEquals

class FormatTest {
    @Test fun durationRoundsToMinutes() {
        assertEquals(0 to 35, durationParts(2_100))
        assertEquals(2 to 4, durationParts(7_440))
        assertEquals(0 to 1, durationParts(30))
        assertEquals(1 to 0, durationParts(3_599))
    }

    @Test fun numbersFollowTheLocale() {
        assertEquals("12,402", groupedNumber(12_402, Locale.US))
        assertEquals("8.97", kilometres(8_970.0, Locale.US))
        assertEquals("4.4", oneDecimal(4.43, Locale.US))
    }
}
