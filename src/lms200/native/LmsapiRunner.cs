// Project-owned x86 host for the original LMSAPI 1.1c DLL. See LMSAPI_EXPERIMENT.md.
// No edits to the original DLL, no separate serial owner, no outer command retries.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Threading;
using System.Web.Script.Serialization;

internal static class LmsapiRunner
{
    const string DllHash = "534f7b6fe9212f7592f409ccfafc94d7cd618cb3bb49175823e911186dad437c";
    static readonly object OutputLock = new object();
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    static bool opened;
    static IntPtr connection;
    static Timer watchdog;
    static string cancelFile;

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate void ConsoleCallback(IntPtr text);
    static readonly ConsoleCallback Callback = LibraryMessage;

    [DllImport("lmsapi.dll", CallingConvention = CallingConvention.Cdecl)]
    static extern void lmsapi_set_console_callback(ConsoleCallback callback);
    [DllImport("lmsapi.dll", CallingConvention = CallingConvention.Cdecl)]
    static extern ushort lmsapi_create_crc(byte[] data, UIntPtr count);
    [DllImport("lmsapi.dll", CallingConvention = CallingConvention.Cdecl)]
    static extern int lmsapi_serial_is_opened();
    [DllImport("lmsapi.dll", CallingConvention = CallingConvention.Cdecl)]
    static extern int lmsapi_serial_open_port(int port, int baud, byte parity, int bits, int stops);
    [DllImport("lmsapi.dll", CallingConvention = CallingConvention.Cdecl)]
    static extern int lmsapi_serial_read_data([Out] byte[] data, int count);
    [DllImport("lmsapi.dll", CallingConvention = CallingConvention.Cdecl)]
    static extern int lmsapi_serial_close();
    [DllImport("lmsapi.dll", CallingConvention = CallingConvention.Cdecl)]
    static extern IntPtr lmsapi_open_terminal(int port, int width, int resolution, int range, int intensity);
    [DllImport("lmsapi.dll", CallingConvention = CallingConvention.Cdecl)]
    static extern int lmsapi_close_terminal(IntPtr terminal);
    [DllImport("lmsapi.dll", CallingConvention = CallingConvention.Cdecl)]
    static extern int lmsapi_send_command(IntPtr terminal, byte[] payload, int length,
                                         [Out] byte[] response, int capacity, int expected);

    static void Emit(string name, params object[] fields)
    {
        var data = new Dictionary<string, object>();
        data["timestamp"] = DateTime.UtcNow.ToString("o");
        data["event"] = name;
        for (int i = 0; i < fields.Length; i += 2) data[(string)fields[i]] = fields[i + 1];
        lock (OutputLock) { Console.WriteLine(Json.Serialize(data)); Console.Out.Flush(); }
    }

    static void LibraryMessage(IntPtr text)
    {
        Emit("library_message", "message", Marshal.PtrToStringAnsi(text));
    }

    static string Hex(byte[] bytes, int count)
    {
        return BitConverter.ToString(bytes, 0, count).Replace('-', ' ');
    }

