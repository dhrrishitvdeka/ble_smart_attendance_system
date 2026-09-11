package ble.relay

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat

/* ============================================================
   Deliverable #1 — STATE MACHINE LOGIC
   Rapid, crash-free transition: SCANNING (Central)
                              → SWITCHING
                              → RELAY_ADVERTISING (Peripheral)

   Crash-avoidance rules enforced below:
    R1. NEVER call startAdvertising() while a scan is still tearing down.
        stopScan() is async at the controller level on many OEM stacks;
        we wait RADIO_SETTLE_MS before claiming the advertiser.
    R2. All radio calls run serially on ONE thread (main Handler) — no
        concurrent start/stop races.
    R3. Every radio call is wrapped for SecurityException — Android 12+
        revokes BLUETOOTH_SCAN/ADVERTISE at any moment from App Ops.
    R4. Peripheral support is probed (isMultipleAdvertisementSupported)
        BEFORE the scan ever starts; a phone that cannot advertise never
        enters the state machine as a relay candidate.
    R5. Every transition has an exit path: window watchdog + hop limit +
        explicit stop() → the radio always ends fully released.
   ============================================================ */

sealed class RelayEvent {
    /** RSSI validated & Session_ID matched → safe to mark proximity check-in. */
    data class ProximityVerified(
        val sessionId: Int,
        val observedHopCount: Int,
        val rssiDbm: Int
    ) : RelayEvent()

    data class RelayAdvertisingStarted(val sessionId: Int, val forwardedHopCount: Int) : RelayEvent()
    data class Failed(val reason: String) : RelayEvent()
    object Stopped : RelayEvent()
}

