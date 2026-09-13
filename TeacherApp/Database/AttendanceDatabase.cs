using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Data.Sqlite;

namespace TeacherApp.Database;

public record TeacherRecord(string TeacherId, string Name, string Email, string PasswordHash);
public record ClassRecord(string ClassId, string ClassName, string Subject, string TeacherId);
public record StudentRecord(string StudentId, string Name, string Email, string RegisteredDeviceId, string DeviceSecret, string ClassId);
public record SessionRecord(string SessionId, string ClassId, string TeacherId, string Subject, long StartTime, long ExpirationTime, string RandomNonce, string Status);
public record AttendanceRecord(string AttendanceId, string SessionId, string StudentId, long Timestamp, string VerificationStatus, string RouteType, int? RssiEvidence, int HopCount, string? ViaStudent, bool Synced);
public record RelayRecord(string EventId, string SessionId, string MessageId, string SourceStudentId, string RelayStudentId, int HopCount, long Timestamp, string Status);


public class AttendanceDatabase : IDisposable
{
    private readonly string _connectionString;
    private readonly SqliteConnection _connection;

    public AttendanceDatabase(string dbPath = "teacher_attendance.db")
    {
        _connectionString = $"Data Source={dbPath}";
        _connection = new SqliteConnection(_connectionString);
        _connection.Open();
        InitializeSchema();
        SeedDefaultData();
    }

    private void InitializeSchema()
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            CREATE TABLE IF NOT EXISTS teachers (
                teacher_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT,
                password_hash TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS classes (
                class_id TEXT PRIMARY KEY,
                class_name TEXT NOT NULL,
                subject TEXT NOT NULL,
                teacher_id TEXT,
                FOREIGN KEY (teacher_id) REFERENCES teachers(teacher_id)
            );

            CREATE TABLE IF NOT EXISTS students (
                student_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT,
                registered_device_id TEXT NOT NULL,
                device_secret TEXT NOT NULL,
                class_id TEXT,
                FOREIGN KEY (class_id) REFERENCES classes(class_id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                class_id TEXT NOT NULL,
                teacher_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                start_time INTEGER NOT NULL,
                expiration_time INTEGER NOT NULL,
                random_nonce TEXT NOT NULL,
                status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attendance (
                attendance_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                verification_status TEXT NOT NULL,
                route_type TEXT NOT NULL,
                rssi_evidence INTEGER,
                hop_count INTEGER DEFAULT 0,
                via_student TEXT,
                synced INTEGER DEFAULT 0,
                UNIQUE(session_id, student_id)
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                log_id TEXT PRIMARY KEY,
                timestamp INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                detail TEXT
            );

            CREATE TABLE IF NOT EXISTS relay_events (
                event_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                source_student_id TEXT NOT NULL,
                relay_student_id TEXT NOT NULL,
                hop_count INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                status TEXT NOT NULL,
                synced INTEGER DEFAULT 0
            );
        ";
        cmd.ExecuteNonQuery();

        try
        {
            using var alterCmd = _connection.CreateCommand();
            alterCmd.CommandText = "ALTER TABLE relay_events ADD COLUMN synced INTEGER DEFAULT 0;";
            alterCmd.ExecuteNonQuery();
        }
        catch { /* column already exists */ }
    }


    private void SeedDefaultData()
    {
        using var checkCmd = _connection.CreateCommand();
        checkCmd.CommandText = "SELECT COUNT(*) FROM teachers;";
        var count = (long)(checkCmd.ExecuteScalar() ?? 0L);
        if (count > 0) return;

        using var tx = _connection.BeginTransaction();
        try
        {
            // Seed teacher T001
            using (var cmd = _connection.CreateCommand())
            {
                cmd.Transaction = tx;
                cmd.CommandText = @"
                    INSERT INTO teachers (teacher_id, name, email, password_hash)
                    VALUES ('T001', 'Dr. Sharma', 'sharma@college.edu', 'teach123');
                    INSERT INTO classes (class_id, class_name, subject, teacher_id)
                    VALUES ('CSE-A', 'CSE-A', 'Data Structures', 'T001');
                ";
                cmd.ExecuteNonQuery();
            }

            // Seed students S001-S006
            var names = new[] { "Aarav Kumar", "Diya Patel", "Rohan Verma", "Ishaan Singh", "Meera Iyer", "Kabir Shah" };
            for (int i = 0; i < names.Length; i++)
            {
                var sid = $"S00{i + 1}";
                var secret = Convert.ToHexString(RandomNumberGenerator.GetBytes(8));
                using var cmd = _connection.CreateCommand();
                cmd.Transaction = tx;
                cmd.CommandText = @"
                    INSERT INTO students (student_id, name, email, registered_device_id, device_secret, class_id)
                    VALUES (@sid, @name, @email, @dev, @secret, 'CSE-A');
                ";
                cmd.Parameters.AddWithValue("@sid", sid);
                cmd.Parameters.AddWithValue("@name", names[i]);
                cmd.Parameters.AddWithValue("@email", $"{sid.ToLower()}@student.college.edu");
                cmd.Parameters.AddWithValue("@dev", $"DEV-{sid}");
                cmd.Parameters.AddWithValue("@secret", secret);
                cmd.ExecuteNonQuery();
            }

            tx.Commit();
        }
        catch
        {
            tx.Rollback();
            throw;
        }
    }

    public TeacherRecord? AuthenticateTeacher(string teacherId, string password)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT teacher_id, name, email, password_hash FROM teachers WHERE teacher_id = @tid;";
        cmd.Parameters.AddWithValue("@tid", teacherId.ToUpper());
        using var reader = cmd.ExecuteReader();
        if (reader.Read())
        {
            var hash = reader.GetString(3);
            if (hash == password)
            {
                return new TeacherRecord(reader.GetString(0), reader.GetString(1), reader.IsDBNull(2) ? "" : reader.GetString(2), hash);
            }
        }
        return null;
    }

    public List<ClassRecord> GetTeacherClasses(string teacherId)
    {
        var list = new List<ClassRecord>();
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT class_id, class_name, subject, teacher_id FROM classes WHERE teacher_id = @tid;";
        cmd.Parameters.AddWithValue("@tid", teacherId);
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            list.Add(new ClassRecord(reader.GetString(0), reader.GetString(1), reader.GetString(2), reader.GetString(3)));
        }
        return list;
    }

