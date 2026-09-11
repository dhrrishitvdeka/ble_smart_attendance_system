using System;
using System.Collections.Concurrent;
using System.Runtime.InteropServices.WindowsRuntime;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using Windows.Devices.Bluetooth;
using Windows.Devices.Bluetooth.GenericAttributeProfile;
using Windows.Storage.Streams;
using TeacherApp.Database;

namespace TeacherApp.BLE;

public class GattAttendanceServer : IDisposable
{
    private readonly AttendanceDatabase _db;
    private SessionRecord? _currentSession;
    private GattServiceProvider? _serviceProvider;
    private GattLocalCharacteristic? _sessionChar;
    private GattLocalCharacteristic? _requestChar;
    private GattLocalCharacteristic? _challengeChar;
    private GattLocalCharacteristic? _responseChar;
    private GattLocalCharacteristic? _resultChar;
    private GattLocalCharacteristic? _relayChar;

    private readonly ConcurrentDictionary<string, (string ChallengeNonce, long ExpiresAt)> _activeChallenges = new();
    private readonly HashSet<string> _seenRequestIds = new();
    private string? _lastChallengeNonce;

    public event Action<string, string, string>? OnStudentVerified;
    public event Action<string, string>? OnVerificationFailed;

    public bool IsAdvertising { get; private set; }
    public bool PeripheralRoleSupported { get; private set; }
    public string? InitializationError { get; private set; }

    public GattAttendanceServer(AttendanceDatabase db)
    {
        _db = db;
    }

    public async Task<bool> InitializeAsync(SessionRecord session)
    {
        _currentSession = session;
        try
        {
            var adapter = await BluetoothAdapter.GetDefaultAsync();
            if (adapter == null)
            {
                PeripheralRoleSupported = false;
                InitializationError = "No Bluetooth adapter detected.";
                _db.LogAudit("BLE_RADIO_UNAVAILABLE", InitializationError);
                return false;
            }
            if (!adapter.IsPeripheralRoleSupported)
            {
                PeripheralRoleSupported = false;
                InitializationError = "Adapter does not support BLE Peripheral role.";
                _db.LogAudit("BLE_PERIPHERAL_UNSUPPORTED", InitializationError);
                return false;
            }

            PeripheralRoleSupported = true;
            var serviceUuid = new Guid(BleProtocol.ServiceUuid);
            var result = await GattServiceProvider.CreateAsync(serviceUuid);
            if (result.Error != BluetoothError.Success)
            {
                InitializationError = $"GattServiceProvider.CreateAsync failed: {result.Error}";
                _db.LogAudit("GATT_SERVICE_ERROR", InitializationError);
                return false;
            }

            _serviceProvider = result.ServiceProvider;

            // 1. Session Characteristic (Read)
            var sessionParams = new GattLocalCharacteristicParameters
            {
                CharacteristicProperties = GattCharacteristicProperties.Read,
                ReadProtectionLevel = GattProtectionLevel.Plain
            };
            var sessionResult = await _serviceProvider.Service.CreateCharacteristicAsync(
                new Guid(BleProtocol.SessionCharacteristic), sessionParams);
            if (sessionResult.Error == BluetoothError.Success)
            {
                _sessionChar = sessionResult.Characteristic;
                _sessionChar.ReadRequested += OnSessionReadRequested;
            }

            // 2. Request Characteristic (Write)
            var requestParams = new GattLocalCharacteristicParameters
            {
                CharacteristicProperties = GattCharacteristicProperties.Write | GattCharacteristicProperties.WriteWithoutResponse,
                WriteProtectionLevel = GattProtectionLevel.Plain
            };
            var reqResult = await _serviceProvider.Service.CreateCharacteristicAsync(
                new Guid(BleProtocol.RequestCharacteristic), requestParams);
            if (reqResult.Error == BluetoothError.Success)
            {
                _requestChar = reqResult.Characteristic;
                _requestChar.WriteRequested += OnRequestWriteRequested;
            }

            // 3. Challenge Characteristic (Read / Indicate)
            var challengeParams = new GattLocalCharacteristicParameters
            {
                CharacteristicProperties = GattCharacteristicProperties.Read | GattCharacteristicProperties.Indicate,
                ReadProtectionLevel = GattProtectionLevel.Plain
            };
            var challengeResult = await _serviceProvider.Service.CreateCharacteristicAsync(
                new Guid(BleProtocol.ChallengeCharacteristic), challengeParams);
            if (challengeResult.Error == BluetoothError.Success)
            {
                _challengeChar = challengeResult.Characteristic;
                _challengeChar.ReadRequested += OnChallengeReadRequested;
            }

            // 4. Response Characteristic (Write)
            var responseParams = new GattLocalCharacteristicParameters
            {
                CharacteristicProperties = GattCharacteristicProperties.Write,
                WriteProtectionLevel = GattProtectionLevel.Plain
            };
            var respResult = await _serviceProvider.Service.CreateCharacteristicAsync(
                new Guid(BleProtocol.ResponseCharacteristic), responseParams);
            if (respResult.Error == BluetoothError.Success)
            {
                _responseChar = respResult.Characteristic;
                _responseChar.WriteRequested += OnResponseWriteRequested;
            }

            // 5. Result Characteristic (Read / Notify)
            var resultParams = new GattLocalCharacteristicParameters
            {
                CharacteristicProperties = GattCharacteristicProperties.Read | GattCharacteristicProperties.Notify,
                ReadProtectionLevel = GattProtectionLevel.Plain
            };
            var resResult = await _serviceProvider.Service.CreateCharacteristicAsync(
                new Guid(BleProtocol.ResultCharacteristic), resultParams);
            if (resResult.Error == BluetoothError.Success)
            {
                _resultChar = resResult.Characteristic;
            }

            // 6. Relay Characteristic (Write)
            var relayParams = new GattLocalCharacteristicParameters
            {
                CharacteristicProperties = GattCharacteristicProperties.Write,
                WriteProtectionLevel = GattProtectionLevel.Plain
            };
            var relayResult = await _serviceProvider.Service.CreateCharacteristicAsync(
                new Guid(BleProtocol.RelayCharacteristic), relayParams);
            if (relayResult.Error == BluetoothError.Success)
            {
                _relayChar = relayResult.Characteristic;
                _relayChar.WriteRequested += OnRelayWriteRequested;
            }

            return true;
        }
        catch (Exception ex)
        {
            InitializationError = $"GattServer exception: {ex.Message}";
            _db.LogAudit("GATT_INIT_EXCEPTION", ex.Message);
            PeripheralRoleSupported = false;
            return false;
        }
    }

