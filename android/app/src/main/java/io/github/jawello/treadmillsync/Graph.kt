package io.github.jawello.treadmillsync

import android.content.Context
import androidx.datastore.preferences.preferencesDataStore
import androidx.health.connect.client.HealthConnectClient
import java.io.File
import io.github.jawello.treadmillsync.bridge.BridgeApi
import io.github.jawello.treadmillsync.bridge.BridgeClient
import io.github.jawello.treadmillsync.health.HealthConnectStore
import io.github.jawello.treadmillsync.health.HealthStore
import io.github.jawello.treadmillsync.health.UnavailableHealthStore
import io.github.jawello.treadmillsync.history.FileHistoryStore
import io.github.jawello.treadmillsync.history.HistoryStore
import io.github.jawello.treadmillsync.net.AndroidSsidSource
import io.github.jawello.treadmillsync.net.NetworkGate
import io.github.jawello.treadmillsync.settings.Settings
import io.github.jawello.treadmillsync.settings.SettingsStore
import io.github.jawello.treadmillsync.sync.DataStoreSyncState
import io.github.jawello.treadmillsync.sync.SyncEngine
import io.github.jawello.treadmillsync.sync.SyncStateStore
import io.github.jawello.treadmillsync.util.Once

private val Context.syncStateStore by preferencesDataStore("sync_state")

/** Manual wiring of the app's collaborators. */
object Graph {
    // EncryptedSharedPreferences must not be created twice at once (worker and screen on first launch).
    private val settingsStore = Once<Context, SettingsStore> { SettingsStore(it.applicationContext) }

    fun settings(context: Context): SettingsStore = settingsStore.get(context)

    fun state(context: Context): SyncStateStore = DataStoreSyncState(context.applicationContext.syncStateStore)

    fun history(context: Context): HistoryStore =
        FileHistoryStore(File(context.applicationContext.filesDir, "history.json"))

    fun bridge(settings: Settings): BridgeApi = BridgeClient(settings.bridgeUrl, settings.token)

    fun health(context: Context): HealthStore =
        if (HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE) {
            HealthConnectStore(HealthConnectClient.getOrCreate(context.applicationContext))
        } else {
            UnavailableHealthStore()
        }

    fun engine(context: Context): SyncEngine {
        val app = context.applicationContext
        return SyncEngine(
            settings = { settings(app).load() }, // inside the pass, so a keystore failure becomes an outcome
            gate = NetworkGate(AndroidSsidSource(app)),
            bridge = ::bridge,
            health = health(app),
            state = state(app),
            history = history(app),
        )
    }
}
