package io.github.jawello.treadmillsync.bridge

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** One final minute of treadmill walking, as served by the bridge's GET /api/v1/steps. */
@Serializable
data class Bucket(
    val start: Long,
    val end: Long,
    val steps: Long,
    @SerialName("distance_m") val distanceM: Double,
    val version: Long,
)

@Serializable
private data class StepsResponse(val buckets: List<Bucket>)

private val json = Json { ignoreUnknownKeys = true }

fun parseStepsResponse(body: String): List<Bucket> =
    try {
        json.decodeFromString<StepsResponse>(body).buckets
    } catch (e: IllegalArgumentException) { // SerializationException is one
        throw BridgeException.BadResponse(200)
    }
