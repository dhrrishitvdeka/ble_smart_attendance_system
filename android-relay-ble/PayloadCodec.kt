package ble.relay

import android.os.ParcelUuid
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

/**
 * PayloadCodec — packs Session_ID + Hop_Count into a standard 31-byte BLE
 * legacy advertisement payload (Deliverable #2).
 *
 * ─────────────────────────────────────────────────────────────────────────
 * 31-BYTE ADVERTISING CHANNEL PDU BUDGET (BLE 4.x legacy adv)
 * ─────────────────────────────────────────────────────────────────────────
 * Each AD structure = [Length:1B][Type:1B][Data:Length-1B]
 *
 *   Offset  Size  Structure
 *   ──────  ────  ────────────────────────────────────────────────────────
 *   0       3     Flags            [02][01][06]
 *                                  Len=02, Type=01(Flags),
 *                                  Data=06 (LE General Discoverable,
 *                                           BR/EDR Not Supported)
 *   3      11     ManufacturerData [0A][FF][FF][FF][B5][HOP][S3][S2][S1][S0][00][00]
 *                                  Len=0A, Type=FF(Manufacturer Specific),
 *                                  CompanyID = FFFF (LSB first on air)
 *                                  MAGIC     = B5 (protocol tag)
 *                                  HOP       = Hop_Count (1 byte, init 3)
 *                                  SESSION   = Session_ID (4 bytes BE)
 *                                  RESERVED  = 00 00 (future flags / TTL)
 *   ──────  ────
 *   Total  14 bytes of the 31-byte budget → 17 bytes free for a local name
 *   or TX-power structure later without exceeding the legacy limit.
 *
 * Why manufacturer data instead of Service Data?
 *   Service Data with our 128-bit UUID would consume 18 bytes
 *   (16 UUID + 2 header), and Android's ScanFilter matches Service Data
 *   poorly across OEM stacks. A ScanFilter on the *Service UUID* AD entry
 *   (advertised separately by the teacher) plus this compact manufacturer
 *   section is the most portable combination.
 */
object PayloadCodec {

    /** Bluetooth SIG reserved Company ID — dev/test only.
     *  Replace with your registered Company ID before production. */
    const val COMPANY_ID = 0xFFFF

    /** Distinguishes attendance packets from any other manufacturer data. */
    const val MAGIC: Byte = 0xB5.toByte()

    const val MFG_PAYLOAD_LEN = 8 // MAGIC + HOP + SESSION(4) + RESERVED(2)

    /** Shared attendance service UUID — must match TeacherBroadcaster.cs */
    val ATTENDANCE_SERVICE_UUID: ParcelUuid =
        ParcelUuid(UUID.fromString("a5e8c0de-0001-4b7d-9c11-000000000001"))

    fun encode(hopCount: Int, sessionId: Int): ByteArray {
        require(hopCount in 0..MAX_HOPS) { "hop_count out of range" }
        return ByteBuffer.allocate(MFG_PAYLOAD_LEN)
            .order(ByteOrder.BIG_ENDIAN)
            .put(MAGIC)
            .put(hopCount.toByte())
            .putInt(sessionId)
            .putShort(0) // reserved
            .array()
    }

    data class Decoded(val sessionId: Int, val hopCount: Int)

    /** Returns null when the packet is not ours (wrong company/magic/size). */
    fun decode(data: ByteArray?): Decoded? {
        if (data == null || data.size != MFG_PAYLOAD_LEN) return null
        val buf = ByteBuffer.wrap(data).order(ByteOrder.BIG_ENDIAN)
        if (buf.get() != MAGIC) return null
        val hop = buf.get().toInt() and 0xFF
        val session = buf.int
        return Decoded(sessionId = session, hopCount = hop)
    }

    const val MAX_HOPS = 3
}
