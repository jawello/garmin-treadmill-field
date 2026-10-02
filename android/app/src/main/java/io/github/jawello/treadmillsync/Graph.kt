package io.github.jawello.treadmillsync

import android.content.Context
import androidx.datastore.preferences.preferencesDataStore
import androidx.health.connect.client.HealthConnectClient
import io.github.jawello.treadmillsync.bridge.BridgeApi
import io.github.jawello.treadmillsync.bridge.BridgeClient
import io.github.jawello.treadmillsync.health.HealthConnectStore
import io.github.jawello.treadmillsync.health.HealthStore
import io.github.jawello.treadmillsync.health.UnavailableHealthStore
import io.github.jawello.treadmillsync.net.AndroidSsidSource
import io.github.jawello.treadmillsync.net.NetworkGate
import io.github.jawello.treadmillsync.settings.Settings
import io.github.jawello.treadmillsync.settings.SettingsStore
import io.github.jawello.treadmillsync.sync.DataStoreSyncState
import io.github.jawello.treadmillsync.sync.SyncEngine
import io.github.jawello.treadmillsync.sync.SyncStateStore

private val Context.syncStateStore by preferencesDataStore("sync_state")

/** Manual wiring of the app's collaborators. */
object Graph {
    fun settings(context: Context) = SettingsStore(context.applicationContext)

    fun state(context: Context): SyncStateStore = DataStoreSyncState(context.applicationContext.syncStateStore)

    fun bridge(settings: Settings): BridgeApi = BridgeClient(settings.bridgeUrl, settings.token)

    fun health(context: Context): HealthStore =
        if (HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE) {
            HealthConnectStore(HealthConnectClient.getOrCreate(context.applicationContext))
        } else {
            UnavailableHealthStore()
        }

    fun engine(context: Context): SyncEngine {
        val app = context.applicationContext
        val settings = settings(app)
        return SyncEngine(
            settings = { settings.load() },
            gate = NetworkGate(AndroidSsidSource(app)),
            bridge = ::bridge,
            health = health(app),
            state = state(app),
        )
    }
}
