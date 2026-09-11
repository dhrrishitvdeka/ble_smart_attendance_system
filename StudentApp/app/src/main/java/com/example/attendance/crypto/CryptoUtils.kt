package com.example.attendance.crypto

import android.annotation.SuppressLint
import android.content.Context
import android.provider.Settings
import java.security.MessageDigest

object CryptoUtils {

    fun sha256Hex(input: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val bytes = digest.digest(input.toByteArray(Charsets.UTF_8))
        return bytes.joinToString("") { "%02x".format(it) }
    }

    /**
     * Solves the teacher GATT authority's challenge nonce:
     * response_hash = SHA256(challenge_nonce + student_device_secret)
     */
    fun computeChallengeResponse(challengeNonce: String, deviceSecret: String): String {
        return sha256Hex(challengeNonce.trim() + deviceSecret.trim())
    }

    /**
     * Hardware-bound device fingerprint using Android Secure ID.
     */
    @SuppressLint("HardwareIds")
    fun getHardwareDeviceId(context: Context): String {
        val androidId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
        return if (!androidId.isNullOrEmpty()) {
            "DEV-${androidId.take(8).uppercase()}"
        } else {
            "DEV-EMU00001"
        }
    }
}