    public void StartAdvertising()
    {
        if (_serviceProvider == null) return;
        var advParams = new GattServiceProviderAdvertisingParameters
        {
            IsConnectable = true,
            IsDiscoverable = true
        };
        _serviceProvider.StartAdvertising(advParams);
        IsAdvertising = true;
        _db.LogAudit("BLE_ADV_STARTED", $"Connectable GATT advertising started for session {_currentSession?.SessionId}");
    }

    public void StopAdvertising()
    {
        if (_serviceProvider != null && IsAdvertising)
        {
            _serviceProvider.StopAdvertising();
            IsAdvertising = false;
            _db.LogAudit("BLE_ADV_STOPPED", "GATT advertising stopped.");
        }
    }

    private async void OnSessionReadRequested(GattLocalCharacteristic sender, GattReadRequestedEventArgs args)
    {
        using var deferral = args.GetDeferral();
        var request = await args.GetRequestAsync();
        if (_currentSession == null)
        {
            request.RespondWithProtocolError(GattProtocolError.UnlikelyError);
            return;
        }

        var data = $"{_currentSession.SessionId}:{_currentSession.RandomNonce}";
        using var writer = new DataWriter();
        writer.WriteString(data);
        request.RespondWithValue(writer.DetachBuffer());
    }

    private async void OnChallengeReadRequested(GattLocalCharacteristic sender, GattReadRequestedEventArgs args)
    {
        using var deferral = args.GetDeferral();
        var request = await args.GetRequestAsync();

        // Return the active challenge nonce generated for the requesting client
        var nonce = _lastChallengeNonce ?? Convert.ToHexString(RandomNumberGenerator.GetBytes(16));
        using var writer = new DataWriter();
        writer.WriteString(nonce);
        request.RespondWithValue(writer.DetachBuffer());
    }

    private async void OnRequestWriteRequested(GattLocalCharacteristic sender, GattWriteRequestedEventArgs args)
    {
        using var deferral = args.GetDeferral();
        var request = await args.GetRequestAsync();
        using var reader = DataReader.FromBuffer(request.Value);
        var message = reader.ReadString(reader.UnconsumedBufferLength);

        // Format: student_id|registered_device_id|route_type
        var parts = message.Split('|');
        if (parts.Length >= 2)
        {
            var studentId = parts[0].Trim().ToUpper();
            var deviceId = parts[1].Trim();
            var challengeNonce = Convert.ToHexString(RandomNumberGenerator.GetBytes(16));
            _activeChallenges[studentId] = (challengeNonce, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 30000);
            _lastChallengeNonce = challengeNonce;
        }

        if (request.Option == GattWriteOption.WriteWithResponse)
        {
            request.Respond();
        }
    }

