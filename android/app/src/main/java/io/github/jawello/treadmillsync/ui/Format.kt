package io.github.jawello.treadmillsync.ui

import java.util.Locale

/** Whole hours and minutes, rounded to the nearest minute. */
fun durationParts(seconds: Long): Pair<Int, Int> {
    val minutes = ((seconds + 30) / 60).toInt()
    return minutes / 60 to minutes % 60
}

fun groupedNumber(value: Long, locale: Locale = Locale.getDefault()): String = String.format(locale, "%,d", value)

fun kilometres(metres: Double, locale: Locale = Locale.getDefault()): String = String.format(locale, "%.2f", metres / 1000)

fun oneDecimal(value: Double, locale: Locale = Locale.getDefault()): String = String.format(locale, "%.1f", value)