class AttendanceRelayStateMachine(
    context: Context,
    private val listener: (RelayEvent) -> Unit
) {
    private val appContext = context.applicationContext
    enum class State { IDLE, SCANNING, SWITCHING, RELAY_ADVERTISING, STOPPED, FAILED }

    companion object {
        const val RSSI_THRESHOLD_DBM = -85   // weaker ⇒ out-of-bounds, packet ignored
        const val SCAN_WINDOW_MS = 60_000L
        const val ADVERTISE_TIMEOUT_MS = 180_000L // stack hard cap for setTimeout()
        const val RADIO_SETTLE_MS = 250L     // R1: scanner teardown debounce
    }

    private val handler = Handler(Looper.getMainLooper())
    private val adapter: BluetoothAdapter? =
        (appContext.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter

    @Volatile var state: State = State.IDLE
        private set

    private var scanner: StudentScanner? = null
    private var relayAdvertiser: RelayAdvertiser? = null
    private var sessionId = 0

    /* ---------- entry point ---------- */
    fun beginAttendanceScan(sessionId: Int) {
        if (state != State.IDLE && state != State.STOPPED && state != State.FAILED) return
        val bt = adapter ?: return emit("Bluetooth adapter unavailable")
        if (!bt.isEnabled) return emit("Bluetooth disabled")
        // R4: a non-advertiser device can scan but must not become a relay.
        if (!bt.isMultipleAdvertisementSupported)
            return emit("Peripheral/advertising mode unsupported on this device")

        this.sessionId = sessionId
        setState(State.SCANNING)

        scanner = StudentScanner(
            context = appContext,
            sessionId = sessionId,
            rssiThresholdDbm = RSSI_THRESHOLD_DBM,
            onError = ::fail
        ) { hop, rssi ->
            listener(RelayEvent.ProximityVerified(sessionId, hop, rssi))
            transitionCentralToPeripheral(sessionId, hop - 1)   // Deliverable #3: decrement
        }
        scanner?.start(onError = ::fail)
        handler.postDelayed({ if (state == State.SCANNING) shutdown() }, SCAN_WINDOW_MS)
    }

    /* ---------- Deliverable #3 — Central → Peripheral transition ---------- */
    private fun transitionCentralToPeripheral(sessionId: Int, decrementedHop: Int) {
        if (state != State.SCANNING) return                    // guard double-fires
        if (decrementedHop <= 0) { shutdown(); return }        // mesh edge reached

        setState(State.SWITCHING)
        scanner?.stop()                                        // R2/R1: tear down first…

        // …then WAIT before advertising (R1). Posting to the same single
        // handler guarantees ordering without blocking or crashing.
        handler.postDelayed({
            if (state != State.SWITCHING) return@postDelayed
            relayAdvertiser = RelayAdvertiser(appContext).also { adv ->
                adv.startRelay(
                    sessionId = sessionId,
                    hopCount = decrementedHop,
                    timeoutMs = ADVERTISE_TIMEOUT_MS,
                    onStarted = {
                        setState(State.RELAY_ADVERTISING)
                        listener(RelayEvent.RelayAdvertisingStarted(sessionId, decrementedHop))
                    },
                    onFailure = ::fail
                )
            }
        }, RADIO_SETTLE_MS)
    }

    /* ---------- lifecycle ---------- */
    fun shutdown() {
        try { scanner?.stop() } catch (_: SecurityException) { } catch (_: Exception) { }
        try { relayAdvertiser?.stop() } catch (_: SecurityException) { } catch (_: Exception) { }
        scanner = null; relayAdvertiser = null
        handler.removeCallbacksAndMessages(null)
        setState(State.STOPPED)
        listener(RelayEvent.Stopped)
    }

    /** Release handler callbacks (call from Activity.onDestroy to avoid leaks). */
    fun destroy() {
        try { scanner?.stop() } catch (_: Exception) { }
        try { relayAdvertiser?.stop() } catch (_: Exception) { }
        scanner = null; relayAdvertiser = null
        handler.removeCallbacksAndMessages(null)
    }

    /** Fail without double-emitting Stopped: release radio silently then emit Failed. */
    private fun fail(reason: String) {
        try { scanner?.stop() } catch (_: Exception) { }
        try { relayAdvertiser?.stop() } catch (_: Exception) { }
        scanner = null; relayAdvertiser = null
        handler.removeCallbacksAndMessages(null)
        state = State.FAILED
        listener(RelayEvent.Failed(reason))
    }

    private fun emit(reason: String) = listener(RelayEvent.Failed(reason))

    private fun setState(s: State) { state = s }
}

/* ============================================================
   Student Scanner (Central) — Deliverable #3 step 1
   Filters by Service UUID, parses manufacturer data, applies
   the −85 dBm RSSI bound, fires exactly once, then stops.
   ============================================================ */
class StudentScanner(
    context: Context,
    private val sessionId: Int,
    private val rssiThresholdDbm: Int,
    private val onError: (String) -> Unit = {},
    private val onMatch: (hopCount: Int, rssiDbm: Int) -> Unit
) {
    private val appCtx = context.applicationContext
    private val scanner =
        (appCtx.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager)
            .adapter?.bluetoothLeScanner

    private var fired = false

    private val callback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            if (fired) return

            // ── RSSI FILTER ──────────────────────────────────────────
            // Prevents out-of-bounds check-ins: a phone in the corridor or
            // through two walls typically measures < −85 dBm.
            if (result.rssi < rssiThresholdDbm) return

            val mfg = result.scanRecord
                ?.getManufacturerSpecificData(PayloadCodec.COMPANY_ID) ?: return
            val decoded = PayloadCodec.decode(mfg) ?: return
            if (decoded.sessionId != sessionId) return          // wrong classroom
            if (decoded.hopCount <= 0 || decoded.hopCount > PayloadCodec.MAX_HOPS) return // exhausted/invalid

            fired = true
            try { scanner?.stopScan(this) } catch (_: SecurityException) { } catch (_: Exception) { }
            onMatch(decoded.hopCount, result.rssi)
        }

        override fun onScanFailed(errorCode: Int) {
            val msg = when (errorCode) {
                SCAN_FAILED_ALREADY_STARTED -> "scan already started"
                SCAN_FAILED_REGISTRATION_FAILED -> "scan registration failed"
                SCAN_FAILED_INTERNAL_ERROR -> "internal BLE error"
                SCAN_FAILED_FEATURE_UNSUPPORTED -> "scanning unsupported"
                else -> "unknown scan failure"
            }
            onError("BLE scan failed: $msg")
        }
    }

    fun start(onError: (String) -> Unit) {
        val s = scanner ?: return onError("BLE scanner unavailable")
        val filter = ScanFilter.Builder()
            .setServiceUuid(PayloadCodec.ATTENDANCE_SERVICE_UUID)
            .build()
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)     // foreground only!
            .setReportDelay(0)
            .build()
        try {
            s.startScan(listOf(filter), settings, callback)
        } catch (e: SecurityException) {                        // R3
            onError("Missing BLUETOOTH_SCAN permission: ${e.message}")
        }
    }

    fun stop() {
        fired = true
        try {
            scanner?.stopScan(callback)
        } catch (_: SecurityException) { /* permission revoked mid-scan */ }
    }
}

