package io.github.jawello.treadmillsync.util

/** Creates a value on first use and hands every later caller, on any thread, the same one. */
class Once<C, T : Any>(private val create: (C) -> T) {
    @Volatile private var value: T? = null

    fun get(context: C): T = value ?: synchronized(this) { value ?: create(context).also { value = it } }
}
