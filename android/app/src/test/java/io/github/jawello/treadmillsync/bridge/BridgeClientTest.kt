package io.github.jawello.treadmillsync.bridge

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import java.net.UnknownServiceException
import java.util.concurrent.TimeUnit
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs

class BridgeClientTest {
    private val server = MockWebServer()

    @BeforeTest fun start() = server.start()
    @AfterTest fun stop() = server.shutdown()

    private fun client(token: String = "secret", http: OkHttpClient = BridgeClient.defaultHttp()) =
        BridgeClient(server.url("/").toString().trimEnd('/'), token, http)

    private val body = """{"buckets":[{"active_seconds":60.0,"distance_m":80.0,"end":1060,"start":1000,"steps":105,"version":1061250}]}"""

    @Test fun sendsBearerAndWindowAndParses() = runTest {
        server.enqueue(MockResponse().setBody(body))
        val buckets = client().steps(1000, 2000)
        assertEquals(listOf(Bucket(1000, 1060, 105, 80.0, 1061250)), buckets)
        val request = server.takeRequest()
        assertEquals("Bearer secret", request.getHeader("Authorization"))
        assertEquals("/api/v1/steps?since=1000&until=2000", request.path)
    }

    @Test fun unauthorized() = runTest {
        server.enqueue(MockResponse().setResponseCode(401))
        assertFailsWith<BridgeException.Unauthorized> { client().steps(0, 1) }
    }

    @Test fun badRequestKeepsCode() = runTest {
        server.enqueue(MockResponse().setResponseCode(400))
        val e = assertFailsWith<BridgeException.BadResponse> { client().steps(0, 1) }
        assertEquals(400, e.code)
    }

    @Test fun malformedJson() = runTest {
        server.enqueue(MockResponse().setBody("""{"buckets":[{"start":"x"}]}"""))
        assertFailsWith<BridgeException.BadResponse> { client().steps(0, 1) }
    }

    @Test fun timeoutIsUnreachable() = runTest {
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        val fast = OkHttpClient.Builder().readTimeout(200, TimeUnit.MILLISECONDS).build()
        assertFailsWith<BridgeException.Unreachable> { client(http = fast).steps(0, 1) }
    }

    @Test fun nonAsciiTokenIsReportedNotThrown() = runTest {
        assertFailsWith<BridgeException.BadToken> { client(token = "tök\n").steps(0, 1) }
    }

    @Test fun badUrlIsReported() = runTest {
        assertFailsWith<BridgeException.BadUrl> { BridgeClient("not a url", "t").steps(0, 1) }
    }

    @Test fun cleartextBlockedIsReported() = runTest {
        val blocking = OkHttpClient.Builder().addInterceptor { throw UnknownServiceException("CLEARTEXT communication to x not permitted") }.build()
        assertFailsWith<BridgeException.CleartextBlocked> { client(http = blocking).steps(0, 1) }
    }

    @Test fun pingHitsStatus() = runTest {
        server.enqueue(MockResponse().setBody("{}"))
        client().ping()
        assertEquals("/api/v1/status", server.takeRequest().path)
    }

    @Test fun defaultTimeoutIsTenSeconds() {
        assertEquals(10_000, BridgeClient.defaultHttp().callTimeoutMillis)
        assertIs<OkHttpClient>(BridgeClient.defaultHttp())
    }
}
