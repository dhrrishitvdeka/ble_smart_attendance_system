using System;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using Windows.Devices.Bluetooth;
using TeacherApp.BLE;
using TeacherApp.Database;
using TeacherApp.Services;

Console.OutputEncoding = Encoding.UTF8;
Console.WriteLine("===============================================================");
Console.WriteLine("   BLE Smart Classroom Attendance System — Teacher Host (.NET 8)");
Console.WriteLine("   Root of Trust & Attendance Finalization Authority");
Console.WriteLine("===============================================================\n");

using var db = new AttendanceDatabase();
var cloudSync = new CloudSyncService(db);

// 1. Hardware Capability Probing (spec §2)
Console.Write("[1/6] Probing Bluetooth Low Energy radio hardware... ");
bool bleSupported = false;
try
{
    var adapter = await BluetoothAdapter.GetDefaultAsync();
    if (adapter == null)
    {
        Console.WriteLine("NO RADIO DETECTED.");
        Console.WriteLine("      Workstation has no active Bluetooth radio.");
    }
    else
    {
        bleSupported = adapter.IsPeripheralRoleSupported;
        Console.WriteLine($"RADIO FOUND: {adapter.DeviceId}");
        Console.WriteLine($"      Peripheral Mode Supported: {adapter.IsPeripheralRoleSupported}");
        Console.WriteLine($"      Central Mode Supported:    {adapter.IsCentralRoleSupported}");
    }
}
catch (Exception ex)
{
    Console.WriteLine($"PROBE FAILED: {ex.Message}");
}

// 2. Teacher Authentication (spec §1)
Console.WriteLine("\n[2/6] Teacher Authentication");
string teacherId = "T001";
string teacherPassword = "teach123";
if (args.Contains("--login") && args.Length > 2)
{
    teacherId = args[1];
    teacherPassword = args[2];
}

var teacher = db.AuthenticateTeacher(teacherId, teacherPassword);
if (teacher == null)
{
    Console.WriteLine($"[ERROR] Authentication failed for Teacher ID '{teacherId}'.");
    return;
}
Console.WriteLine($"      Authenticated as: {teacher.Name} ({teacher.TeacherId})");

// 3. Class Selection (spec §2)
Console.WriteLine("\n[3/6] Class Selection & Roster Loading");
var classes = db.GetTeacherClasses(teacher.TeacherId);
if (classes.Count == 0)
{
    Console.WriteLine("[ERROR] No classes assigned to this teacher.");
    return;
}
var selectedClass = classes[0];
var roster = db.GetClassStudents(selectedClass.ClassId);
Console.WriteLine($"      Selected Class: {selectedClass.ClassId} — {selectedClass.Subject}");
Console.WriteLine($"      Enrolled Students: {roster.Count}");

// 4. Session Initialization & GATT Server (spec §3/§4)
Console.WriteLine("\n[4/6] Initializing Attendance Session");
var session = db.CreateSession(selectedClass.ClassId, teacher.TeacherId, selectedClass.Subject);
Console.WriteLine($"      Session ID:    {session.SessionId}");
Console.WriteLine($"      Random Nonce:  {session.RandomNonce}");
Console.WriteLine($"      Valid For:     10 minutes (Expires: {DateTimeOffset.FromUnixTimeMilliseconds(session.ExpirationTime):HH:mm:ss})");

using var gattServer = new GattAttendanceServer(db);
bool gattReady = await gattServer.InitializeAsync(session);
if (gattReady)
{
    gattServer.StartAdvertising();
    Console.WriteLine("      Windows BLE GATT Server: RUNNING & ADVERTISING (Connectable)");
}
else
{
    var reason = !string.IsNullOrWhiteSpace(gattServer.InitializationError) ? gattServer.InitializationError : "Radio peripheral mode unavailable on this workstation.";
    Console.WriteLine($"      Windows BLE GATT Server: {reason}");
    Console.WriteLine("      Running in Simulated / Hybrid Attendance Verification Mode.");
}

