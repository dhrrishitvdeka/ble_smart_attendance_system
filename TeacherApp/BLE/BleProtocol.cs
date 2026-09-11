// Shared BLE identifiers — must match shared/ble_config.json + webapp/core.js.
namespace TeacherApp.BLE;

public static class BleProtocol
{
    public const string ServiceUuid = "a5e8c0de-0001-4b7d-9c11-000000000001";
    public const string SessionCharacteristic = "a5e8c0de-0002-4b7d-9c11-000000000002";
    public const string RequestCharacteristic = "a5e8c0de-0003-4b7d-9c11-000000000003";
    public const string ChallengeCharacteristic = "a5e8c0de-0004-4b7d-9c11-000000000004";
    public const string ResponseCharacteristic = "a5e8c0de-0005-4b7d-9c11-000000000005";
    public const string ResultCharacteristic = "a5e8c0de-0006-4b7d-9c11-000000000006";
    public const string RelayCharacteristic = "a5e8c0de-0007-4b7d-9c11-000000000007";
    public const int MaxHops = 2;
}
