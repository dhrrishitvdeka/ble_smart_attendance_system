package com.example.attendance.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.example.attendance.R
import com.example.attendance.models.AttendanceRecord
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class HistoryAdapter(
    private var records: List<AttendanceRecord> = emptyList()
) : RecyclerView.Adapter<HistoryAdapter.ViewHolder>() {

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val tvSessionId: TextView = view.findViewById(R.id.tvHistorySessionId)
        val tvStatus: TextView = view.findViewById(R.id.tvHistoryStatus)
        val tvDetails: TextView = view.findViewById(R.id.tvHistoryDetails)
        val tvTime: TextView = view.findViewById(R.id.tvHistoryTime)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_history, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val r = records[position]
        holder.tvSessionId.text = "Session: ${r.sessionId}"
        holder.tvStatus.text = r.status

        val viaInfo = if (r.viaStudent != null) " via ${r.viaStudent}" else ""
        holder.tvDetails.text = "${r.routeType} (${r.rssi} dBm) | Hop ${r.hopCount}$viaInfo"

        val sdf = SimpleDateFormat("MMM dd, HH:mm", Locale.getDefault())
        holder.tvTime.text = sdf.format(Date(r.timestamp))
    }

    override fun getItemCount(): Int = records.size

    fun updateRecords(newRecords: List<AttendanceRecord>) {
        records = newRecords
        notifyDataSetChanged()
    }
}
