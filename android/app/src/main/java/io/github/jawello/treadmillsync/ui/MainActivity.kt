package io.github.jawello.treadmillsync.ui

import android.Manifest
import android.content.Intent
import android.os.Bundle
import android.text.format.DateUtils
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.lifecycle.lifecycleScope
import io.github.jawello.treadmillsync.Graph
import io.github.jawello.treadmillsync.R
import io.github.jawello.treadmillsync.bridge.BridgeException
import io.github.jawello.treadmillsync.health.HealthConnectStore
import io.github.jawello.treadmillsync.net.AndroidSsidSource
import io.github.jawello.treadmillsync.settings.Settings
import io.github.jawello.treadmillsync.sync.SyncScheduler
import io.github.jawello.treadmillsync.sync.SyncSnapshot
import io.github.jawello.treadmillsync.sync.bridgeOutcome
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val snapshot = mutableStateOf(SyncSnapshot())
    private val message = mutableStateOf("")

    private val healthPermissions =
        registerForActivityResult(PermissionController.createRequestPermissionResultContract()) { refresh() }
    private val backgroundLocation =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
    private var onFineLocation: () -> Unit = {}
    private val fineLocation =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
            if (granted[Manifest.permission.ACCESS_FINE_LOCATION] == true) onFineLocation()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        SyncScheduler.schedule(this)
        val initial = try { Graph.settings(this).load() } catch (e: Exception) { Settings() } // unreadable prefs: start blank
        setContent { MaterialTheme { Screen(initial, ::save) } }
        refresh()
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun save(settings: Settings) {
        try {
            Graph.settings(this).save(settings)
        } catch (e: Exception) {
            message.value = getString(R.string.outcome_unknown)
        }
    }

    private fun refresh() {
        lifecycleScope.launch {
            try {
                snapshot.value = Graph.state(this@MainActivity).read()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // keep the last snapshot on screen
            }
        }
    }

    private fun syncNow() {
        lifecycleScope.launch {
            Graph.engine(this@MainActivity).sync()
            refresh()
        }
    }

    private fun testConnection(settings: Settings) {
        lifecycleScope.launch {
            message.value = try {
                Graph.bridge(settings.normalized()).ping()
                getString(R.string.connection_ok)
            } catch (e: BridgeException) {
                getString(outcomeTextRes(bridgeOutcome(e).key))
            }
        }
    }

    private fun withCurrentSsid(use: (String) -> Unit) {
        onFineLocation = {
            lifecycleScope.launch {
                AndroidSsidSource(this@MainActivity).currentSsid()?.let(use)
                backgroundLocation.launch(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
            }
        }
        fineLocation.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
    }

    private fun time(epochSecond: Long?): String =
        epochSecond?.let { DateUtils.formatDateTime(this, it * 1000, DateUtils.FORMAT_SHOW_TIME or DateUtils.FORMAT_SHOW_DATE) } ?: "—"

    @Composable
    private fun Screen(initial: Settings, save: (Settings) -> Unit) {
        var url by remember { mutableStateOf(initial.bridgeUrl) }
        var token by remember { mutableStateOf(initial.token) }
        var ssid by remember { mutableStateOf(initial.homeSsid) }
        val scope = rememberCoroutineScope()
        val snap by snapshot
        val current = { Settings(url, token, ssid) }

        Column(
            Modifier.padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(stringResource(R.string.status_title), style = MaterialTheme.typography.titleLarge)
            Text(
                if (snap.lastSuccessAt == null) stringResource(R.string.status_never)
                else stringResource(R.string.status_last_success, time(snap.lastSuccessAt), snap.lastWritten)
            )
            if (snap.lastOutcome != null && snap.lastOutcome != "Success") {
                Text(stringResource(R.string.status_last_problem, time(snap.lastAttemptAt), stringResource(outcomeTextRes(snap.lastOutcome))))
            }
            Button(onClick = { save(current()); syncNow() }, Modifier.fillMaxWidth()) { Text(stringResource(R.string.sync_now)) }

            OutlinedTextField(url, { url = it }, label = { Text(stringResource(R.string.bridge_url)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(token, { token = it }, label = { Text(stringResource(R.string.token)) }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(ssid, { ssid = it }, label = { Text(stringResource(R.string.home_ssid)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Text(stringResource(R.string.home_ssid_hint), style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = { withCurrentSsid { ssid = it } }) { Text(stringResource(R.string.use_current_network)) }
            Button(onClick = {
                save(current())
                if (current().normalized().homeSsid.isNotEmpty()) withCurrentSsid { }
            }) { Text(stringResource(R.string.save)) }
            OutlinedButton(onClick = { scope.launch { testConnection(current()) } }) { Text(stringResource(R.string.test_connection)) }
            if (message.value.isNotEmpty()) Text(message.value)

            Button(onClick = { healthPermissions.launch(HealthConnectStore.PERMISSIONS) }) { Text(stringResource(R.string.hc_permissions)) }
            Text(stringResource(R.string.hc_priority_hint), style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = { startActivity(Intent(HealthConnectClient.ACTION_HEALTH_CONNECT_SETTINGS)) }) {
                Text(stringResource(R.string.open_hc_settings))
            }
        }
    }
}