    private async void OnResponseWriteRequested(GattLocalCharacteristic sender, GattWriteRequestedEventArgs args)
    {
        using var deferral = args.GetDeferral();
        var request = await args.GetRequestAsync();
        using var reader = DataReader.FromBuffer(request.Value);
        var message = reader.ReadString(reader.UnconsumedBufferLength);

        // Format: student_id|device_id|response_hash|rssi
        var parts = message.Split('|');
        if (parts.Length >= 3 && _currentSession != null)
        {
            var studentId = parts[0].Trim().ToUpper();
            var deviceId = parts[1].Trim();
            var responseHash = parts[2].Trim().ToLower();
            int rssi = -65;
            if (parts.Length >= 4) int.TryParse(parts[3], out rssi);

            VerifyAndCommit(studentId, deviceId, responseHash, "DIRECT", rssi, 0, null);
        }

        if (request.Option == GattWriteOption.WriteWithResponse)
        {
            request.Respond();
        }
    }

    private async void OnRelayWriteRequested(GattLocalCharacteristic sender, GattWriteRequestedEventArgs args)
    {
        using var deferral = args.GetDeferral();
        var request = await args.GetRequestAsync();
        using var reader = DataReader.FromBuffer(request.Value);
        var message = reader.ReadString(reader.UnconsumedBufferLength);

        // Format: RELAY|student_id|device_id|response_hash|hop_count|via_student|rssi
        var parts = message.Split('|');
        if (parts.Length >= 6 && parts[0] == "RELAY" && _currentSession != null)
        {
            var studentId = parts[1].Trim().ToUpper();
            var deviceId = parts[2].Trim();
            var responseHash = parts[3].Trim().ToLower();
            int.TryParse(parts[4], out int hopCount);
            var viaStudent = parts[5].Trim();
            int rssi = -75;
            if (parts.Length >= 7) int.TryParse(parts[6], out rssi);

            VerifyAndCommit(studentId, deviceId, responseHash, "RELAY", rssi, hopCount, viaStudent);
        }

        if (request.Option == GattWriteOption.WriteWithResponse)
        {
            request.Respond();
        }
    }

    public bool VerifyAndCommit(string studentId, string deviceId, string responseHash, string routeType, int rssi, int hopCount, string? viaStudent)
    {
        if (_currentSession == null || _currentSession.Status != "ACTIVE")
        {
            OnVerificationFailed?.Invoke(studentId, "Session not active.");
            return false;
        }

        var student = _db.GetStudent(studentId);
        if (student == null)
        {
            OnVerificationFailed?.Invoke(studentId, "Student not found in roster.");
            return false;
        }

        if (student.ClassId != _currentSession.ClassId)
        {
            OnVerificationFailed?.Invoke(studentId, "Student not enrolled in this session's class.");
            return false;
        }

        if (student.RegisteredDeviceId != deviceId)
        {
            OnVerificationFailed?.Invoke(studentId, "Unregistered hardware device.");
            return false;
        }

        if (rssi <= -90)
        {
            OnVerificationFailed?.Invoke(studentId, $"Proximity below floor threshold ({rssi} dBm).");
            return false;
        }

        if (routeType == "RELAY" && (hopCount < 1 || hopCount > BleProtocol.MaxHops))
        {
            OnVerificationFailed?.Invoke(studentId, $"Hop limit exceeded ({hopCount} > {BleProtocol.MaxHops}).");
            return false;
        }

        // Cryptographic check: calculate SHA256(challenge + secret)
        if (!_activeChallenges.TryGetValue(studentId, out var ch))
        {
            OnVerificationFailed?.Invoke(studentId, "No active challenge found for student. Fresh challenge required.");
            return false;
        }

        if (DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() > ch.ExpiresAt)
        {
            _activeChallenges.TryRemove(studentId, out _);
            OnVerificationFailed?.Invoke(studentId, "Challenge expired.");
            return false;
        }

        var expected = ComputeSha256(ch.ChallengeNonce + student.DeviceSecret);
        if (!string.Equals(expected, responseHash, StringComparison.OrdinalIgnoreCase))
        {
            _activeChallenges.TryRemove(studentId, out _);
            OnVerificationFailed?.Invoke(studentId, "Cryptographic response mismatch.");
            return false;
        }

        // Consume single-use challenge to prevent replay attacks
        _activeChallenges.TryRemove(studentId, out _);

        // All checks passed -> mark ELIGIBLE
        var attId = $"att_{Guid.NewGuid():N}";
        bool ok = _db.RecordAttendance(attId, _currentSession.SessionId, studentId, "ELIGIBLE", routeType, rssi, hopCount, viaStudent);
        if (ok)
        {
            OnStudentVerified?.Invoke(studentId, routeType, $"{rssi} dBm");
            return true;
        }
        return false;
    }

    public void RegisterChallengeForTest(string studentId, string nonce, int ttlMs = 30000)
    {
        _activeChallenges[studentId.Trim().ToUpper()] = (nonce, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + ttlMs);
        _lastChallengeNonce = nonce;
    }

    private static string ComputeSha256(string raw)
    {
        using var sha = SHA256.Create();
        var bytes = sha.ComputeHash(Encoding.UTF8.GetBytes(raw));
        return Convert.ToHexString(bytes).ToLower();
    }

    public void Dispose()
    {
        StopAdvertising();
        _serviceProvider = null;
    }
}
