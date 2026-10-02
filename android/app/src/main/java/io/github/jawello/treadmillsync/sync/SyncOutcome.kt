package io.github.jawello.treadmillsync.sync

import io.github.jawello.treadmillsync.bridge.BridgeException

sealed interface SyncOutcome {
    val key: String get() = this::class.simpleName!!
    val retry: Boolean get() = false

    data class Success(val written: Int) : SyncOutcome
    data object NotConfigured : SyncOutcome
    data object NotHome : SyncOutcome
    data object NetworkUnknown : SyncOutcome
    data object BridgeUnreachable : SyncOutcome { override val retry = true }
    data object CleartextBlocked : SyncOutcome
    data object WrongToken : SyncOutcome
    data class BridgeError(val code: Int?) : SyncOutcome { override val key = "BridgeError:${code ?: "url"}" }
    data object PermissionsMissing : SyncOutcome
    data object HealthConnectUnavailable : SyncOutcome { override val retry = true }
    data object RateLimited : SyncOutcome { override val retry = true }
    data object Unexpected : SyncOutcome
}

fun bridgeOutcome(e: BridgeException): SyncOutcome = when (e) {
    is BridgeException.Unreachable -> SyncOutcome.BridgeUnreachable
    is BridgeException.CleartextBlocked -> SyncOutcome.CleartextBlocked
    is BridgeException.Unauthorized, is BridgeException.BadToken -> SyncOutcome.WrongToken
    is BridgeException.BadResponse -> SyncOutcome.BridgeError(e.code)
    is BridgeException.BadUrl -> SyncOutcome.BridgeError(null)
}
