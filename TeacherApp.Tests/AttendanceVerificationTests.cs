using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using Microsoft.VisualStudio.TestTools.UnitTesting;
using TeacherApp.BLE;
using TeacherApp.Database;

namespace TeacherApp.Tests;

[TestClass]
public class AttendanceVerificationTests
{
    private string _testDbPath = null!;
    private AttendanceDatabase _db = null!;
    private SessionRecord _session = null!;

    [TestInitialize]
    public void Setup()
    {
        _testDbPath = $"test_attendance_{Guid.NewGuid():N}.db";
        _db = new AttendanceDatabase(_testDbPath);
        _session = _db.CreateSession("CSE-A", "T001", "Data Structures");
    }

    [TestCleanup]
    public void Cleanup()
    {
        _db.Dispose();
        try
        {
            if (File.Exists(_testDbPath)) File.Delete(_testDbPath);
        }
        catch { }
    }

    private static string ComputeHash(string raw)
    {
        using var sha = SHA256.Create();
        return Convert.ToHexString(sha.ComputeHash(Encoding.UTF8.GetBytes(raw))).ToLower();
    }

    [TestMethod]
    public void TestTeacherAuthentication_Success()
    {
        var teacher = _db.AuthenticateTeacher("T001", "teach123");
        Assert.IsNotNull(teacher);
        Assert.AreEqual("T001", teacher.TeacherId);
        Assert.AreEqual("Dr. Sharma", teacher.Name);
    }

    [TestMethod]
    public void TestTeacherAuthentication_BadPassword()
    {
        var teacher = _db.AuthenticateTeacher("T001", "wrongpassword");
        Assert.IsNull(teacher);
    }

    [TestMethod]
    public void TestTeacherAuthentication_UnknownUser()
    {
        var teacher = _db.AuthenticateTeacher("NON_EXISTENT", "teach123");
        Assert.IsNull(teacher);
    }

    [TestMethod]
    public void TestSessionCreation_AndValidation()
    {
        Assert.AreEqual("ACTIVE", _session.Status);
        Assert.AreEqual("CSE-A", _session.ClassId);
        Assert.AreEqual("T001", _session.TeacherId);
        Assert.AreEqual(8, _session.SessionId.Length);
        Assert.AreEqual(16, _session.RandomNonce.Length);
        Assert.IsGreaterThan(_session.StartTime, _session.ExpirationTime);
    }



    [TestMethod]
    public void TestDirectAttendance_VerificationSuccess()
    {
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(_session).GetAwaiter().GetResult();

        var s1 = _db.GetStudent("S001")!;
        string challengeNonce = "0123456789ABCDEF0123456789ABCDEF";
        server.RegisterChallengeForTest(s1.StudentId, challengeNonce);

        string responseHash = ComputeHash(challengeNonce + s1.DeviceSecret);
        bool verified = server.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, responseHash, "DIRECT", -60, 0, null);

        Assert.IsTrue(verified, "Legitimate student check-in with valid hardware secret should succeed.");

