package com.example.attendance.models

data class StudentProfile(
    val studentId: String,
    val name: String,
    val deviceSecret: String,
    val registeredDeviceId: String,
    val classId: String
)

data class AttendanceSession(
    val sessionId: String,
    val nonce: String,
    val classId: String,
    val rssi: Int,
    val hopCount: Int = 0,
    val viaStudent: String? = null
)

enum class AttendanceState {
    NOT_VERIFIED,
    SCANNING,
    CONNECTING,
    CHALLENGING,
    ELIGIBLE,
    PRESENT,
    FAILED
}

data class AttendanceRecord(
    val id: String,
    val sessionId: String,
    val studentId: String,
    val status: String,
    val routeType: String,
    val rssi: Int,
    val hopCount: Int,
    val viaStudent: String?,
    val timestamp: Long
)
