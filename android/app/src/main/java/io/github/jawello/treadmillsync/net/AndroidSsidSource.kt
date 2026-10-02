package io.github.jawello.treadmillsync.net

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiInfo
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeoutOrNull

/** Reads the current Wi-Fi SSID; needs fine (and, in background, background) location. */
class AndroidSsidSource(private val context: Context) : SsidSource {
    override suspend fun currentSsid(): String? {
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return null
        val result = CompletableDeferred<String?>()
        val callback = object : ConnectivityManager.NetworkCallback(FLAG_INCLUDE_LOCATION_INFO) {
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                result.complete(normalizeSsid((caps.transportInfo as? WifiInfo)?.ssid))
            }
        }
        val request = NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build()
        cm.registerNetworkCallback(request, callback)
        return try {
            withTimeoutOrNull(2_000) { result.await() }
        } finally {
            cm.unregisterNetworkCallback(callback)
        }
    }
}
