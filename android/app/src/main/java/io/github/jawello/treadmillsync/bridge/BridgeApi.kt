package io.github.jawello.treadmillsync.bridge

import java.io.IOException

interface BridgeApi {
    suspend fun steps(since: Long, until: Long): List<Bucket>
    suspend fun ping()
}

sealed class BridgeException(message: String? = null, cause: Throwable? = null) : Exception(message, cause) {
    class Unreachable(cause: IOException) : BridgeException(cause.message, cause)
    class CleartextBlocked : BridgeException()
    class Unauthorized : BridgeException()
    class BadToken : BridgeException()
    class BadUrl : BridgeException()
    class BadResponse(val code: Int?) : BridgeException("HTTP $code")
}