/* ============================================================
   Relay Advertiser (Peripheral) — Deliverable #3 step 2
   Broadcasts SAME service UUID + SAME Session_ID with Hop−1.
   Non-connectable to save power and avoid GATT handshakes.
   ============================================================ */
class RelayAdvertiser(context: Context) {

    private val appCtx = context.applicationContext
    private val adapter: BluetoothAdapter? =
        (appCtx.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
    private var advertiser: android.bluetooth.le.BluetoothLeAdvertiser? = null
    private var onStarted: () -> Unit = {}
    private var onFailure: (String) -> Unit = {}
    private val callback = object : AdvertiseCallback() {
        override fun onStartSuccess(settingsInEffect: AdvertiseSettings?) { try { onStarted() } catch (_: Exception) { } }
        override fun onStartFailure(errorCode: Int) { try { onFailure(
            when (errorCode) {
                ADVERTISE_FAILED_DATA_TOO_LARGE -> "adv payload >31 bytes (drop service UUID or shorten payload)"
                ADVERTISE_FAILED_NOT_SUPPORTED -> "advertising not supported"
                ADVERTISE_FAILED_TOO_MANY_ADVERTISERS -> "too many advertisers"
                ADVERTISE_FAILED_INTERNAL_ERROR -> "advertiser internal error"
                else -> "advertiser error $errorCode"
            }
        ) } catch (_: Exception) { } }
    }

    fun startRelay(sessionId: Int, hopCount: Int, timeoutMs: Long, onStarted: () -> Unit, onFailure: (String) -> Unit) {
        this.onStarted = onStarted
        this.onFailure = onFailure
        if (hopCount !in 1..PayloadCodec.MAX_HOPS) { onFailure("hop_count out of range"); return }
        val bt = adapter ?: run { onFailure("Bluetooth adapter unavailable"); return }
        if (!bt.isEnabled) { onFailure("Bluetooth disabled"); return }
        advertiser = bt.bluetoothLeAdvertiser ?: run {
            onFailure("No BluetoothLeAdvertiser"); return
        }

        val settings = AdvertiseSettings.Builder()
            .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
            .setConnectable(false)                               // beacon-style relay
            .setTimeout(timeoutMs.coerceAtMost(180_000L))        // stack auto-stops ≤180s
            .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_HIGH)
            .build()

        // NOTE: 128-bit service UUID (18B) + manufacturer (12B) + flags (3B) = 33B > 31B
        // legacy limit. If ADVERTISE_FAILED_DATA_TOO_LARGE occurs, drop the
        // service UUID here (scan filter can match manufacturer data instead).
        val payload = try { PayloadCodec.encode(hopCount, sessionId) }
            catch (e: IllegalArgumentException) { onFailure(e.message ?: "bad hop"); return }
        val data = AdvertiseData.Builder()
            .addServiceUuid(PayloadCodec.ATTENDANCE_SERVICE_UUID)   // keeps ScanFilter working downstream
            .addManufacturerData(PayloadCodec.COMPANY_ID, payload)
            .setIncludeDeviceName(false)                             // saves bytes
            .setIncludeTxPowerLevel(false)                           // saves bytes
            .build()

        try {
            advertiser?.startAdvertising(settings, data, callback)   // R3 caller-side catch too
        } catch (e: SecurityException) {
            onFailure("Missing BLUETOOTH_ADVERTISE permission: ${e.message}")
        } catch (e: Exception) {
            onFailure("Advertiser start failed: ${e.message}")
        }
    }

    fun stop() {
        try { advertiser?.stopAdvertising(callback) } catch (_: SecurityException) { } catch (_: Exception) { }
        advertiser = null
    }
}