// 5. Verification Event Handlers (spec §7/§8/§11)
gattServer.OnStudentVerified += (studentId, route, rssi) =>
{
    Console.ForegroundColor = ConsoleColor.Green;
    Console.WriteLine($"\n[VERIFIED] Student {studentId} verified via {route} (RSSI: {rssi}) -> Status: ELIGIBLE");
    Console.ResetColor();
    RenderRosterTable(db, selectedClass.ClassId, session.SessionId);
};

gattServer.OnVerificationFailed += (studentId, reason) =>
{
    Console.ForegroundColor = ConsoleColor.Yellow;
    Console.WriteLine($"\n[REJECTED] Student {studentId} verification failed: {reason}");
    Console.ResetColor();
};

// 6. Interactive / Automated Session Loop
Console.WriteLine("\n[5/6] Live Attendance Session Active");
RenderRosterTable(db, selectedClass.ClassId, session.SessionId);

bool autoDemo = args.Contains("--auto-demo") || args.Contains("--test");

if (autoDemo)
{
    Console.WriteLine("\n--- Executing Automated Verification Test Scenario ---");
    // Simulate student S001 direct check-in
    var s1 = db.GetStudent("S001");
    if (s1 != null)
    {
        string chNonce = Convert.ToHexString(RandomNumberGenerator.GetBytes(16));
        gattServer.RegisterChallengeForTest(s1.StudentId, chNonce);
        using var sha = SHA256.Create();
        string responseHash = Convert.ToHexString(sha.ComputeHash(Encoding.UTF8.GetBytes(chNonce + s1.DeviceSecret))).ToLower();
        Console.WriteLine($"Simulating Student S001 (Aarav Kumar) direct submission with hardware secret...");
        gattServer.VerifyAndCommit(s1.StudentId, s1.RegisteredDeviceId, responseHash, "DIRECT", -58, 0, null);
    }

    // Simulate student S003 relayed check-in via S002
    var s3 = db.GetStudent("S003");
    if (s3 != null)
    {
        string chNonce = Convert.ToHexString(RandomNumberGenerator.GetBytes(16));
        gattServer.RegisterChallengeForTest(s3.StudentId, chNonce);
        using var sha = SHA256.Create();
        string responseHash = Convert.ToHexString(sha.ComputeHash(Encoding.UTF8.GetBytes(chNonce + s3.DeviceSecret))).ToLower();
        Console.WriteLine($"Simulating Student S003 (Rohan Verma) 2-hop mesh relay via Student S002...");
        db.RecordRelayEvent($"rl_{Guid.NewGuid():N}", session.SessionId, $"msg_{Guid.NewGuid():N}", s3.StudentId, "S002", 2, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), "FORWARDED");
        gattServer.VerifyAndCommit(s3.StudentId, s3.RegisteredDeviceId, responseHash, "RELAY", -74, 2, "Diya Patel (S002)");
    }

    RenderRosterTable(db, selectedClass.ClassId, session.SessionId);

    // Finalize
    Console.WriteLine("\nFinalizing Attendance (ELIGIBLE -> PRESENT)...");
    int finalized = db.FinalizeAttendance(session.SessionId, teacher.TeacherId);
    Console.WriteLine($"Finalized {finalized} attendance records.");
    RenderRosterTable(db, selectedClass.ClassId, session.SessionId);

    // Authenticated Cloud Sync
    Console.WriteLine("\nAttempting Authenticated Cloud Sync to http://localhost:8000...");
    var cloudToken = await cloudSync.LoginToCloudAsync("http://localhost:8000", teacher.TeacherId, teacherPassword);
    var (ok, attCount, relayCount, msg) = await cloudSync.SyncAllAsync("http://localhost:8000", cloudToken);
    Console.WriteLine($"Cloud Sync Result: {msg}");

    Console.WriteLine("\n===============================================================");
    Console.WriteLine("   Automated Verification Completed Successfully.");
    Console.WriteLine("===============================================================");
    return;
}

