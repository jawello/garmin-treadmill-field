package io.github.jawello.treadmillsync.net

enum class GateResult { OPEN, NOT_HOME, UNKNOWN }

fun interface SsidSource {
    /** The current Wi-Fi SSID without quotes, or null when Android hides or has none. */
    suspend fun currentSsid(): String?
}

/** Lets the token leave the phone only on the home network, when one is configured. */
class NetworkGate(private val source: SsidSource) {
    suspend fun check(homeSsid: String): GateResult {
        val home = homeSsid.trim()
        if (home.isEmpty()) return GateResult.OPEN
        val current = source.currentSsid() ?: return GateResult.UNKNOWN
        return if (current == home) GateResult.OPEN else GateResult.NOT_HOME
    }
}

private const val UNKNOWN_SSID = "<unknown ssid>" // WifiManager.UNKNOWN_SSID

fun normalizeSsid(raw: String?): String? {
    if (raw == null || raw == UNKNOWN_SSID) return null
    return raw.removeSurrounding("\"").ifEmpty { null }
}