    public List<StudentRecord> GetClassStudents(string classId)
    {
        var list = new List<StudentRecord>();
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT student_id, name, email, registered_device_id, device_secret, class_id FROM students WHERE class_id = @cid;";
        cmd.Parameters.AddWithValue("@cid", classId);
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            list.Add(new StudentRecord(
                reader.GetString(0), reader.GetString(1),
                reader.IsDBNull(2) ? "" : reader.GetString(2),
                reader.GetString(3), reader.GetString(4), reader.GetString(5)
            ));
        }
        return list;
    }

    public StudentRecord? GetStudent(string studentId)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT student_id, name, email, registered_device_id, device_secret, class_id FROM students WHERE student_id = @sid;";
        cmd.Parameters.AddWithValue("@sid", studentId);
        using var reader = cmd.ExecuteReader();
        if (reader.Read())
        {
            return new StudentRecord(
                reader.GetString(0), reader.GetString(1),
                reader.IsDBNull(2) ? "" : reader.GetString(2),
                reader.GetString(3), reader.GetString(4), reader.GetString(5)
            );
        }
        return null;
    }

    public bool AddStudent(string studentId, string name, string email, string registeredDeviceId, string deviceSecret, string classId)
    {
        try
        {
            using var cmd = _connection.CreateCommand();
            cmd.CommandText = @"
                INSERT INTO students (student_id, name, email, registered_device_id, device_secret, class_id)
                VALUES (@sid, @name, @email, @dev, @sec, @cid);
            ";
            cmd.Parameters.AddWithValue("@sid", studentId);
            cmd.Parameters.AddWithValue("@name", name);
            cmd.Parameters.AddWithValue("@email", email);
            cmd.Parameters.AddWithValue("@dev", registeredDeviceId);
            cmd.Parameters.AddWithValue("@sec", deviceSecret);
            cmd.Parameters.AddWithValue("@cid", classId);
            return cmd.ExecuteNonQuery() > 0;
        }
        catch { return false; }
    }

    public SessionRecord CreateSession(string classId, string teacherId, string subject, long durationMs = 600000)
    {
        var sessionId = Convert.ToHexString(RandomNumberGenerator.GetBytes(4));
        var nonce = Convert.ToHexString(RandomNumberGenerator.GetBytes(8));
        var startTime = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        var expTime = startTime + durationMs;

        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            INSERT INTO sessions (session_id, class_id, teacher_id, subject, start_time, expiration_time, random_nonce, status)
            VALUES (@sid, @cid, @tid, @sub, @st, @exp, @nonce, 'ACTIVE');
        ";
        cmd.Parameters.AddWithValue("@sid", sessionId);
        cmd.Parameters.AddWithValue("@cid", classId);
        cmd.Parameters.AddWithValue("@tid", teacherId);
        cmd.Parameters.AddWithValue("@sub", subject);
        cmd.Parameters.AddWithValue("@st", startTime);
        cmd.Parameters.AddWithValue("@exp", expTime);
        cmd.Parameters.AddWithValue("@nonce", nonce);
        cmd.ExecuteNonQuery();

        LogAudit("SESSION_START", $"Session {sessionId} started for class {classId}");
        return new SessionRecord(sessionId, classId, teacherId, subject, startTime, expTime, nonce, "ACTIVE");
    }

    public bool RecordAttendance(string attendanceId, string sessionId, string studentId, string status, string routeType, int? rssi, int hopCount, string? viaStudent)
    {
        try
        {
            using var cmd = _connection.CreateCommand();
            cmd.CommandText = @"
                INSERT OR REPLACE INTO attendance (attendance_id, session_id, student_id, timestamp, verification_status, route_type, rssi_evidence, hop_count, via_student, synced)
                VALUES (@aid, @sid, @stuid, @ts, @status, @route, @rssi, @hops, @via, 0);
            ";
            cmd.Parameters.AddWithValue("@aid", attendanceId);
            cmd.Parameters.AddWithValue("@sid", sessionId);
            cmd.Parameters.AddWithValue("@stuid", studentId);
            cmd.Parameters.AddWithValue("@ts", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            cmd.Parameters.AddWithValue("@status", status);
            cmd.Parameters.AddWithValue("@route", routeType);
            cmd.Parameters.AddWithValue("@rssi", (object?)rssi ?? DBNull.Value);
            cmd.Parameters.AddWithValue("@hops", hopCount);
            cmd.Parameters.AddWithValue("@via", (object?)viaStudent ?? DBNull.Value);
            cmd.ExecuteNonQuery();

            LogAudit("ATTENDANCE_RECORDED", $"Student {studentId} marked {status} via {routeType} (RSSI: {rssi} dBm)");
            return true;
        }
        catch
        {
            return false;
        }
    }

    public List<AttendanceRecord> GetSessionAttendance(string sessionId)
    {
        var list = new List<AttendanceRecord>();
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT attendance_id, session_id, student_id, timestamp, verification_status, route_type, rssi_evidence, hop_count, via_student, synced FROM attendance WHERE session_id = @sid;";
        cmd.Parameters.AddWithValue("@sid", sessionId);
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            list.Add(new AttendanceRecord(
                reader.GetString(0), reader.GetString(1), reader.GetString(2),
                reader.GetInt64(3), reader.GetString(4), reader.GetString(5),
                reader.IsDBNull(6) ? null : reader.GetInt32(6),
                reader.GetInt32(7),
                reader.IsDBNull(8) ? null : reader.GetString(8),
                reader.GetInt32(9) == 1
            ));
        }
        return list;
    }

    public int FinalizeAttendance(string sessionId, string teacherId)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            UPDATE attendance
            SET verification_status = 'PRESENT'
            WHERE session_id = @sid AND verification_status = 'ELIGIBLE';
        ";
        cmd.Parameters.AddWithValue("@sid", sessionId);
        int modified = cmd.ExecuteNonQuery();

        using var sessCmd = _connection.CreateCommand();
        sessCmd.CommandText = "UPDATE sessions SET status = 'FINALIZED' WHERE session_id = @sid;";
        sessCmd.Parameters.AddWithValue("@sid", sessionId);
        sessCmd.ExecuteNonQuery();

        LogAudit("SESSION_FINALIZED", $"Session {sessionId} finalized by {teacherId}. {modified} students marked PRESENT.");
        return modified;
    }

    public List<AttendanceRecord> GetUnsyncedAttendance()
    {
        var list = new List<AttendanceRecord>();
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT attendance_id, session_id, student_id, timestamp, verification_status, route_type, rssi_evidence, hop_count, via_student, synced FROM attendance WHERE synced = 0;";
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            list.Add(new AttendanceRecord(
                reader.GetString(0), reader.GetString(1), reader.GetString(2),
                reader.GetInt64(3), reader.GetString(4), reader.GetString(5),
                reader.IsDBNull(6) ? null : reader.GetInt32(6),
                reader.GetInt32(7),
                reader.IsDBNull(8) ? null : reader.GetString(8),
                reader.GetInt32(9) == 1
            ));
        }
        return list;
    }

    public void MarkAttendanceSynced(string attendanceId)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "UPDATE attendance SET synced = 1 WHERE attendance_id = @aid;";
        cmd.Parameters.AddWithValue("@aid", attendanceId);
        cmd.ExecuteNonQuery();
    }

    public void LogAudit(string eventType, string detail)
    {
        try
        {
            using var cmd = _connection.CreateCommand();
            cmd.CommandText = @"
                INSERT INTO audit_logs (log_id, timestamp, event_type, detail)
                VALUES (@lid, @ts, @type, @detail);
            ";
            cmd.Parameters.AddWithValue("@lid", Guid.NewGuid().ToString("N"));
            cmd.Parameters.AddWithValue("@ts", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            cmd.Parameters.AddWithValue("@type", eventType);
            cmd.Parameters.AddWithValue("@detail", detail);
            cmd.ExecuteNonQuery();
        }
        catch { }
    }

    public bool RecordRelayEvent(string eventId, string sessionId, string messageId, string sourceStudentId, string relayStudentId, int hopCount, long timestamp, string status)
    {
        try
        {
            using var cmd = _connection.CreateCommand();
            cmd.CommandText = @"
                INSERT OR IGNORE INTO relay_events (event_id, session_id, message_id, source_student_id, relay_student_id, hop_count, timestamp, status, synced)
                VALUES (@eid, @sid, @mid, @src, @rl, @hops, @ts, @st, 0);
            ";
            cmd.Parameters.AddWithValue("@eid", eventId);
            cmd.Parameters.AddWithValue("@sid", sessionId);
            cmd.Parameters.AddWithValue("@mid", messageId);
            cmd.Parameters.AddWithValue("@src", sourceStudentId);
            cmd.Parameters.AddWithValue("@rl", relayStudentId);
            cmd.Parameters.AddWithValue("@hops", hopCount);
            cmd.Parameters.AddWithValue("@ts", timestamp);
            cmd.Parameters.AddWithValue("@st", status);
            return cmd.ExecuteNonQuery() > 0;
        }
        catch { return false; }
    }

    public List<RelayRecord> GetSessionRelayEvents(string sessionId)
    {
        var list = new List<RelayRecord>();
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT event_id, session_id, message_id, source_student_id, relay_student_id, hop_count, timestamp, status FROM relay_events WHERE session_id = @sid ORDER BY timestamp ASC;";
        cmd.Parameters.AddWithValue("@sid", sessionId);
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            list.Add(new RelayRecord(
                reader.GetString(0),
                reader.GetString(1),
                reader.GetString(2),
                reader.GetString(3),
                reader.GetString(4),
                reader.GetInt32(5),
                reader.GetInt64(6),
                reader.GetString(7)
            ));
        }
        return list;
    }

    public List<RelayRecord> GetUnsyncedRelayEvents()
    {
        var list = new List<RelayRecord>();
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT event_id, session_id, message_id, source_student_id, relay_student_id, hop_count, timestamp, status FROM relay_events WHERE synced = 0 ORDER BY timestamp ASC;";
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            list.Add(new RelayRecord(
                reader.GetString(0),
                reader.GetString(1),
                reader.GetString(2),
                reader.GetString(3),
                reader.GetString(4),
                reader.GetInt32(5),
                reader.GetInt64(6),
                reader.GetString(7)
            ));
        }
        return list;
    }

    public void MarkRelayEventSynced(string eventId)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "UPDATE relay_events SET synced = 1 WHERE event_id = @id;";
        cmd.Parameters.AddWithValue("@id", eventId);
        cmd.ExecuteNonQuery();
    }

    public void Dispose()
    {
        _connection?.Dispose();
    }
}

