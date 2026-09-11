package com.example.attendance

import java.util.UUID

/** Shared protocol constants — must match shared/ble_config.json. */
object Protocol {
    val SERVICE_UUID: UUID = UUID.fromString("a5e8c0de-0001-4b7d-9c11-000000000001")
    const val COMPANY_ID = 0xFFFF
    const val MAGIC: Byte = 0xB5.toByte()
    const val MAX_HOPS = 2
    const val RSSI_THRESHOLD_DBM = -85
}
