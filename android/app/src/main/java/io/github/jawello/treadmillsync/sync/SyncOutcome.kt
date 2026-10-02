package io.github.jawello.treadmillsync.sync

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
}
