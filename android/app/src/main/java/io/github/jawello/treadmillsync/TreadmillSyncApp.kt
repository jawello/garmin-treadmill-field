package io.github.jawello.treadmillsync

import android.app.Application
import io.github.jawello.treadmillsync.sync.SyncScheduler

class TreadmillSyncApp : Application() {
    override fun onCreate() {
        super.onCreate()
        SyncScheduler.schedule(this)
    }
}
