package com.example.attendance.ui

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.example.attendance.R
import com.example.attendance.crypto.CryptoUtils
import com.example.attendance.databinding.ActivityLoginBinding
import com.example.attendance.models.StudentProfile
import com.example.attendance.storage.AttendanceStorage

class LoginActivity : AppCompatActivity() {

    private lateinit var binding: ActivityLoginBinding
    private lateinit var storage: AttendanceStorage
    private var hardwareDeviceId: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)

        storage = AttendanceStorage(this)
        hardwareDeviceId = CryptoUtils.getHardwareDeviceId(this)
        binding.tvDeviceId.text = hardwareDeviceId

        // Auto-login if previously authenticated
        val existingProfile = storage.getLoggedInProfile()
        if (existingProfile != null) {
            navigateToMain()
            return
        }

        setupButtons()
    }

    private fun setupButtons() {
        binding.btnDemoS001.setOnClickListener {
            val demo = AttendanceStorage.DEMO_STUDENTS.firstOrNull { it.studentId == "S001" }
            if (demo != null) {
                binding.etStudentId.setText(demo.studentId)
                binding.etDeviceSecret.setText(demo.deviceSecret)
            }
        }

        binding.btnDemoS003.setOnClickListener {
            val demo = AttendanceStorage.DEMO_STUDENTS.firstOrNull { it.studentId == "S003" }
            if (demo != null) {
                binding.etStudentId.setText(demo.studentId)
                binding.etDeviceSecret.setText(demo.deviceSecret)
            }
        }

        binding.btnLogin.setOnClickListener {
            val studentId = binding.etStudentId.text?.toString()?.trim()?.uppercase() ?: ""
            val deviceSecret = binding.etDeviceSecret.text?.toString()?.trim() ?: ""

            if (studentId.isEmpty()) {
                binding.tilStudentId.error = "Please enter your Student ID"
                return@setOnClickListener
            }
            binding.tilStudentId.error = null

            if (deviceSecret.length < 16) {
                binding.tilSecret.error = "Device secret must be at least 16 characters"
                return@setOnClickListener
            }
            binding.tilSecret.error = null

            // Match demo profile or create dynamically
            val matched = AttendanceStorage.DEMO_STUDENTS.firstOrNull { it.studentId == studentId }
            val name = matched?.name ?: "Student $studentId"
            val classId = matched?.classId ?: "CSE-A"
            val regDeviceId = matched?.registeredDeviceId ?: hardwareDeviceId

            val profile = StudentProfile(
                studentId = studentId,
                name = name,
                deviceSecret = deviceSecret,
                registeredDeviceId = regDeviceId,
                classId = classId
            )

            storage.saveLoggedInProfile(profile)
            Toast.makeText(this, "Authenticated as ${profile.name}", Toast.LENGTH_SHORT).show()
            navigateToMain()
        }
    }

    private fun navigateToMain() {
        val intent = Intent(this, MainActivity::class.java)
        startActivity(intent)
        finish()
    }
}