    static void CheckDll()
    {
        if (IntPtr.Size != 4) throw new InvalidOperationException("The legacy host must be x86");
        string path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "lmsapi.dll");
        using (var sha = SHA256.Create())
        {
            string actual = BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(path)))
                .Replace("-", "").ToLowerInvariant();
            if (actual != DllHash) throw new InvalidOperationException("Unreviewed LMSAPI DLL");
        }
        lmsapi_set_console_callback(Callback);
        Emit("dll_loaded", "bits", IntPtr.Size * 8, "sha256", DllHash);
    }

    static void ArmWatchdog(int seconds, string phase)
    {
        watchdog = new Timer(delegate(object state)
        {
            Emit("watchdog_timeout", "phase", phase, "seconds", seconds,
                 "note", "Terminating helper; Windows releases handles. Scanner settings may have changed.");
            Environment.Exit(124);
        }, null, seconds * 1000, Timeout.Infinite);
    }

    static void StopWatchdog()
    {
        if (watchdog != null) { watchdog.Dispose(); watchdog = null; }
    }

    static void Passive(string onFile, string completeFile)
    {
        var elapsed = Stopwatch.StartNew();
        double poweredAt = -1;
        bool completed = false;
        long total = 0;
        var buffer = new byte[4096];
        Emit("listener_ready", "port", "COM7", "nominal_baud", 9600, "tx_bytes", 0,
             "flow_control", "Inherited by unmodified LMSAPI; not forced or verified",
             "message", "Scanner is off. Awaiting separate power-on and startup confirmations.");
        while (true)
        {
            if (File.Exists(cancelFile)) throw new OperationCanceledException("Operator cancellation");
            int count = lmsapi_serial_read_data(buffer, buffer.Length);
            if (count < 0 || count > buffer.Length) throw new IOException("Invalid legacy read count");
            if (count > 0)
            {
                Emit("rx", "phase", "passive", "offset", total, "count", count,
                     "hex", Hex(buffer, count), "evidence", "Bytes/count reported by original DLL");
                total += count;
            }
            if (poweredAt < 0 && File.Exists(onFile))
            {
                poweredAt = elapsed.Elapsed.TotalSeconds;
                Emit("power_on_confirmed", "minimum_startup_seconds", 65);
            }
            if (poweredAt >= 0 && !completed && File.Exists(completeFile))
            {
                completed = true;
                Emit("startup_complete_confirmed");
            }
            if (poweredAt < 0 && elapsed.Elapsed.TotalSeconds >= 300)
                throw new TimeoutException("No power-on confirmation within 300 seconds");
            if (poweredAt >= 0 && elapsed.Elapsed.TotalSeconds - poweredAt >= 300 && !completed)
                throw new TimeoutException("No startup-complete confirmation within 300 seconds");
            if (poweredAt >= 0 && completed && elapsed.Elapsed.TotalSeconds - poweredAt >= 65)
            {
                Emit("passive_complete", "rx_bytes", total,
                     "seconds_after_power_confirmation", elapsed.Elapsed.TotalSeconds - poweredAt);
                return;
            }
            Thread.Sleep(10);
        }
    }

    static int Run(string onFile, string completeFile, string stopFile)
    {
        cancelFile = stopFile;
        string[] paths = { Path.GetFullPath(onFile), Path.GetFullPath(completeFile), Path.GetFullPath(stopFile) };
        var distinct = new HashSet<string>(paths, StringComparer.OrdinalIgnoreCase);
        if (distinct.Count != 3) throw new ArgumentException("Confirmation/cancel paths must differ");
        foreach (string path in paths)
            if (File.Exists(path) || Directory.Exists(path)) throw new ArgumentException("Markers must be fresh");
        CheckDll();
        ArmWatchdog(610, "passive");
        Emit("opening", "port", "COM7", "profile", "original LMSAPI 9600/8-N-1");
        int result = lmsapi_serial_open_port(7, 9600, 0, 8, 1);
        opened = result != 0;
        Emit("open_result", "library_return", result);
        if (!opened) return 2;
        Passive(onFile, completeFile);
        StopWatchdog();
        if (File.Exists(cancelFile)) throw new OperationCanceledException("Operator cancellation");
        ArmWatchdog(90, "active_configuration_and_status");
        Emit("connect_begin", "width_degrees", 180, "resolution_hundredths", 50,
             "range_metres", 8, "intensity", false, "library_max_tries_per_command", 10,
             "tx_bytes", null, "rx_bytes", null,
             "evidence", "Internal raw TX/RX and actual accepted write counts are not exposed by DLL");
        // Serial is already open: original open_terminal reuses its own handle.
        connection = lmsapi_open_terminal(7, 180, 50, 8, 0);
        Emit("connect_result", "connection_nonnull", connection != IntPtr.Zero);
        if (connection == IntPtr.Zero) return 3;
        if (File.Exists(cancelFile)) throw new OperationCanceledException("Operator cancellation");
        Emit("status_begin", "payload_hex", "31", "expected_response", "B1",
             "library_max_tries", 10, "outer_calls", 1);
        byte[] reply = new byte[2048];
        int length = lmsapi_send_command(connection, new byte[] { 0x31 }, 1, reply, reply.Length, 0xB1);
        bool valid = length >= 2 && length <= reply.Length && reply[0] == 0xB1;
        Emit("status_result", "library_return", length, "library_success", valid,
             "payload_hex", length > 0 && length <= reply.Length ? Hex(reply, length) : "",
             "crc_evidence", "Original DLL checks CRC internally; wire header/footer not exposed",
             "standalone_ack", "Not exposed by original DLL", "wire_frame_hex", null);
        return valid ? 0 : 4;
    }

    static int Main(string[] args)
    {
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        try
        {
            if (args.Length == 1 && args[0] == "--self-test")
            {
                CheckDll();
                byte[] request = { 2, 0, 1, 0, 0x31 };
                ushort crc = lmsapi_create_crc(request, (UIntPtr)request.Length);
                int isOpen = lmsapi_serial_is_opened();
                Emit("self_test", "crc", crc, "expected_crc", 0x1215,
                     "serial_opened", isOpen != 0, "passed", crc == 0x1215 && isOpen == 0);
                return crc == 0x1215 && isOpen == 0 ? 0 : 1;
            }
            if (args.Length != 6 || args[0] != "--run" || args[1] != "--physical-confirmed" ||
                args[2] != "--allow-legacy-configuration-and-retries")
                throw new ArgumentException("Explicit physical/configuration guards and three fresh marker paths required");
            return Run(args[3], args[4], args[5]);
        }
        catch (Exception ex)
        {
            Emit("error", "type", ex.GetType().Name, "message", ex.Message);
            return 1;
        }
        finally
        {
            // Leave watchdog armed during native cleanup in case legacy close stalls.
            if (opened)
            {
                int closed = connection != IntPtr.Zero ? lmsapi_close_terminal(connection) : lmsapi_serial_close();
                Emit("closed", "library_return", closed, "library_is_open", lmsapi_serial_is_opened() != 0,
                     "cleanup_telegram_sent_by_wrapper", false);
            }
            StopWatchdog();
            GC.KeepAlive(Callback);
        }
    }
}
