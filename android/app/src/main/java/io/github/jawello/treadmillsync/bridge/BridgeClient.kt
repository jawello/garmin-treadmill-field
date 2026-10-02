package io.github.jawello.treadmillsync.bridge

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException
import java.net.UnknownServiceException
import java.util.concurrent.TimeUnit

class BridgeClient(
    private val baseUrl: String,
    private val token: String,
    private val http: OkHttpClient = defaultHttp(),
) : BridgeApi {

    override suspend fun steps(since: Long, until: Long): List<Bucket> {
        val url = endpoint("api/v1/steps").newBuilder()
            .addQueryParameter("since", since.toString())
            .addQueryParameter("until", until.toString())
            .build()
        return parseStepsResponse(get(url))
    }

    override suspend fun ping() {
        get(endpoint("api/v1/status"))
    }

    private fun endpoint(path: String): HttpUrl =
        "${baseUrl.trim().trimEnd('/')}/$path".toHttpUrlOrNull() ?: throw BridgeException.BadUrl()

    private suspend fun get(url: HttpUrl): String = withContext(Dispatchers.IO) {
        val request = try {
            Request.Builder().url(url).header("Authorization", "Bearer $token").build()
        } catch (e: IllegalArgumentException) { // OkHttp rejects non-ASCII or control characters
            throw BridgeException.BadToken()
        }
        try {
            http.newCall(request).execute().use { response ->
                when (response.code) {
                    200 -> response.body?.string() ?: throw BridgeException.BadResponse(200)
                    401 -> throw BridgeException.Unauthorized()
                    else -> throw BridgeException.BadResponse(response.code)
                }
            }
        } catch (e: UnknownServiceException) { // network security config forbids cleartext to this host
            throw BridgeException.CleartextBlocked()
        } catch (e: IOException) {
            throw BridgeException.Unreachable(e)
        }
    }

    companion object {
        fun defaultHttp(): OkHttpClient = OkHttpClient.Builder()
            .callTimeout(10, TimeUnit.SECONDS)
            .build()
    }
}
