package io.github.jawello.treadmillsync.ui

import io.github.jawello.treadmillsync.R

fun outcomeTextRes(key: String?): Int = when {
    key == null -> 0
    key == "Success" -> R.string.outcome_success
    key == "NotConfigured" -> R.string.outcome_not_configured
    key == "NotHome" -> R.string.outcome_not_home
    key == "NetworkUnknown" -> R.string.outcome_network_unknown
    key == "BridgeUnreachable" -> R.string.outcome_bridge_unreachable
    key == "CleartextBlocked" -> R.string.outcome_cleartext_blocked
    key == "WrongToken" -> R.string.outcome_wrong_token
    key.startsWith("BridgeError") -> R.string.outcome_bridge_error
    key == "PermissionsMissing" -> R.string.outcome_permissions
    key == "HealthConnectUnavailable" -> R.string.outcome_hc_unavailable
    key == "RateLimited" -> R.string.outcome_rate_limited
    else -> R.string.outcome_unknown
}
