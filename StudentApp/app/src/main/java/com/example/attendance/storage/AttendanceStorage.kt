package com.example.attendance.storage

import android.content.Context
import android.content.SharedPreferences
import com.example.attendance.models.AttendanceRecord
import com.example.attendance.models.StudentProfile
import org.json.JSONArray
import org.json.JSONObject

class AttendanceStorage(context: Context) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences("ble_attendance_prefs", Context.MODE_PRIVATE)

    companion object {
        // Enrolled demo students matching TeacherApp & webapp/core.js mock data
        val DEMO_STUDENTS = listOf(
            StudentProfile(
                studentId = "S001",
                name = "Aarav Kumar",
                deviceSecret = "sec_aarav_001_secret_key_fixed_99887766554433221100aabbccddeeff",
                registeredDeviceId = "DEV-001",
                classId = "CSE-A"
            ),
            StudentProfile(
                studentId = "S002",
                name = "Diya Patel",
                deviceSecret = "sec_diya_002_secret_key_fixed_11223344556677889900aabbccddeeff",
                registeredDeviceId = "DEV-002",
                classId = "CSE-A"
            ),
            StudentProfile(
                studentId = "S003",
                name = "Rohan Verma",
                deviceSecret = "sec_rohan_003_secret_key_fixed_55667788990011223344aabbccddeeff",
                registeredDeviceId = "DEV-003",
                classId = "CSE-A"
            )
        )
    }

    fun saveLoggedInProfile(profile: StudentProfile) {
        prefs.edit()
            .putString("student_id", profile.studentId)
            .putString("student_name", profile.name)
            .putString("device_secret", profile.deviceSecret)
            .putString("registered_device_id", profile.registeredDeviceId)
            .putString("class_id", profile.classId)
            .apply()
    }

    fun getLoggedInProfile(): StudentProfile? {
        val id = prefs.getString("student_id", null) ?: return null
        val name = prefs.getString("student_name", "") ?: ""
        val secret = prefs.getString("device_secret", "") ?: ""
        val deviceId = prefs.getString("registered_device_id", "") ?: ""
        val classId = prefs.getString("class_id", "") ?: ""
        return StudentProfile(id, name, secret, deviceId, classId)
    }

    fun clearProfile() {
        prefs.edit()
            .remove("student_id")
            .remove("student_name")
            .remove("device_secret")
            .remove("registered_device_id")
            .remove("class_id")
            .apply()
    }

    fun saveRecord(record: AttendanceRecord) {
        val records = getRecords().toMutableList()
        records.removeAll { it.sessionId == record.sessionId }
        records.add(0, record)

        val jsonArray = JSONArray()
        for (r in records) {
            val obj = JSONObject()
            obj.put("id", r.id)
            obj.put("sessionId", r.sessionId)
            obj.put("studentId", r.studentId)
            obj.put("status", r.status)
            obj.put("routeType", r.routeType)
            obj.put("rssi", r.rssi)
            obj.put("hopCount", r.hopCount)
            obj.put("viaStudent", r.viaStudent ?: "")
            obj.put("timestamp", r.timestamp)
            jsonArray.put(obj)
        }

        prefs.edit().putString("history_records", jsonArray.toString()).apply()
    }

    fun getRecords(): List<AttendanceRecord> {
        val raw = prefs.getString("history_records", null) ?: return emptyList()
        val list = mutableListOf<AttendanceRecord>()
        try {
            val arr = JSONArray(raw)
            for (i in 0 until arr.length()) {
                val obj = arr.getJSONObject(i)
                val via = obj.optString("viaStudent", "")
                list.add(
                    AttendanceRecord(
                        id = obj.getString("id"),
                        sessionId = obj.getString("sessionId"),
                        studentId = obj.getString("studentId"),
                        status = obj.getString("status"),
                        routeType = obj.getString("routeType"),
                        rssi = obj.getInt("rssi"),
                        hopCount = obj.getInt("hopCount"),
                        viaStudent = if (via.isEmpty()) null else via,
                        timestamp = obj.getLong("timestamp")
                    )
                )
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        return list
    }
}
