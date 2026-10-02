package io.github.jawello.treadmillsync.settings

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Bridge URL, token and home SSID, encrypted at rest. */
class SettingsStore(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context,
        "settings",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun load() = Settings(
        bridgeUrl = prefs.getString(URL, null) ?: DEFAULT_BRIDGE_URL,
        token = prefs.getString(TOKEN, null).orEmpty(),
        homeSsid = prefs.getString(SSID, null).orEmpty(),
    )

    fun save(settings: Settings) {
        val s = settings.normalized()
        prefs.edit().putString(URL, s.bridgeUrl).putString(TOKEN, s.token).putString(SSID, s.homeSsid).apply()
    }

    private companion object {
        const val URL = "bridge_url"
        const val TOKEN = "token"
        const val SSID = "home_ssid"
    }
}
