package io.github.jawello.treadmillsync.settings

const val DEFAULT_BRIDGE_URL = "http://192.168.31.250:8080"

data class Settings(
    val bridgeUrl: String = DEFAULT_BRIDGE_URL,
    val token: String = "",
    val homeSsid: String = "",
) {
    fun normalized() = Settings(bridgeUrl.trim().trimEnd('/'), token.trim(), homeSsid.trim())

    val configured: Boolean get() = bridgeUrl.isNotBlank() && token.isNotBlank()
}
