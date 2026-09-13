using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using TeacherApp.Database;

namespace TeacherApp.Services;

public class CloudSyncService
{
    private readonly HttpClient _http;
    private readonly AttendanceDatabase _db;

    public CloudSyncService(AttendanceDatabase db, HttpClient? http = null)
    {
        _db = db;
        _http = http ?? new HttpClient();
        _http.Timeout = TimeSpan.FromSeconds(5);
    }


    public async Task<string?> LoginToCloudAsync(string backendUrl, string teacherId, string password)
    {
        try
        {
            var payload = JsonSerializer.Serialize(new { username = teacherId, password = password });
            var content = new StringContent(payload, Encoding.UTF8, "application/json");
            var resp = await _http.PostAsync($"{backendUrl.TrimEnd('/')}/api/auth/login", content);
            if (!resp.IsSuccessStatusCode) return null;

            var body = await resp.Content.ReadAsStringAsync();
            using var doc = JsonDocument.Parse(body);
            if (doc.RootElement.TryGetProperty("access_token", out var tokenProp))
            {
                return tokenProp.GetString();
            }
        }
        catch (Exception ex)
        {
            _db.LogAudit("CLOUD_LOGIN_ERROR", ex.Message);
        }
        return null;
    }

    public async Task<(bool Success, int SyncedCount, string Message)> SyncBatchAsync(
        string backendUrl,
        string? bearerToken = null)
    {
        var unsynced = _db.GetUnsyncedAttendance();
        if (unsynced.Count == 0)
        {
            return (true, 0, "No pending records to sync.");
        }

        try
        {
            var items = new List<object>();
            foreach (var r in unsynced)
            {
                items.Add(new
                {
                    attendance_id = r.AttendanceId,
                    session_id = r.SessionId,
                    student_id = r.StudentId,
                    timestamp = r.Timestamp,
                    verification_status = r.VerificationStatus,
                    route_type = r.RouteType,
                    rssi_evidence = r.RssiEvidence,
                    hop_count = r.HopCount,
                    via_student = r.ViaStudent
                });
            }

            var json = JsonSerializer.Serialize(items);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var request = new HttpRequestMessage(HttpMethod.Post, $"{backendUrl.TrimEnd('/')}/api/attendance/batch")
            {
                Content = content
            };

            if (!string.IsNullOrWhiteSpace(bearerToken))
            {
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", bearerToken);
            }

            var response = await _http.SendAsync(request);
            if (response.IsSuccessStatusCode)
            {
                foreach (var r in unsynced)
                {
                    _db.MarkAttendanceSynced(r.AttendanceId);
                }
                _db.LogAudit("CLOUD_SYNC_SUCCESS", $"Pushed {unsynced.Count} records to cloud backend.");
                return (true, unsynced.Count, $"Successfully synced {unsynced.Count} records to cloud.");
            }
            else
            {
                var err = await response.Content.ReadAsStringAsync();
                _db.LogAudit("CLOUD_SYNC_FAILED", $"Status {(int)response.StatusCode}: {err}");
                return (false, 0, $"Cloud sync failed with HTTP {(int)response.StatusCode}: {err}");
            }
        }
        catch (Exception ex)
        {
            _db.LogAudit("CLOUD_SYNC_ERROR", ex.Message);
            return (false, 0, $"Network error connecting to cloud: {ex.Message}");
        }
    }

    public async Task<(bool Success, int SyncedCount, string Message)> SyncRelayEventsBatchAsync(
        string backendUrl,
        string? bearerToken = null)
    {
        var unsynced = _db.GetUnsyncedRelayEvents();
        if (unsynced.Count == 0)
        {
            return (true, 0, "No pending relay events to sync.");
        }

        try
        {
            var items = new List<object>();
            foreach (var r in unsynced)
            {
                items.Add(new
                {
                    event_id = r.EventId,
                    session_id = r.SessionId,
                    message_id = r.MessageId,
                    source_student_id = r.SourceStudentId,
                    relay_student_id = r.RelayStudentId,
                    hop_count = r.HopCount,
                    timestamp = r.Timestamp,
                    status = r.Status
                });
            }

            var json = JsonSerializer.Serialize(items);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var request = new HttpRequestMessage(HttpMethod.Post, $"{backendUrl.TrimEnd('/')}/api/relay-events/batch")
            {
                Content = content
            };

            if (!string.IsNullOrWhiteSpace(bearerToken))
            {
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", bearerToken);
            }

            var response = await _http.SendAsync(request);
            if (response.IsSuccessStatusCode)
            {
                foreach (var r in unsynced)
                {
                    _db.MarkRelayEventSynced(r.EventId);
                }
                _db.LogAudit("CLOUD_RELAY_SYNC_SUCCESS", $"Pushed {unsynced.Count} relay events to cloud backend.");
                return (true, unsynced.Count, $"Successfully synced {unsynced.Count} relay events to cloud.");
            }
            else
            {
                var err = await response.Content.ReadAsStringAsync();
                _db.LogAudit("CLOUD_RELAY_SYNC_FAILED", $"Status {(int)response.StatusCode}: {err}");
                return (false, 0, $"Relay events sync failed with HTTP {(int)response.StatusCode}: {err}");
            }
        }
        catch (Exception ex)
        {
            _db.LogAudit("CLOUD_RELAY_SYNC_ERROR", ex.Message);
            return (false, 0, $"Network error syncing relay events: {ex.Message}");
        }
    }

    public async Task<(bool Success, int SyncedAttendance, int SyncedRelay, string Message)> SyncAllAsync(
        string backendUrl,
        string? bearerToken = null)
    {
        var attResult = await SyncBatchAsync(backendUrl, bearerToken);
        var relayResult = await SyncRelayEventsBatchAsync(backendUrl, bearerToken);

        bool overallSuccess = attResult.Success && relayResult.Success;
        string combinedMessage = $"Attendance: {attResult.Message} | Relay Events: {relayResult.Message}";
        return (overallSuccess, attResult.SyncedCount, relayResult.SyncedCount, combinedMessage);
    }
}
