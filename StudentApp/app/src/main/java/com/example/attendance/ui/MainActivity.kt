package com.example.attendance.ui

import android.Manifest
import android.bluetooth.BluetoothDevice
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.attendance.Protocol
import com.example.attendance.R
import com.example.attendance.ble.BleManager
import com.example.attendance.ble.RelayManager
import com.example.attendance.databinding.ActivityMainBinding
import com.example.attendance.models.AttendanceRecord
import com.example.attendance.models.AttendanceSession
import com.example.attendance.models.AttendanceState
import com.example.attendance.models.StudentProfile
import com.example.attendance.storage.AttendanceStorage
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : AppCompatActivity(), BleManager.BleListener, RelayManager.RelayListener {

    private lateinit var binding: ActivityMainBinding
    private lateinit var storage: AttendanceStorage
    private lateinit var bleManager: BleManager
    private lateinit var relayManager: RelayManager
    private lateinit var historyAdapter: HistoryAdapter

    private var currentProfile: StudentProfile? = null
    private var activeSession: AttendanceSession? = null
    private var targetPeripheral: BluetoothDevice? = null

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val allGranted = permissions.entries.all { it.value }
        if (allGranted) {
            appendLog("[PERMS] All Bluetooth and Location permissions granted.")
        } else {
            appendLog("[PERMS] Some permissions denied. Scanning may be restricted.")
            Toast.makeText(this, "Bluetooth permissions required for proximity scan", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        storage = AttendanceStorage(this)
        currentProfile = storage.getLoggedInProfile()

        if (currentProfile == null) {
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        bleManager = BleManager(this, this)
        relayManager = RelayManager(this, this)

        setupUI()
        setupHistory()
        checkAndRequestPermissions()
    }

    private fun setupUI() {
        val p = currentProfile!!
        binding.tvStudentName.text = "${p.name} (${p.studentId})"
        binding.tvClassEnrolled.text = "Enrolled: ${p.classId} — Data Structures"
        binding.tvDeviceBinding.text = "Device ID: ${p.registeredDeviceId} | Vault: Hardware-Bound PBKDF2"

        binding.btnLogout.setOnClickListener {
            storage.clearProfile()
            bleManager.disconnect()
            relayManager.stopRelayBeaconAdvertising()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
        }

        binding.btnScanBeacon.setOnClickListener {
            bleManager.startScanning()
        }

        binding.btnSubmitDirect.setOnClickListener {
            val student = currentProfile ?: return@setOnClickListener
            if (activeSession == null) {
                Toast.makeText(this, "Please scan classroom beacon first", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            bleManager.submitDirectGattAttendance(student, targetPeripheral)
        }

        binding.btnSubmitRelay.setOnClickListener {
            val student = currentProfile ?: return@setOnClickListener
            val session = activeSession ?: AttendanceSession(
                sessionId = "1957F836",
                nonce = "SIM_NONCE",
                classId = student.classId,
                rssi = -74,
                hopCount = 2,
                viaStudent = "S002"
            )
            relayManager.submitMeshRelayAttendance(student, session)
        }
    }

    private fun setupHistory() {
        historyAdapter = HistoryAdapter(storage.getRecords())
        binding.rvAttendanceHistory.layoutManager = LinearLayoutManager(this)
        binding.rvAttendanceHistory.adapter = historyAdapter
        updateHistoryVisibility()
    }

    private fun updateHistoryVisibility() {
        val records = storage.getRecords()
        if (records.isEmpty()) {
            binding.tvEmptyHistory.visibility = View.VISIBLE
            binding.rvAttendanceHistory.visibility = View.GONE
        } else {
            binding.tvEmptyHistory.visibility = View.GONE
            binding.rvAttendanceHistory.visibility = View.VISIBLE
            historyAdapter.updateRecords(records)
        }
    }

    private fun checkAndRequestPermissions() {
        val needed = mutableListOf<String>()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED) {
                needed.add(Manifest.permission.BLUETOOTH_SCAN)
            }
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
                needed.add(Manifest.permission.BLUETOOTH_CONNECT)
            }
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_ADVERTISE) != PackageManager.PERMISSION_GRANTED) {
                needed.add(Manifest.permission.BLUETOOTH_ADVERTISE)
            }
        } else {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH) != PackageManager.PERMISSION_GRANTED) {
                needed.add(Manifest.permission.BLUETOOTH)
            }
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_ADMIN) != PackageManager.PERMISSION_GRANTED) {
                needed.add(Manifest.permission.BLUETOOTH_ADMIN)
            }
        }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.ACCESS_FINE_LOCATION)
        }

        if (needed.isNotEmpty()) {
            permissionLauncher.launch(needed.toTypedArray())
        }
    }

    private fun appendLog(line: String) {
        val time = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
        val current = binding.tvProtocolLog.text.toString()
        val newText = "$current\n[$time] $line"
        binding.tvProtocolLog.text = newText
    }

    // --- BleManager.BleListener callbacks ---

    override fun onBeaconDiscovered(session: AttendanceSession, device: BluetoothDevice?) {
        activeSession = session
        targetPeripheral = device

        binding.tvSessionId.text = "Session ID: ${session.sessionId} (${session.classId})"
        binding.tvSignalRssi.text = "Signal Strength: ${session.rssi} dBm (Threshold: > ${Protocol.RSSI_THRESHOLD_DBM} dBm)"

        val routeText = if (session.hopCount == 0) "Direct BLE GATT (Hop 0)" else "Relay Beacon (Hop ${session.hopCount})"
        binding.tvRouteInfo.text = "Route: $routeText"

        // Map RSSI (-100 to -40) to progress (0 to 100)
        val progress = ((session.rssi + 100).coerceIn(0, 60) * 100) / 60
        binding.progressRssi.progress = progress

        appendLog("[BEACON] Locked onto Session ${session.sessionId} (RSSI: ${session.rssi} dBm)")
    }

    override fun onStatusChanged(state: AttendanceState, description: String) {
        binding.tvStatusBadge.text = state.name
        binding.tvStatusDesc.text = description

        when (state) {
            AttendanceState.NOT_VERIFIED -> binding.tvStatusBadge.setTextColor(Color.parseColor("#D97706"))
            AttendanceState.SCANNING, AttendanceState.CONNECTING, AttendanceState.CHALLENGING ->
                binding.tvStatusBadge.setTextColor(Color.parseColor("#2563EB"))
            AttendanceState.ELIGIBLE -> binding.tvStatusBadge.setTextColor(Color.parseColor("#059669"))
            AttendanceState.PRESENT -> binding.tvStatusBadge.setTextColor(Color.parseColor("#16A34A"))
            AttendanceState.FAILED -> binding.tvStatusBadge.setTextColor(Color.parseColor("#DC2626"))
        }
    }

    override fun onLog(message: String) {
        appendLog(message)
    }

    override fun onVerificationSuccess(record: AttendanceRecord) {
        storage.saveRecord(record)
        updateHistoryVisibility()

        // As an eligible node, activate mesh relay advertising to help peer classmates (spec §13)
        relayManager.startRelayBeaconAdvertising(
            sessionIdInt = record.sessionId.hashCode(),
            remainingHops = 1
        )
    }

    override fun onVerificationFailed(reason: String) {
        onStatusChanged(AttendanceState.FAILED, reason)
        appendLog("[ERROR] Verification failed: $reason")
        Toast.makeText(this, "Verification failed: $reason", Toast.LENGTH_LONG).show()
    }

    // --- RelayManager.RelayListener callbacks ---

    override fun onRelayLog(message: String) {
        appendLog(message)
    }

    override fun onRelayStatusChanged(state: AttendanceState, description: String) {
        onStatusChanged(state, description)
    }

    override fun onRelaySuccess(record: AttendanceRecord) {
        storage.saveRecord(record)
        updateHistoryVisibility()
    }

    override fun onRelayFailed(reason: String) {
        onStatusChanged(AttendanceState.FAILED, reason)
        appendLog("[RELAY-ERROR] $reason")
    }

    override fun onDestroy() {
        super.onDestroy()
        bleManager.disconnect()
        relayManager.stopRelayBeaconAdvertising()
    }
}
