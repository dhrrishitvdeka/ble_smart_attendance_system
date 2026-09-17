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
Console.WriteLine("   BLE Smart Classroom Attendance System — Teacher Host (.NET 10)");
Console.WriteLine("   Root of Trust & Attendance Finalization Authority");
Console.WriteLine("===============================================================\n");

bool autoDemo = args.Contains("--auto-demo") || args.Contains("--test");
bool simulation = autoDemo || args.Contains("--simulate");
using var db = new AttendanceDatabase(simulation ? ":memory:" : "teacher_attendance.db");
var cloudSync = new CloudSyncService(db);

// 1. Hardware Capability Probing (spec §2)
Console.Write("[1/6] Probing Bluetooth Low Energy radio hardware... ");
if (simulation)
{
    Console.WriteLine("SKIPPED (isolated simulation; no radio or cloud access).");
}
else try
{
    var adapter = await BluetoothAdapter.GetDefaultAsync();
    if (adapter == null)
    {
        Console.WriteLine("NO RADIO DETECTED.");
        Console.WriteLine("      Workstation has no active Bluetooth radio.");
    }
    else
    {
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
if (args.Contains("--login"))
{
    var loginIndex = Array.IndexOf(args, "--login");
    if (loginIndex + 2 >= args.Length)
    {
        Console.WriteLine("[ERROR] --login requires a teacher ID and password.");
        Environment.ExitCode = 1;
        return;
    }
    teacherId = args[loginIndex + 1];
    teacherPassword = args[loginIndex + 2];
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
Console.WriteLine($"      Selected Class: {selectedClass.ClassId} — {selectedClass.Subject} (Class Code: {selectedClass.ClassCode})");
Console.WriteLine($"      Enrolled Students: {roster.Count}");

// 4. Session Initialization & GATT Server (spec §3/§4)
Console.WriteLine("\n[4/6] Initializing Attendance Session");
var session = db.CreateSession(selectedClass.ClassId, teacher.TeacherId, selectedClass.Subject);
Console.WriteLine($"      Session ID:    {session.SessionId}");
Console.WriteLine($"      Random Nonce:  {session.RandomNonce}");
Console.WriteLine($"      Valid For:     10 minutes (Expires: {DateTimeOffset.FromUnixTimeMilliseconds(session.ExpirationTime):HH:mm:ss})");

using var gattServer = new GattAttendanceServer(db);
bool gattReady = await gattServer.InitializeAsync(session, enableBluetooth: !simulation);
if (gattReady)
{
    gattServer.StartAdvertising();
    Console.WriteLine("      Windows BLE GATT Server: RUNNING & ADVERTISING (Connectable)");
}
else
{
    var reason = !string.IsNullOrWhiteSpace(gattServer.InitializationError) ? gattServer.InitializationError : "Radio peripheral mode unavailable on this workstation.";
    Console.WriteLine($"      Windows BLE GATT Server: {reason}");
    Console.WriteLine(simulation
        ? "      Explicit simulation active; attendance is isolated in memory."
        : "      BLE verification unavailable. Manual commands remain available; simulation requires --simulate.");
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

    Console.WriteLine("\n[SIMULATION] Cloud sync skipped. Records exist only in memory.");
    if (finalized != 2)
    {
        Console.WriteLine("[ERROR] Simulation did not finalize the expected two records.");
        Environment.ExitCode = 1;
        return;
    }

    Console.WriteLine("\n===============================================================");
    Console.WriteLine("   Automated Verification Completed Successfully.");
    Console.WriteLine("===============================================================");
    return;
}

Console.WriteLine("\nCommands: [v] Verify Student Demo | [m] Manual Override | [j] Enroll Student with Code | [c] Show Class Code | [f] Finalize Session | [s] Cloud Sync | [q] Quit");

bool running = true;
while (running)
{
    Console.Write("\nTeacherApp> ");
    var input = Console.ReadLine()?.Trim().ToLower();
    switch (input)
    {
        case "v":
            if (!simulation)
            {
                Console.WriteLine("Demo verification requires --simulate; no live attendance was changed.");
                break;
            }
            // Demo verification
            roster = db.GetClassStudents(selectedClass.ClassId);
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
            bool recorded = db.RecordAttendance($"att_{Guid.NewGuid():N}", session.SessionId, sid, "PRESENT", "MANUAL", null, 0, null);
            Console.WriteLine(recorded
                ? $"Student {sid} manually marked PRESENT."
                : $"Attendance for {sid} was not changed. Check enrollment, existing attendance, and session status.");
            RenderRosterTable(db, selectedClass.ClassId, session.SessionId);
            break;

        case "j":
            Console.Write("Enter Student ID to enroll: ");
            var joinSid = Console.ReadLine()?.Trim().ToUpper() ?? "";
            Console.Write($"Enter Class Code (press Enter for '{selectedClass.ClassCode}'): ");
            var joinCodeInput = Console.ReadLine()?.Trim();
            var joinCode = string.IsNullOrWhiteSpace(joinCodeInput) ? selectedClass.ClassCode : joinCodeInput;
            bool joinSuccess = db.JoinClassWithCode(joinSid, joinCode);
            if (joinSuccess)
            {
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine($"[ENROLLED] Student {joinSid} successfully joined class using code '{joinCode}'.");
                Console.ResetColor();
                roster = db.GetClassStudents(selectedClass.ClassId);
            }
            else
            {
                Console.ForegroundColor = ConsoleColor.Yellow;
                Console.WriteLine($"[FAILED] Could not enroll Student {joinSid}. Verify student exists and code is valid.");
                Console.ResetColor();
            }
            RenderRosterTable(db, selectedClass.ClassId, session.SessionId);
            break;

        case "c":
            Console.WriteLine($"\nActive Class: {selectedClass.ClassId} ({selectedClass.Subject})");
            Console.WriteLine($"Class Code for Students: {selectedClass.ClassCode}");
            break;

        case "f":
            int num = db.FinalizeAttendance(session.SessionId, teacher.TeacherId);
            Console.ForegroundColor = ConsoleColor.Cyan;
            Console.WriteLine($"\n[FINALIZED] {num} student(s) marked PRESENT. Session sealed.");
            Console.ResetColor();
            RenderRosterTable(db, selectedClass.ClassId, session.SessionId);
            break;

        case "s":
            if (simulation)
            {
                Console.WriteLine("Cloud sync disabled for isolated simulation.");
                break;
            }
            Console.WriteLine("Syncing with cloud backend at http://localhost:8000...");
            var token = await cloudSync.LoginToCloudAsync("http://localhost:8000", teacher.TeacherId, teacherPassword);
            var res = await cloudSync.SyncAllAsync("http://localhost:8000", token);
            Console.WriteLine($"Result: {res.Message}");
            break;

        case null:
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