Console.WriteLine("\nCommands: [v] Verify Student Demo | [m] Manual Override | [f] Finalize Session | [s] Cloud Sync | [q] Quit");

bool running = true;
while (running)
{
    Console.Write("\nTeacherApp> ");
    var input = Console.ReadLine()?.Trim().ToLower();
    switch (input)
    {
        case "v":
            // Demo verification
            var candidate = roster.FirstOrDefault(s => !db.GetSessionAttendance(session.SessionId).Any(a => a.StudentId == s.StudentId));
            if (candidate != null)
            {
                db.RecordAttendance($"att_{Guid.NewGuid():N}", session.SessionId, candidate.StudentId, "ELIGIBLE", "DIRECT", -62, 0, null);
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine($"[DEMO] Student {candidate.StudentId} ({candidate.Name}) verified and marked ELIGIBLE.");
                Console.ResetColor();
            }
            else
            {
                Console.WriteLine("All students in roster are already recorded.");
            }
            RenderRosterTable(db, selectedClass.ClassId, session.SessionId);
            break;

        case "m":
            Console.Write("Enter Student ID to mark PRESENT: ");
            var sid = Console.ReadLine()?.Trim().ToUpper() ?? "";
            db.RecordAttendance($"att_{Guid.NewGuid():N}", session.SessionId, sid, "PRESENT", "MANUAL", -50, 0, null);
            Console.WriteLine($"Student {sid} manually marked PRESENT.");
            RenderRosterTable(db, selectedClass.ClassId, session.SessionId);
            break;

        case "f":
            int num = db.FinalizeAttendance(session.SessionId, teacher.TeacherId);
            Console.ForegroundColor = ConsoleColor.Cyan;
            Console.WriteLine($"\n[FINALIZED] {num} student(s) marked PRESENT. Session sealed.");
            Console.ResetColor();
            RenderRosterTable(db, selectedClass.ClassId, session.SessionId);
            break;

        case "s":
            Console.WriteLine("Syncing with cloud backend at http://localhost:8000...");
            var token = await cloudSync.LoginToCloudAsync("http://localhost:8000", teacher.TeacherId, teacherPassword);
            var res = await cloudSync.SyncAllAsync("http://localhost:8000", token);
            Console.WriteLine($"Result: {res.Message}");
            break;

        case "q":
            running = false;
            break;

        default:
            RenderRosterTable(db, selectedClass.ClassId, session.SessionId);
            break;
    }
}

gattServer.StopAdvertising();
Console.WriteLine("Session closed. TeacherApp exited cleanly.");

static void RenderRosterTable(AttendanceDatabase db, string classId, string sessionId)
{
    var students = db.GetClassStudents(classId);
    var attendance = db.GetSessionAttendance(sessionId);

    Console.WriteLine("\n+------------+----------------------+---------------+--------+----------+--------------+");
    Console.WriteLine("| Student ID | Name                 | Status        | Route  | RSSI     | Hops / Via   |");
    Console.WriteLine("+------------+----------------------+---------------+--------+----------+--------------+");

    foreach (var st in students)
    {
        var att = attendance.FirstOrDefault(a => a.StudentId == st.StudentId);
        string status = att?.VerificationStatus ?? "NOT VERIFIED";
        string route = att?.RouteType ?? "--";
        string rssi = att?.RssiEvidence != null ? $"{att.RssiEvidence} dBm" : "--";
        string hops = att?.RouteType == "RELAY" ? $"{att.HopCount}h ({att.ViaStudent?.Split(' ').FirstOrDefault()})" : "--";

        Console.WriteLine($"| {st.StudentId,-10} | {st.Name,-20} | {status,-13} | {route,-6} | {rssi,-8} | {hops,-12} |");
    }
    Console.WriteLine("+------------+----------------------+---------------+--------+----------+--------------+");
}