        var records = _db.GetSessionAttendance(_session.SessionId);
        var rec = records.Find(r => r.StudentId == "S001");
        Assert.IsNotNull(rec);
        Assert.AreEqual("ELIGIBLE", rec.VerificationStatus);
        Assert.AreEqual("DIRECT", rec.RouteType);
        Assert.AreEqual(-60, rec.RssiEvidence);
    }

    [TestMethod]
    public void TestDirectAttendance_UnregisteredDeviceRejected()
    {
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(_session).GetAwaiter().GetResult();

        var s1 = _db.GetStudent("S001")!;
        string challengeNonce = "AABBCCDDEEFF00112233445566778899";
        server.RegisterChallengeForTest(s1.StudentId, challengeNonce);

        string responseHash = ComputeHash(challengeNonce + s1.DeviceSecret);
        bool verified = server.VerifyAndCommit(s1.StudentId, "DEV-SPOOFED-ID", responseHash, "DIRECT", -60, 0, null);

        Assert.IsFalse(verified, "Check-in from unregistered device ID must be rejected.");
    }

    [TestMethod]
    public void TestDirectAttendance_WeakRssiRejected()
    {
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(_session).GetAwaiter().GetResult();

        var s1 = _db.GetStudent("S001")!;
        string challengeNonce = "112233445566778899AABBCCDDEEFF00";
        server.RegisterChallengeForTest(s1.StudentId, challengeNonce);

        string responseHash = ComputeHash(challengeNonce + s1.DeviceSecret);
        bool verified = server.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, responseHash, "DIRECT", -95, 0, null);

        Assert.IsFalse(verified, "RSSI <= -90 dBm floor threshold must be rejected.");
    }

    [TestMethod]
    public void TestDirectAttendance_CryptographicMismatchRejected()
    {
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(_session).GetAwaiter().GetResult();

        var s1 = _db.GetStudent("S001")!;
        string challengeNonce = "FEDCBA9876543210FEDCBA9876543210";
        server.RegisterChallengeForTest(s1.StudentId, challengeNonce);

        string wrongHash = ComputeHash(challengeNonce + "WRONG_SECRET");
        bool verified = server.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, wrongHash, "DIRECT", -55, 0, null);

        Assert.IsFalse(verified, "Invalid cryptographic challenge response must be rejected.");
    }

    [TestMethod]
    public void TestDirectAttendance_ReplayAttackPrevented()
    {
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(_session).GetAwaiter().GetResult();

        var s1 = _db.GetStudent("S001")!;
        string challengeNonce = "CAFEBABEDEADBEEFCAFEBABEDEADBEEF";
        server.RegisterChallengeForTest(s1.StudentId, challengeNonce);

        string responseHash = ComputeHash(challengeNonce + s1.DeviceSecret);

        // First attempt -> succeeds
        bool first = server.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, responseHash, "DIRECT", -65, 0, null);
        Assert.IsTrue(first);

        // Replay attempt with same challenge -> rejected because challenge is single-use
        bool replay = server.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, responseHash, "DIRECT", -65, 0, null);
        Assert.IsFalse(replay, "Replaying a previously used challenge response must be rejected.");
    }

    [TestMethod]
    public void TestRelayAttendance_MultiHopSuccess()
    {
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(_session).GetAwaiter().GetResult();

        var s3 = _db.GetStudent("S003")!;
        string challengeNonce = "00112233445566778899AABBCCDDEEFF";
        server.RegisterChallengeForTest(s3.StudentId, challengeNonce);

        string responseHash = ComputeHash(challengeNonce + s3.DeviceSecret);
        bool verified = server.VerifyAndCommit(s3.StudentId, s3.RegisteredDeviceId, responseHash, "RELAY", -76, 2, "Diya Patel (S002)");

        Assert.IsTrue(verified, "Relayed attendance via peer student within max hops must succeed.");

        var records = _db.GetSessionAttendance(_session.SessionId);
        var rec = records.Find(r => r.StudentId == "S003");
        Assert.IsNotNull(rec);
        Assert.AreEqual("ELIGIBLE", rec.VerificationStatus);
        Assert.AreEqual("RELAY", rec.RouteType);
        Assert.AreEqual(2, rec.HopCount);
        Assert.AreEqual("Diya Patel (S002)", rec.ViaStudent);
    }

    [TestMethod]
    public void TestRelayAttendance_HopLimitExceededRejected()
    {
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(_session).GetAwaiter().GetResult();

        var s3 = _db.GetStudent("S003")!;
        string challengeNonce = "12345678901234567890123456789012";
        server.RegisterChallengeForTest(s3.StudentId, challengeNonce);

        string responseHash = ComputeHash(challengeNonce + s3.DeviceSecret);
        // Hop count 3 > MAX_HOPS (2)
        bool verified = server.VerifyAndCommit(s3.StudentId, s3.RegisteredDeviceId, responseHash, "RELAY", -78, 3, "Peer C");

        Assert.IsFalse(verified, "Relay request exceeding MAX_HOPS (2) must be rejected.");
    }

    [TestMethod]
    public void TestFinalization_EligibleToPresent()
    {
        // Add attendance records
        _db.RecordAttendance("att_1", _session.SessionId, "S001", "ELIGIBLE", "DIRECT", -60, 0, null);
        _db.RecordAttendance("att_2", _session.SessionId, "S002", "ELIGIBLE", "RELAY", -75, 1, "S001");

        int count = _db.FinalizeAttendance(_session.SessionId, "T001");
        Assert.AreEqual(2, count, "Both ELIGIBLE records should be finalized.");

        var records = _db.GetSessionAttendance(_session.SessionId);
        foreach (var r in records)
        {
            Assert.AreEqual("PRESENT", r.VerificationStatus);
        }
    }

    [TestMethod]
    public void TestRelayEvents_PersistenceAndRetrieval()
    {
        bool recorded = _db.RecordRelayEvent(
            "rl_unit_01",
            _session.SessionId,
            "msg_unit_01",
            "S003",
            "S002",
            2,
            DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            "FORWARDED"
        );
        Assert.IsTrue(recorded);

        var events = _db.GetSessionRelayEvents(_session.SessionId);
        Assert.HasCount(1, events);
        Assert.AreEqual("rl_unit_01", events[0].EventId);

        Assert.AreEqual("S003", events[0].SourceStudentId);
        Assert.AreEqual("S002", events[0].RelayStudentId);
        Assert.AreEqual(2, events[0].HopCount);
    }

    [TestMethod]
    public async Task TestCloudSyncService_EmptyBatchReturnsSuccess()
    {
        var sync = new TeacherApp.Services.CloudSyncService(_db);
        var result = await sync.SyncBatchAsync("http://localhost:8000");
        Assert.IsTrue(result.Success);
        Assert.AreEqual(0, result.SyncedCount);
    }

    [TestMethod]
    public async Task TestCloudSyncService_SuccessfulBatchPush()
    {
        _db.RecordAttendance("att_sync_1", _session.SessionId, "S001", "PRESENT", "DIRECT", -60, 0, null);
        var mockHandler = new MockHttpMessageHandler((req) =>
        {
            if (req.RequestUri!.AbsolutePath.EndsWith("/api/attendance/batch"))
            {
                return new System.Net.Http.HttpResponseMessage(System.Net.HttpStatusCode.OK)
                {
                    Content = new System.Net.Http.StringContent("{\"stored\": 1, \"duplicates_ignored\": 0}", Encoding.UTF8, "application/json")
                };
            }
            return new System.Net.Http.HttpResponseMessage(System.Net.HttpStatusCode.NotFound);
        });

        using var client = new System.Net.Http.HttpClient(mockHandler);
        var sync = new TeacherApp.Services.CloudSyncService(_db, client);
        var result = await sync.SyncBatchAsync("http://fake-cloud", "test-token");

        Assert.IsTrue(result.Success);
        Assert.AreEqual(1, result.SyncedCount);

        var unsynced = _db.GetUnsyncedAttendance();
        Assert.HasCount(0, unsynced);
    }

    [TestMethod]
    public void TestDirectAttendance_WrongClassEnrollmentRejected()
    {
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(_session).GetAwaiter().GetResult();

        // Create student in CSE-B
        _db.AddStudent("S999", "Other Class Student", "s999@college.edu", "DEV-S999", "SECRET999", "CSE-B");

        string challengeNonce = "AABBCCDDEEFF00112233445566778899";
        server.RegisterChallengeForTest("S999", challengeNonce);

        string responseHash = ComputeHash(challengeNonce + "SECRET999");
        bool verified = server.VerifyAndCommit("S999", "DEV-S999", responseHash, "DIRECT", -60, 0, null);

        Assert.IsFalse(verified, "Student enrolled in a different class must be rejected.");
    }

    [TestMethod]
    public void TestDirectAttendance_ExpiredChallengeRejected()
    {
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(_session).GetAwaiter().GetResult();

        var s1 = _db.GetStudent("S001")!;
        string challengeNonce = "EXPIRED_NONCE_123456789012345678";
        // Register challenge with negative TTL (already expired)
        server.RegisterChallengeForTest(s1.StudentId, challengeNonce, ttlMs: -5000);

        string responseHash = ComputeHash(challengeNonce + s1.DeviceSecret);
        bool verified = server.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, responseHash, "DIRECT", -60, 0, null);

        Assert.IsFalse(verified, "Expired challenge must be rejected.");
    }

    [TestMethod]
    public void TestDirectAttendance_InactiveSessionRejected()
    {
        // Session with EXPIRED status
        var inactiveSession = new SessionRecord("SES_INACTIVE", "CSE-A", "T001", "Data Structures", 1000, 2000, "NONCE", "EXPIRED");
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(inactiveSession).GetAwaiter().GetResult();

        var s1 = _db.GetStudent("S001")!;
        string challengeNonce = "NONCE_FOR_INACTIVE_SESSION";
        server.RegisterChallengeForTest(s1.StudentId, challengeNonce);

        string responseHash = ComputeHash(challengeNonce + s1.DeviceSecret);
        bool verified = server.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, responseHash, "DIRECT", -60, 0, null);

        Assert.IsFalse(verified, "Attendance for non-active session must be rejected.");
    }

    [TestMethod]
    public void TestRelayEvents_UnsyncedQueryAndMarkSynced()
    {
        bool recorded = _db.RecordRelayEvent(
            "rl_unsynced_01",
            _session.SessionId,
            "msg_unsynced_01",
            "S003",
            "S002",
            2,
            DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            "FORWARDED"
        );
        Assert.IsTrue(recorded);

        var unsynced = _db.GetUnsyncedRelayEvents();
        Assert.HasCount(1, unsynced);
        Assert.AreEqual("rl_unsynced_01", unsynced[0].EventId);

        _db.MarkRelayEventSynced("rl_unsynced_01");

        var unsyncedAfter = _db.GetUnsyncedRelayEvents();
        Assert.IsEmpty(unsyncedAfter);
    }

    [TestMethod]
    public async Task TestCloudSyncService_SuccessfulRelayBatchPush()
    {
        _db.RecordRelayEvent(
            "rl_sync_test_01",
            _session.SessionId,
            "msg_sync_01",
            "S003",
            "S002",
            2,
            DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            "FORWARDED"
        );

        var mockHandler = new MockHttpMessageHandler((req) =>
        {
            if (req.RequestUri!.AbsolutePath.EndsWith("/api/relay-events/batch"))
            {
                return new System.Net.Http.HttpResponseMessage(System.Net.HttpStatusCode.OK)
                {
                    Content = new System.Net.Http.StringContent("{\"stored\": 1, \"duplicates_ignored\": 0}", Encoding.UTF8, "application/json")
                };
            }
            return new System.Net.Http.HttpResponseMessage(System.Net.HttpStatusCode.NotFound);
        });

        using var client = new System.Net.Http.HttpClient(mockHandler);
        var sync = new TeacherApp.Services.CloudSyncService(_db, client);
        var result = await sync.SyncRelayEventsBatchAsync("http://fake-cloud", "test-token");

        Assert.IsTrue(result.Success);
        Assert.AreEqual(1, result.SyncedCount);

        var unsynced = _db.GetUnsyncedRelayEvents();
        Assert.IsEmpty(unsynced);
    }

    [TestMethod]
    public async Task TestCloudSyncService_SyncAllAsync()
    {
        _db.RecordAttendance("att_all_sync", _session.SessionId, "S001", "PRESENT", "DIRECT", -58, 0, null);
        _db.RecordRelayEvent("rl_all_sync", _session.SessionId, "msg_all", "S003", "S002", 2, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), "FORWARDED");

        var mockHandler = new MockHttpMessageHandler((req) =>
        {
            if (req.RequestUri!.AbsolutePath.EndsWith("/api/attendance/batch") ||
                req.RequestUri!.AbsolutePath.EndsWith("/api/relay-events/batch"))
            {
                return new System.Net.Http.HttpResponseMessage(System.Net.HttpStatusCode.OK)
                {
                    Content = new System.Net.Http.StringContent("{\"stored\": 1, \"duplicates_ignored\": 0}", Encoding.UTF8, "application/json")
                };
            }
            return new System.Net.Http.HttpResponseMessage(System.Net.HttpStatusCode.NotFound);
        });

        using var client = new System.Net.Http.HttpClient(mockHandler);
        var sync = new TeacherApp.Services.CloudSyncService(_db, client);
        var result = await sync.SyncAllAsync("http://fake-cloud", "test-token");

        Assert.IsTrue(result.Success);
        Assert.AreEqual(1, result.SyncedAttendance);
        Assert.AreEqual(1, result.SyncedRelay);

        Assert.IsEmpty(_db.GetUnsyncedAttendance());
        Assert.IsEmpty(_db.GetUnsyncedRelayEvents());
    }

    [TestMethod]
    public async Task TestFullEndToEndSession_AutoDemoScenario()
    {
        // 1. Teacher Authentication
        var teacher = _db.AuthenticateTeacher("T001", "teach123");
        Assert.IsNotNull(teacher);

        // 2. Class & Roster
        var classes = _db.GetTeacherClasses(teacher.TeacherId);
        Assert.IsNotEmpty(classes);
        var selectedClass = classes[0];
        var roster = _db.GetClassStudents(selectedClass.ClassId);
        Assert.IsNotEmpty(roster);

        // 3. Session Initialization & GATT Server
        var session = _db.CreateSession(selectedClass.ClassId, teacher.TeacherId, selectedClass.Subject);
        using var gattServer = new GattAttendanceServer(_db);
        await gattServer.InitializeAsync(session);

        // 4. Direct check-in for S001
        var s1 = _db.GetStudent("S001")!;
        string chNonce1 = "A1B2C3D4E5F60718A1B2C3D4E5F60718";
        gattServer.RegisterChallengeForTest(s1.StudentId, chNonce1);
        string hash1 = ComputeHash(chNonce1 + s1.DeviceSecret);
        bool s1Ok = gattServer.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, hash1, "DIRECT", -58, 0, null);
        Assert.IsTrue(s1Ok);

        // 5. Relayed check-in for S003 via S002
        var s3 = _db.GetStudent("S003")!;
        string chNonce3 = "99887766554433221100FFEEDDCCBBAA";
        gattServer.RegisterChallengeForTest(s3.StudentId, chNonce3);
        string hash3 = ComputeHash(chNonce3 + s3.DeviceSecret);
        _db.RecordRelayEvent("rl_demo_01", session.SessionId, "msg_demo_01", s3.StudentId, "S002", 2, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), "FORWARDED");
        bool s3Ok = gattServer.VerifyAndCommit(s3.StudentId, s3.RegisteredDeviceId, hash3, "RELAY", -74, 2, "Diya Patel (S002)");
        Assert.IsTrue(s3Ok);

        // 6. Teacher finalization
        int finalized = _db.FinalizeAttendance(session.SessionId, teacher.TeacherId);
        Assert.AreEqual(2, finalized);

        var records = _db.GetSessionAttendance(session.SessionId);
        Assert.HasCount(2, records);
        Assert.IsTrue(records.All(r => r.VerificationStatus == "PRESENT"));

        // 7. Cloud Sync
        var mockHandler = new MockHttpMessageHandler((req) =>
        {
            return new System.Net.Http.HttpResponseMessage(System.Net.HttpStatusCode.OK)
            {
                Content = new System.Net.Http.StringContent("{\"stored\": 2, \"duplicates_ignored\": 0}", Encoding.UTF8, "application/json")
            };
        });

        using var client = new System.Net.Http.HttpClient(mockHandler);
        var sync = new TeacherApp.Services.CloudSyncService(_db, client);
        var syncResult = await sync.SyncAllAsync("http://localhost:8000", "teacher-jwt-token");
        Assert.IsTrue(syncResult.Success);
        Assert.AreEqual(2, syncResult.SyncedAttendance);
        Assert.AreEqual(1, syncResult.SyncedRelay);
    }

    [TestMethod]
    public void TestCrossStudentResultIsolation()
    {
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(_session).GetAwaiter().GetResult();

        var s1 = _db.GetStudent("S001")!;
        var s2 = _db.GetStudent("S002")!;

        // 1. Student S002 attempts verification with bad hash and fails
        string nonce2 = "NONCE_S002_TEST_CHALLENGE_000000";
        server.RegisterChallengeForTest(s2.StudentId, nonce2);
        bool s2Ok = server.VerifyAndCommit(s2.StudentId, s2.RegisteredDeviceId, "invalid_hash_value", "DIRECT", -65, 0, null);
        Assert.IsFalse(s2Ok);
        Assert.StartsWith("REJECTED", server.GetStudentResult("S002")!);

        // 2. Student S001 attempts verification with correct hash and succeeds
        string nonce1 = "NONCE_S001_TEST_CHALLENGE_111111";
        server.RegisterChallengeForTest(s1.StudentId, nonce1);
        string validHash1 = ComputeHash(nonce1 + s1.DeviceSecret);
        bool s1Ok = server.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, validHash1, "DIRECT", -60, 0, null);
        Assert.IsTrue(s1Ok);
        Assert.AreEqual("ELIGIBLE:0x01", server.GetStudentResult("S001"));

        // 3. Verify S002's result did NOT get overwritten by S001's success
        Assert.StartsWith("REJECTED", server.GetStudentResult("S002")!, "S002's rejection must remain isolated and not overwritten by S001's success.");
    }

    [TestMethod]
    public void TestDuplicateAttendanceSubmission_Rejected()
    {
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(_session).GetAwaiter().GetResult();

        var s1 = _db.GetStudent("S001")!;
        string nonce = "FIRST_ATTEMPT_NONCE_00000000000";
        server.RegisterChallengeForTest(s1.StudentId, nonce);
        string hash = ComputeHash(nonce + s1.DeviceSecret);

        // First verification -> succeeds
        bool first = server.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, hash, "DIRECT", -60, 0, null);
        Assert.IsTrue(first);

        // Register fresh challenge for second attempt
        string nonce2 = "SECOND_ATTEMPT_NONCE_1111111111";
        server.RegisterChallengeForTest(s1.StudentId, nonce2);
        string hash2 = ComputeHash(nonce2 + s1.DeviceSecret);

        // Second verification -> rejected because attendance is already recorded for this session
        bool second = server.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, hash2, "DIRECT", -60, 0, null);
        Assert.IsFalse(second, "Duplicate attendance submission within the same session must be rejected.");
        Assert.AreEqual("REJECTED:0x02:Attendance already recorded for this session.", server.GetStudentResult("S001"));
    }

    [TestMethod]
    public void TestDuplicateAttendanceSubmission_PresentNotDowngraded()
    {
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(_session).GetAwaiter().GetResult();

        var s1 = _db.GetStudent("S001")!;
        _db.RecordAttendance("att_p1", _session.SessionId, s1.StudentId, "PRESENT", "DIRECT", -60, 0, null);

        // Attempt verification again
        string nonce = "NONCE_REVERIFY_PRESENT_STUDENT";
        server.RegisterChallengeForTest(s1.StudentId, nonce);
        string hash = ComputeHash(nonce + s1.DeviceSecret);

        bool attempt = server.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, hash, "DIRECT", -60, 0, null);
        Assert.IsFalse(attempt);

        // Confirm database status remains PRESENT
        var records = _db.GetSessionAttendance(_session.SessionId);
        var rec = records.First(r => r.StudentId == s1.StudentId);
        Assert.AreEqual("PRESENT", rec.VerificationStatus, "Finalized PRESENT attendance must never be downgraded back to ELIGIBLE.");
    }

    [TestMethod]
    public void TestDirectAttendance_ExpiredSessionTimeRejected()
    {
        // Session record whose status is ACTIVE but expiration time has passed
        long past = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - 1000;
        var expiredSession = new SessionRecord("SES_TIME_EXPIRED", "CSE-A", "T001", "Data Structures", past - 1000, past, "NONCE", "ACTIVE");
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(expiredSession).GetAwaiter().GetResult();

        var s1 = _db.GetStudent("S001")!;
        string nonce = "NONCE_EXPIRED_TIME_TEST_0000000";
        server.RegisterChallengeForTest(s1.StudentId, nonce);
        string hash = ComputeHash(nonce + s1.DeviceSecret);

        bool verified = server.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, hash, "DIRECT", -60, 0, null);
        Assert.IsFalse(verified, "Attendance must be rejected when the session expiration time has passed even if status is still ACTIVE.");
    }

    [TestMethod]
    public void TestRecordAttendance_DoesNotOverwriteExistingRecord()
    {
        bool first = _db.RecordAttendance("att_keep", _session.SessionId, "S001", "PRESENT", "MANUAL", -50, 0, null);
        Assert.IsTrue(first);

        // A second submission with the same session+student must NOT replace the PRESENT record
        bool second = _db.RecordAttendance("att_other_id", _session.SessionId, "S001", "ELIGIBLE", "RELAY", -80, 2, "S002");
        Assert.IsFalse(second, "Second attendance write for the same session+student must not succeed.");

        var records = _db.GetSessionAttendance(_session.SessionId);
        Assert.HasCount(1, records);
        Assert.AreEqual("PRESENT", records[0].VerificationStatus, "Existing record must never be downgraded or replaced.");
        Assert.AreEqual("att_keep", records[0].AttendanceId);
    }

    [TestMethod]
    public void TestRecordAttendance_RejectsInvalidStatusAndRoute()
    {
        Assert.IsFalse(_db.RecordAttendance("att_bad1", _session.SessionId, "S001", "FORGED", "DIRECT", -60, 0, null));
        Assert.IsFalse(_db.RecordAttendance("att_bad2", _session.SessionId, "S001", "ELIGIBLE", "WORMHOLE", -60, 0, null));
        Assert.IsFalse(_db.RecordAttendance("", _session.SessionId, "S001", "ELIGIBLE", "DIRECT", -60, 0, null));
        Assert.IsEmpty(_db.GetSessionAttendance(_session.SessionId));
    }

    [TestMethod]
    public void TestTeacherAuthentication_BackdoorRemoved()
    {
        // Insert teacher with distinct password
        using var conn = new Microsoft.Data.Sqlite.SqliteConnection($"Data Source={_testDbPath}");
        conn.Open();
        using (var cmd = conn.CreateCommand())
        {
            cmd.CommandText = "INSERT INTO teachers (teacher_id, name, email, password_hash) VALUES ('T999', 'Prof. Custom', 'custom@college.edu', 'custom_secure_pass');";
            cmd.ExecuteNonQuery();
        }

        // Must authenticate with actual password
        var good = _db.AuthenticateTeacher("T999", "custom_secure_pass");
        Assert.IsNotNull(good);

        // Backdoor password 'teach123' MUST be rejected for this teacher
        var backdoor = _db.AuthenticateTeacher("T999", "teach123");
        Assert.IsNull(backdoor, "Entering backdoor 'teach123' for a teacher with a different password must fail.");
    }

    [TestMethod]
    public void TestVerificationFailure_LogsAudit()
    {
        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(_session).GetAwaiter().GetResult();

        var s1 = _db.GetStudent("S001")!;
        string nonce = "AUDIT_FAILURE_TEST_NONCE_123456";
        server.RegisterChallengeForTest(s1.StudentId, nonce);

        // Submit with invalid device ID
        server.VerifyAndCommit(s1.StudentId, "DEV-WRONG-DEVICE", "dummy_hash", "DIRECT", -60, 0, null);

        // Query audit logs from db
        using var conn = new Microsoft.Data.Sqlite.SqliteConnection($"Data Source={_testDbPath}");
        conn.Open();
        using var cmd = conn.CreateCommand();
        cmd.CommandText = "SELECT COUNT(*) FROM audit_logs WHERE event_type = 'VERIFICATION_FAILED';";
        var count = (long)(cmd.ExecuteScalar() ?? 0L);
        Assert.IsGreaterThan(0L, count, "Failed verification must be logged to audit_logs table.");
    }

    [TestMethod]
    public void TestGetClassByCode_Success()
    {
        var cls = _db.GetClassByCode("CSE-A");
        Assert.IsNotNull(cls);
        Assert.AreEqual("CSE-A", cls.ClassId);
        Assert.AreEqual("CSE-A", cls.ClassCode);
        Assert.AreEqual("Data Structures", cls.Subject);
    }

    [TestMethod]
    public void TestGetClassByCode_CaseInsensitive()
    {
        var cls = _db.GetClassByCode("cse-a");
        Assert.IsNotNull(cls);
        Assert.AreEqual("CSE-A", cls.ClassId);
    }

    [TestMethod]
    public void TestGetClassByCode_NotFound()
    {
        var cls = _db.GetClassByCode("INVALID-CODE-999");
        Assert.IsNull(cls);
    }

    [TestMethod]
    public void TestAddClass_WithCustomClassCode()
    {
        bool added = _db.AddClass("CSE-B", "CSE Section B", "Algorithms", "T001", "ALGO-2026");
        Assert.IsTrue(added);

        var retrieved = _db.GetClassByCode("algo-2026");
        Assert.IsNotNull(retrieved);
        Assert.AreEqual("CSE-B", retrieved.ClassId);
        Assert.AreEqual("ALGO-2026", retrieved.ClassCode);
    }

    [TestMethod]
    public void TestJoinClassWithCode_Success()
    {
        _db.AddClass("CSE-SYS", "Systems Lab", "Operating Systems", "T001", "SYS101");

        var studentBefore = _db.GetStudent("S001")!;
        Assert.AreEqual("CSE-A", studentBefore.ClassId);

        bool joined = _db.JoinClassWithCode("S001", "SYS101");
        Assert.IsTrue(joined);

        var studentAfter = _db.GetStudent("S001")!;
        Assert.AreEqual("CSE-SYS", studentAfter.ClassId);
    }

    [TestMethod]
    public void TestJoinClassWithCode_InvalidCode()
    {
        bool joined = _db.JoinClassWithCode("S001", "NONEXISTENT_CODE");
        Assert.IsFalse(joined);

        var student = _db.GetStudent("S001")!;
        Assert.AreEqual("CSE-A", student.ClassId);
    }

    [TestMethod]
    public void TestEndToEnd_StudentJoinsClassAndVerifiesAttendance()
    {
        // 1. Create a new class with join code 'DIST-SYS'
        _db.AddClass("CSE-DIST", "Distributed Systems", "Cloud Computing", "T001", "DIST-SYS");
        var distSession = _db.CreateSession("CSE-DIST", "T001", "Cloud Computing");

        using var server = new GattAttendanceServer(_db);
        server.InitializeAsync(distSession).GetAwaiter().GetResult();

        var s2 = _db.GetStudent("S002")!;
        Assert.AreEqual("CSE-A", s2.ClassId);

        // 2. S002 tries to verify for CSE-DIST without joining -> rejected (enrollment check fails)
        string nonce = "NONCE_BEFORE_JOIN_TEST_123456";
        server.RegisterChallengeForTest(s2.StudentId, nonce);
        string hash = ComputeHash(nonce + s2.DeviceSecret);
        bool okBefore = server.VerifyAndCommit(s2.StudentId, s2.RegisteredDeviceId, hash, "DIRECT", -60, 0, null);
        Assert.IsFalse(okBefore, "Student should not be verified if not enrolled in session's class.");

        // 3. S002 joins class using code 'DIST-SYS'
        bool joined = _db.JoinClassWithCode(s2.StudentId, "DIST-SYS");
        Assert.IsTrue(joined, "Student must successfully join class with valid code.");

        // 4. S002 now verifies -> succeeds and marked ELIGIBLE!
        string freshNonce = "NONCE_AFTER_JOIN_TEST_789012";
        server.RegisterChallengeForTest(s2.StudentId, freshNonce);
        string freshHash = ComputeHash(freshNonce + s2.DeviceSecret);
        bool okAfter = server.VerifyAndCommit(s2.StudentId, s2.RegisteredDeviceId, freshHash, "DIRECT", -60, 0, null);
        Assert.IsTrue(okAfter, "Student should be verified after joining the class.");

        var attRecords = _db.GetSessionAttendance(distSession.SessionId);
        Assert.HasCount(1, attRecords);
        Assert.AreEqual("ELIGIBLE", attRecords[0].VerificationStatus);
    }

    [TestMethod]
    public void TestAddClass_DuplicateClassCodeRejected()
    {
        // 1. Adding with class code CSE-A (default class code) must fail
        bool dup1 = _db.AddClass("CSE-NEW1", "New Class 1", "Algorithms", "T001", "CSE-A");
        Assert.IsFalse(dup1, "Adding a class with an existing class code must return false.");

        // 2. Adding a new unique code succeeds
        bool ok = _db.AddClass("CSE-NEW2", "New Class 2", "Algorithms", "T001", "UNIQUE-CODE-1");
        Assert.IsTrue(ok);

        // 3. Adding again with the same code (case-insensitive) fails
        bool dup2 = _db.AddClass("CSE-NEW3", "New Class 3", "Algorithms", "T001", "unique-code-1");
        Assert.IsFalse(dup2, "Adding a duplicate class code case-insensitively must return false.");
    }

    [TestMethod]
    public void TestMultiClassEnrollment_StudentRetainedInAllEnrolledClasses()
    {
        // 1. Verify S001 starts in CSE-A
        var cseaStudentsBefore = _db.GetClassStudents("CSE-A");
        Assert.IsTrue(cseaStudentsBefore.Any(s => s.StudentId == "S001"), "S001 must be in CSE-A roster.");

        // 2. Add new class and S001 joins using code
        _db.AddClass("CSE-MULTI", "Multi Section", "Operating Systems", "T001", "MULTI-101");
        bool joined = _db.JoinClassWithCode("S001", "MULTI-101");
        Assert.IsTrue(joined, "Student must join CSE-MULTI.");

        // 3. S001 must be in CSE-MULTI roster AND STILL in CSE-A roster
        var multiStudents = _db.GetClassStudents("CSE-MULTI");
        var cseaStudentsAfter = _db.GetClassStudents("CSE-A");

        Assert.IsTrue(multiStudents.Any(s => s.StudentId == "S001"), "S001 must appear in CSE-MULTI roster.");
        Assert.IsTrue(cseaStudentsAfter.Any(s => s.StudentId == "S001"), "S001 must STILL appear in CSE-A roster after joining second class.");
        Assert.IsTrue(_db.IsStudentEnrolledInClass("S001", "CSE-A"), "S001 must be recognized as enrolled in CSE-A.");
        Assert.IsTrue(_db.IsStudentEnrolledInClass("S001", "CSE-MULTI"), "S001 must be recognized as enrolled in CSE-MULTI.");

        // 4. S001 can successfully verify in BOTH CSE-A and CSE-MULTI sessions
        var cseaSession = _db.CreateSession("CSE-A", "T001", "Data Structures");
        using var cseaServer = new GattAttendanceServer(_db);
        cseaServer.InitializeAsync(cseaSession).GetAwaiter().GetResult();

        var s1 = _db.GetStudent("S001")!;
        string nonceCsea = "NONCE_CSEA_MULTI_TEST";
        cseaServer.RegisterChallengeForTest(s1.StudentId, nonceCsea);
        string hashCsea = ComputeHash(nonceCsea + s1.DeviceSecret);
        bool cseaVerified = cseaServer.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, hashCsea, "DIRECT", -60, 0, null);
        Assert.IsTrue(cseaVerified, "S001 must verify in CSE-A session.");

        var multiSession = _db.CreateSession("CSE-MULTI", "T001", "Operating Systems");
        using var multiServer = new GattAttendanceServer(_db);
        multiServer.InitializeAsync(multiSession).GetAwaiter().GetResult();

        string nonceMulti = "NONCE_MULTI_SESSION_TEST";
        multiServer.RegisterChallengeForTest(s1.StudentId, nonceMulti);
        string hashMulti = ComputeHash(nonceMulti + s1.DeviceSecret);
        bool multiVerified = multiServer.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, hashMulti, "DIRECT", -60, 0, null);
        Assert.IsTrue(multiVerified, "S001 must verify in CSE-MULTI session as well.");
    }
}

public class MockHttpMessageHandler : System.Net.Http.HttpMessageHandler
{
    private readonly Func<System.Net.Http.HttpRequestMessage, System.Net.Http.HttpResponseMessage> _handler;
    public MockHttpMessageHandler(Func<System.Net.Http.HttpRequestMessage, System.Net.Http.HttpResponseMessage> handler) => _handler = handler;
    protected override Task<System.Net.Http.HttpResponseMessage> SendAsync(System.Net.Http.HttpRequestMessage request, CancellationToken cancellationToken)
        => Task.FromResult(_handler(request));
}

