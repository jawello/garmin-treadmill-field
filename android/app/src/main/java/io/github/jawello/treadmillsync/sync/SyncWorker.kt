package io.github.jawello.treadmillsync.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ListenableWorker
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.github.jawello.treadmillsync.Graph
import java.util.concurrent.TimeUnit

fun workResult(outcome: SyncOutcome): ListenableWorker.Result = when {
    outcome is SyncOutcome.Success -> ListenableWorker.Result.success()
    outcome.retry -> ListenableWorker.Result.retry()
    else -> ListenableWorker.Result.failure() // the next period runs anyway
}

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = workResult(Graph.engine(applicationContext).sync())
}

object SyncScheduler {
    private const val NAME = "bridge-sync"

    fun schedule(context: Context) {
        val request = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.UNMETERED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 1, TimeUnit.MINUTES)
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.KEEP, request)
    }
}
