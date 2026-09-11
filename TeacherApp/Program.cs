// Minimal teacher console stub (spec §2/§4). Full GATT server lives in
// android-relay-ble/BleTeacherBroadcaster.cs; this host wires session +
// SQLite + capability probing. See shared/ble_config.json for UUIDs.
using System.Security.Cryptography;

var sessionId = Convert.ToHexString(RandomNumberGenerator.GetBytes(4));
var nonce = Convert.ToHexString(RandomNumberGenerator.GetBytes(8));
Console.WriteLine($"BLE Attendance TeacherApp (.NET 8)");
Console.WriteLine($"Session: {sessionId} Nonce: {nonce} Expires: +10 min");
Console.WriteLine("NOTE: BLE peripheral mode requires a radio with advertising support.");
Console.WriteLine("Run the browser demo: start-webapp.bat. Cloud sync: Backend/main.py.");
