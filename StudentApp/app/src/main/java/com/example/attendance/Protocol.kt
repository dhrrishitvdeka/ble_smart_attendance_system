package com.example.attendance

import android.os.ParcelUuid
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

/**
 * Shared protocol constants matching shared/ble_config.json,
 * TeacherApp (BleProtocol.cs), and webapp/core.js.
 */
object Protocol {
    val SERVICE_UUID: UUID = UUID.fromString("a5e8c0de-0001-4b7d-9c11-000000000001")
    val SESSION_CHAR_UUID: UUID = UUID.fromString("a5e8c0de-0002-4b7d-9c11-000000000002")
    val REQUEST_CHAR_UUID: UUID = UUID.fromString("a5e8c0de-0003-4b7d-9c11-000000000003")
    val CHALLENGE_CHAR_UUID: UUID = UUID.fromString("a5e8c0de-0004-4b7d-9c11-000000000004")
    val RESPONSE_CHAR_UUID: UUID = UUID.fromString("a5e8c0de-0005-4b7d-9c11-000000000005")
    val RESULT_CHAR_UUID: UUID = UUID.fromString("a5e8c0de-0006-4b7d-9c11-000000000006")
    val RELAY_CHAR_UUID: UUID = UUID.fromString("a5e8c0de-0007-4b7d-9c11-000000000007")

    val SERVICE_PARCEL_UUID: ParcelUuid = ParcelUuid(SERVICE_UUID)

    const val COMPANY_ID = 0xFFFF
    const val MAGIC: Byte = 0xB5.toByte()
    const val MAX_HOPS = 2
    const val RSSI_FLOOR_DBM = -90
    const val RSSI_THRESHOLD_DBM = -85
    const val SESSION_TTL_MS = 600000L
    const val CHALLENGE_TTL_MS = 30000L

    const val MFG_PAYLOAD_LEN = 8 // MAGIC + HOP + SESSION(4) + RESERVED(2)

    fun encodeMfgData(hopCount: Int, sessionIdInt: Int): ByteArray {
        require(hopCount in 0..MAX_HOPS) { "hop_count out of range" }
        return ByteBuffer.allocate(MFG_PAYLOAD_LEN)
            .order(ByteOrder.BIG_ENDIAN)
            .put(MAGIC)
            .put(hopCount.toByte())
            .putInt(sessionIdInt)
            .putShort(0)
            .array()
    }

    data class DecodedBeacon(val sessionIdInt: Int, val hopCount: Int)

    fun decodeMfgData(data: ByteArray?): DecodedBeacon? {
        if (data == null || data.size != MFG_PAYLOAD_LEN) return null
        val buf = ByteBuffer.wrap(data).order(ByteOrder.BIG_ENDIAN)
        if (buf.get() != MAGIC) return null
        val hop = buf.get().toInt() and 0xFF
        if (hop !in 1..MAX_HOPS) return null
        val session = buf.int
        return DecodedBeacon(sessionIdInt = session, hopCount = hop)
    }
}
