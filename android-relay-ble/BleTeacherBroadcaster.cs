using System;
using Windows.Devices.Bluetooth.Advertisement;
using Windows.Storage.Streams;

namespace BleRelay
{
    /// <summary>
    /// Teacher Broadcaster (Original Peripheral) — Deliverable #1.
    ///
    /// Advertises:
    ///   • the shared attendance Service UUID (so student ScanFilters match)
    ///   • manufacturer data = [MAGIC B5][HOP=2][SESSION_ID 4B][RSV 2B]
    ///
    /// Byte layout is identical to PayloadCodec.kt — keep them in sync.
    /// Uses BluetoothLEAdvertisementPublisher, which works on any Windows
    /// machine with a radio that supports advertising; GattServiceProvider
    /// is NOT required for beacon-style broadcast.
    /// </summary>
    public sealed class BleTeacherBroadcaster : IDisposable
    {
        public const ushort CompanyId = 0xFFFF;      // SIG test ID — replace in production
        private const byte Magic = 0xB5;
        private const byte InitialHopCount = 2; // must match spec §13 MAX_HOPS=2 + PayloadCodec.MAX_HOPS

        private BluetoothLEAdvertisementPublisher? _publisher;
        private bool _disposed;
        private readonly Guid _serviceUuid =
            new Guid("a5e8c0de-0001-4b7d-9c11-000000000001");

        public BleTeacherBroadcaster(int sessionId)
        {
            var adv = new BluetoothLEAdvertisement
            {
                Flags = AdvertisementFlags.GeneralUnconnectableMode // beacon-style
            };

            // Keeps student ScanFilter(setServiceUuid) matching on Android,
            // and lets iOS central apps background-filter on it too.
            adv.ServiceUuids.Add(_serviceUuid);

            adv.ManufacturerData.Add(new BluetoothLEManufacturerData
            {
                CompanyId = CompanyId,
                Data = BuildPayload(sessionId, InitialHopCount)
            });

            _publisher = new BluetoothLEAdvertisementPublisher(adv);
            _publisher.StatusChanged += OnStatusChanged;
        }

        /// <summary>Begin broadcasting. Call again per new session with a fresh id.</summary>
        public void Start() => _publisher?.Start();

        public void Stop() { try { _publisher?.Stop(); } catch { } }

        /// <summary>Update hop count mid-session if you ever re-broadcast.</summary>
        public void Restart(int sessionId)
        {
            Stop();
            DisposePublisher();
            var next = new BleTeacherBroadcaster(sessionId);
            // Transfer ownership: copy advertisement into this instance is not
            // possible (publisher payload immutable), so callers should dispose
            // this instance and use the new one. Kept explicit to avoid leaks.
            next.Start();
        }

        /* Payload: [B5][HOP][S3 S2 S1 S0][00 00] — big-endian session bytes */
        private static IBuffer BuildPayload(int sessionId, byte hopCount)
        {
            using var writer = new DataWriter();
            writer.WriteByte(Magic);
            writer.WriteByte(hopCount);
            writer.WriteByte((byte)(sessionId >> 24));
            writer.WriteByte((byte)(sessionId >> 16));
            writer.WriteByte((byte)(sessionId >> 8));
            writer.WriteByte((byte)sessionId);
            writer.WriteBytes(new byte[] { 0x00, 0x00 });
            return writer.DetachBuffer();
        }

        public event Action<BluetoothLEAdvertisementPublisherStatus, BluetoothLEAdvertisementPublisherError>? StatusChanged;

        private void OnStatusChanged(BluetoothLEAdvertisementPublisher sender,
                                            BluetoothLEAdvertisementPublisherStatusChangedEventArgs args)
        {
            switch (args.Status)
            {
                case BluetoothLEAdvertisementPublisherStatus.Started:
                    Console.WriteLine("[BLE] Advertising started");
                    break;
                case BluetoothLEAdvertisementPublisherStatus.Aborted:
                    // Most common cause: another app owns the radio, or the
                    // adapter does not support peripheral advertising.
                    Console.WriteLine($"[BLE] Advertising ABORTED: {args.Error}");
                    break;
                case BluetoothLEAdvertisementPublisherStatus.Stopped:
                    Console.WriteLine("[BLE] Advertising stopped");
                    break;
                default:
                    Console.WriteLine($"[BLE] Publisher status: {args.Status} / {args.Error}");
                    break;
            }
            try { StatusChanged?.Invoke(args.Status, args.Error); } catch { }
        }

        private void DisposePublisher()
        {
            if (_publisher != null)
            {
                try { _publisher.StatusChanged -= OnStatusChanged; } catch { }
                try { _publisher.Stop(); } catch { }
                try { (_publisher as IDisposable)?.Dispose(); } catch { }
                _publisher = null;
            }
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            DisposePublisher();
            GC.SuppressFinalize(this);
        }
    }
}
