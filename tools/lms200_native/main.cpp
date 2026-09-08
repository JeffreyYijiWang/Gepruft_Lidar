#include "protocol.hpp"
#include "sequence.hpp"
#include "win_serial.hpp"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <thread>

namespace {
using namespace lmsnative;
using Clock = std::chrono::steady_clock;
using namespace std::chrono_literals;
std::atomic<bool> cancelled{false};
BOOL WINAPI console_control(DWORD signal) {
    if (signal == CTRL_C_EVENT || signal == CTRL_BREAK_EVENT) {
        cancelled.store(true);
        return TRUE;
    }
    return FALSE; // Forced window/process termination cannot guarantee cleanup.
}
std::string quote(const std::string& value) {
    std::ostringstream out;
    out << '"';
    constexpr char digits[] = "0123456789abcdef";
    for (const unsigned char c : value) {
        if (c == '"' || c == '\\') out << '\\' << static_cast<char>(c);
        else if (c < 32) out << "\\u00" << digits[c >> 4] << digits[c & 15];
        else out << static_cast<char>(c);
    }
    out << '"';
    return out.str();
}
const char* boolean(bool value) { return value ? "true" : "false"; }
std::string utc(bool filename = false) {
    SYSTEMTIME now{};
    GetSystemTime(&now);
    std::ostringstream out;
    out << std::setfill('0') << std::setw(4) << now.wYear;
    const auto separator = filename ? "" : "-";
    out << separator << std::setw(2) << now.wMonth << separator << std::setw(2) << now.wDay
        << 'T' << std::setw(2) << now.wHour << (filename ? "" : ":")
        << std::setw(2) << now.wMinute << (filename ? "" : ":") << std::setw(2) << now.wSecond;
    if (!filename) out << '.' << std::setw(3) << now.wMilliseconds;
    return out.str() + 'Z';
}

class Log {
public:
    explicit Log(const std::filesystem::path& directory) : root(directory) {
        if (!std::filesystem::create_directories(root))
            throw std::runtime_error("Output directory already exists; refusing to overwrite evidence");
        raw.open(root / "rx.bin", std::ios::binary);
        events.open(root / "events.jsonl", std::ios::binary);
        if (!raw || !events) throw std::runtime_error("Cannot create evidence files");
        raw.exceptions(std::ios::badbit | std::ios::failbit);
        events.exceptions(std::ios::badbit | std::ios::failbit);
    }
    void event(const std::string& object) {
        std::lock_guard<std::mutex> lock(mutex);
        try { event_locked(object); }
        catch (...) { failed.store(true); throw; }
    }
    void rx(const Bytes& bytes, std::uint64_t offset) {
        std::lock_guard<std::mutex> lock(mutex);
        try {
            raw.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
            raw.flush(); // Raw preservation precedes even the JSON log, then parsing.
            saved.fetch_add(bytes.size());
            event_locked("{\"event\":\"rx\",\"offset\":" + std::to_string(offset) +
                         ",\"count\":" + std::to_string(bytes.size()) + ",\"hex\":" + quote(hex(bytes)) + "}");
        } catch (...) { failed.store(true); throw; }
    }
    void result(const std::string& object) {
        std::ofstream file(root / "result.json", std::ios::binary | std::ios::trunc);
        file.exceptions(std::ios::badbit | std::ios::failbit);
        file << object << '\n';
        file.flush();
    }
    const std::filesystem::path root;
    std::atomic<std::uint64_t> saved{0};
    std::atomic<bool> failed{false};
private:
    void event_locked(const std::string& object) {
        const auto milliseconds = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - began).count();
        const auto line = "{\"utc\":" + quote(utc()) + ",\"elapsed_ms\":" + std::to_string(milliseconds) +
                          ",\"sequence\":" + std::to_string(++sequence) + ",\"detail\":" + object + "}";
        events << line << '\n';
        events.flush();
        std::cout << line << std::endl;
    }
    Clock::time_point began = Clock::now();
    std::uint64_t sequence = 0;
    std::mutex mutex;
    std::ofstream raw, events;
};

// Last resort for a kernel/driver call that ignores every per-I/O deadline.
// Ordinary failure and Ctrl+C run the documented STOP before this can expire.
class Watchdog {
public:
    Watchdog() : worker([this]() {
        std::unique_lock<std::mutex> lock(mutex);
        if (!cv.wait_for(lock, 75s, [this]() { return done; })) {
            std::cerr << "FATAL: 75-second watchdog; stop confirmation unavailable. Saved raw capture is retained.\n";
            TerminateProcess(GetCurrentProcess(), 71);
            std::_Exit(71);
        }
    }) {}
    ~Watchdog() {
        { std::lock_guard<std::mutex> lock(mutex); done = true; }
        cv.notify_one(); worker.join();
    }
private:
    std::mutex mutex;
    std::condition_variable cv;
    bool done = false;
    std::thread worker;
};

class Session final : public SequenceIO {
public:
    Session(WinSerial& serial, Log& logger) : port(serial), log(logger) {}
    ~Session() override { try { port.close(); } catch (...) {} }
    void receive(const Bytes& bytes) {
        std::lock_guard<std::mutex> lock(mutex);
        const auto offset = os_rx;
        os_rx += bytes.size(); // OS delivery evidence survives a later logger/parser failure.
        log.rx(bytes, offset);
        const auto decoded = decoder.feed(bytes);
        for (const auto& event : decoded) { describe(event); observations.push_back(event); }
        cv.notify_all();
    }
    void finish() {
        std::lock_guard<std::mutex> lock(mutex);
        for (const auto& event : decoder.finish()) describe(event);
    }
    bool interrupted() const override { return cancelled.load(); }
    void serial_note(const std::string& object) { event(object, cleanup_active.load()); }
    void note(const std::string& message) override {
        log.event("{\"event\":\"note\",\"message\":" + quote(message) + "}");
    }
    Exchange exchange(Command command, bool cleanup = false) override {
        struct CleanupFlag {
            std::atomic<bool>& flag;
            CleanupFlag(std::atomic<bool>& value, bool active) : flag(value) { flag.store(active); }
            ~CleanupFlag() { flag.store(false); }
        } cleanup_flag(cleanup_active, cleanup);
        Exchange result;
        if (interrupted() && !cleanup) { result.reason = "Interrupted before write"; return result; }
        const Bytes bytes = command_bytes(command);
        const auto began = Clock::now();
        std::size_t cursor;
        std::uint64_t boundary;
        {
            std::lock_guard<std::mutex> lock(mutex);
            cursor = observations.size();
            boundary = os_rx;
        }
        Handshake handshake{command, boundary, false, false, false, false, {}, {}, {}};
        event("{\"event\":\"tx_intent\",\"stage\":" + quote(command_name(command)) +
                  ",\"cleanup\":" + boolean(cleanup) + ",\"count\":" + std::to_string(bytes.size()) +
                  ",\"hex\":" + quote(hex(bytes)) + ",\"rx_boundary\":" + std::to_string(boundary) + "}", cleanup);
        result.write_attempted = true;
        const auto written = port.write(bytes, 1000, cleanup);
        if (written.count_available) os_tx += written.reported;
        else ++unknown_write_counts;
        ++write_calls;
        event("{\"event\":\"write_result\",\"stage\":" + quote(command_name(command)) +
                  ",\"intended_count\":" + std::to_string(written.requested) +
                  ",\"os_reported_count\":" + (written.count_available ? std::to_string(written.reported) : "null") +
                  ",\"count_available\":" + boolean(written.count_available) +
                  ",\"complete\":" + boolean(written.complete) + ",\"win32_error\":" +
                  std::to_string(written.error) + ",\"timed_out\":" + boolean(written.timed_out) +
                  ",\"physical_transmission_proven\":false}", cleanup);
        const bool drained = port.drain(1000);
        const auto listening_began = Clock::now();
        const auto deadline = listening_began + 5s;
        std::uint64_t received = 0;
        {
            std::unique_lock<std::mutex> lock(mutex);
            for (;;) {
                while (cursor < observations.size()) handshake.observe(observations[cursor++]);
                received = os_rx - boundary;
                if (handshake.successful() || handshake.nak || handshake.rejected ||
                    !port.reader_ok() || (interrupted() && !cleanup) || Clock::now() >= deadline) break;
                cv.wait_for(lock, 25ms);
            }
            if (handshake.successful() && written.complete && drained && port.reader_ok()) {
                result.success = true;
                result.status = handshake.status;
                if (command == Command::Status) expected = handshake.status;
                if (command == Command::Variant) { expected.angle_deg = 100; expected.resolution_hundredths = 100; }
                if (command == Command::Start) confirmed_start = Clock::now();
            }
        }
        const auto listened = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - listening_began).count();
        if (!written.complete) result.reason = "Partial/failed write; physical transmission unknown";
        else if (!drained) result.reason = "Output drain was not confirmed before its deadline";
        else if (!port.reader_ok()) result.reason = "Receive worker failed: " + port.reader_error();
        else if (result.success) result.reason = "ACK and matching complete successful reply";
        else if (handshake.nak || handshake.rejected) result.reason = handshake.reason;
        else if (interrupted() && !cleanup) result.reason = "Interrupted while awaiting reply";
        else result.reason = "Reply deadline: ACK=" + std::string(boolean(handshake.ack)) +
                             ", valid matching reply=" + boolean(handshake.reply);
        result.may_retry = command == Command::Status && written.complete && drained &&
                           port.reader_ok() && !interrupted() && received == 0 && Clock::now() >= deadline;
        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - began).count();
        const auto summary = "{\"event\":\"exchange_result\",\"stage\":" + quote(command_name(command)) +
            ",\"success\":" + boolean(result.success) + ",\"ack\":" + boolean(handshake.ack) +
            ",\"nak\":" + boolean(handshake.nak) + ",\"matching_reply\":" + boolean(handshake.reply) +
            ",\"rx_bytes\":" + std::to_string(received) + ",\"post_drain_listen_ms\":" + std::to_string(listened) +
            ",\"elapsed_ms\":" + std::to_string(elapsed) + ",\"may_retry\":" + boolean(result.may_retry) +
            ",\"reason\":" + quote(result.reason) + "}";
        exchanges.push_back(summary);
        event(summary, cleanup);
        return result;
    }
    bool capture() override {
        const auto deadline = confirmed_start + 10s;
        log.event("{\"event\":\"capture_begin\",\"duration_ms\":10000,\"origin\":\"confirmed_start_reply\"}");
        while (Clock::now() < deadline && !interrupted() && port.reader_ok())
            std::this_thread::sleep_for(20ms);
        const auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - confirmed_start).count();
        log.event("{\"event\":\"capture_end\",\"elapsed_since_start_confirmation_ms\":" + std::to_string(duration) + "}");
        return Clock::now() >= deadline && !interrupted() && port.reader_ok();
    }
    bool listen_passively() {
        const auto began = Clock::now();
        const auto deadline = began + 10s;
        log.event("{\"event\":\"passive_listen_begin\",\"duration_ms\":10000,\"transmit_enabled\":false}");
        while (Clock::now() < deadline && !interrupted() && port.reader_ok())
            std::this_thread::sleep_for(20ms);
        const bool completed = Clock::now() >= deadline && !interrupted() && port.reader_ok();
        const auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - began).count();
        log.event("{\"event\":\"passive_listen_end\",\"elapsed_ms\":" + std::to_string(duration) +
                  ",\"completed\":" + boolean(completed) + ",\"reader_healthy\":" + boolean(port.reader_ok()) +
                  ",\"reader_error\":" + quote(port.reader_error()) + "}");
        return completed;
    }
    std::string evidence_json() {
        std::lock_guard<std::mutex> lock(mutex);
        const auto stats = decoder.stats();
        std::ostringstream out;
        out << "{\"os_reported_tx_bytes\":" << os_tx << ",\"write_calls\":" << write_calls
            << ",\"write_calls_with_unavailable_count\":" << unknown_write_counts
            << ",\"physical_tx_proven\":false,\"raw_rx_bytes\":" << os_rx
            << ",\"raw_binary_bytes_saved_confirmed\":" << log.saved.load()
            << ",\"decoder_fed_bytes\":" << stats.raw_bytes
            << ",\"logging_failed\":" << boolean(log.failed.load())
            << ",\"ack_observations_including_ambiguous\":" << stats.ack
            << ",\"nak_observations_including_ambiguous\":" << stats.nak
            << ",\"unambiguous_ack_observations\":" << unambiguous_ack
            << ",\"unambiguous_nak_observations\":" << unambiguous_nak
            << ",\"crc_valid_frames_before_semantics\":" << stats.valid_frames
            << ",\"crc_failures\":" << stats.crc_failures
            << ",\"rejected_candidates_or_noise_runs\":" << stats.rejected
            << ",\"unclassified_bytes\":" << stats.noise
            << ",\"b0_crc_valid_frames\":" << b0_frames << ",\"semantically_valid_scans\":" << scans
            << ",\"total_valid_scan_samples\":" << samples
            << ",\"valid_scans_during_ten_second_capture\":" << capture_scans
            << ",\"exchanges\":[";
        for (std::size_t i = 0; i < exchanges.size(); ++i) { if (i) out << ','; out << exchanges[i]; }
        return out.str() + "]}";
    }
    bool has_valid_scans() const { return scans != 0; } // Call only after reader joined.
private:
    void event(const std::string& object, bool best_effort = false) {
        try { log.event(object); }
        catch (...) {
            if (!best_effort) throw;
            std::cerr << "Cleanup observation could not be saved: " << object << '\n';
        }
    }
    void describe(const Event& event) {
        std::ostringstream out;
        out << "{\"event\":\"decode\",\"offset\":" << event.offset << ",\"reason\":" << quote(event.reason);
        if (event.kind == EventKind::Ack || event.kind == EventKind::Nak) {
            const bool ack = event.kind == EventKind::Ack;
            if (event.reason.empty()) { if (ack) ++unambiguous_ack; else ++unambiguous_nak; }
            out << ",\"kind\":" << quote(ack ? "ACK" : "NAK")
                << ",\"attribution_uncertain\":" << boolean(!event.reason.empty());
        } else if (event.kind == EventKind::Frame) {
            const auto& frame = event.frame;
            const auto validation = validate_response(frame);
            out << ",\"kind\":\"CRC-valid frame\",\"response\":" << quote(response_name(frame.command()))
                << ",\"address\":" << static_cast<unsigned>(frame.address)
                << ",\"payload_length\":" << frame.payload.size()
                << ",\"crc_received\":" << frame.crc_received << ",\"crc_calculated\":" << frame.crc_calculated
                << ",\"status_byte\":" << static_cast<unsigned>(frame.status())
                << ",\"status_text\":" << quote(status_text(frame.status()))
                << ",\"generic_response_valid\":" << boolean(validation.ok)
                << ",\"validation_reason\":" << quote(validation.reason);
            if (frame.command() == 0xB1) {
                const auto status = decode_status(frame);
                out << ",\"b1_layout_supported\":" << boolean(status.supported)
                    << ",\"b1_reason\":" << quote(status.reason)
                    << ",\"operating_mode\":" << static_cast<unsigned>(status.operating_mode)
                    << ",\"device_error\":" << static_cast<unsigned>(status.device_error)
                    << ",\"angle_deg\":" << status.angle_deg << ",\"resolution_hundredths\":" << status.resolution_hundredths
                    << ",\"unit\":" << quote(status.unit) << ",\"baud\":" << status.baud;
            }
            if (frame.command() == 0xB0) {
                ++b0_frames;
                const auto scan = decode_scan(frame, expected.supported ? &expected : nullptr);
                if (scan.valid) {
                    ++scans; samples += scan.sample_count;
                    if (confirmed_start != Clock::time_point{} && Clock::now() < confirmed_start + 10s) ++capture_scans;
                }
                out << ",\"scan_valid\":" << boolean(scan.valid) << ",\"scan_reason\":" << quote(scan.reason)
                    << ",\"sample_count\":" << scan.sample_count << ",\"unit\":" << quote(scan.unit)
                    << ",\"optional_indices\":" << boolean(scan.has_indices);
            }
        } else {
            out << ",\"kind\":\"rejected or unclassified\",\"hex\":" << quote(hex(event.raw));
            if (event.frame.crc_received != event.frame.crc_calculated)
                out << ",\"crc_received\":" << event.frame.crc_received << ",\"crc_calculated\":" << event.frame.crc_calculated;
        }
        log.event(out.str() + "}");
    }
    WinSerial& port;
    Log& log;
    std::mutex mutex;
    std::condition_variable cv;
    Decoder decoder;
    std::vector<Event> observations;
    StatusInfo expected;
    Clock::time_point confirmed_start{};
    std::vector<std::string> exchanges;
    std::atomic<bool> cleanup_active{false};
    std::uint64_t os_rx = 0, unknown_write_counts = 0;
    std::uint64_t os_tx = 0, write_calls = 0, b0_frames = 0, scans = 0, samples = 0, capture_scans = 0;
    std::uint64_t unambiguous_ack = 0, unambiguous_nak = 0;
};

std::string result_json(const SequenceResult& result, bool opened, bool setup_complete, bool closed,
                        const std::string& settings, const std::string& evidence,
                        const std::string& led, bool scans, bool listen_only,
                        bool passive_complete, bool reader_healthy, const std::string& reader_error) {
    std::ostringstream out;
    out << "{\"state\":\"finished\",\"utc\":" << quote(utc())
        << ",\"run_mode\":" << quote(listen_only ? "listen_only" : "status_variant_start_capture_stop")
        << ",\"passive_listen_complete\":" << boolean(passive_complete)
        << ",\"reader_healthy_at_close\":" << boolean(reader_healthy)
        << ",\"reader_error\":" << quote(reader_error)
        << ",\"port_opened\":" << boolean(opened) << ",\"port_closed\":" << boolean(closed)
        << ",\"serial_setup_complete\":" << boolean(setup_complete)
        << ",\"serial_settings\":" << (settings.empty() ? "null" : settings)
        << ",\"stage\":" << quote(result.stage) << ",\"reason\":" << quote(result.reason)
        << ",\"status_confirmed\":" << boolean(result.status_confirmed)
        << ",\"variant_requested\":" << boolean(result.variant_requested)
        << ",\"variant_confirmed\":" << boolean(result.variant_confirmed)
        << ",\"original_angle_deg\":" << result.original.angle_deg
        << ",\"original_resolution_hundredths\":" << result.original.resolution_hundredths
        << ",\"start_attempted\":" << boolean(result.start_attempted)
        << ",\"start_confirmed\":" << boolean(result.start_confirmed)
        << ",\"capture_complete\":" << boolean(result.capture_complete)
        << ",\"stop_attempted\":" << boolean(result.stop_attempted)
        << ",\"stop_response_valid\":" << boolean(result.stop_response_valid)
        << ",\"stop_confirmed\":" << boolean(result.stop_confirmed)
        << ",\"stop_ambiguous\":" << boolean(result.stop_ambiguous)
        << ",\"sequence_complete\":" << boolean(result.sequence_complete)
        << ",\"actual_valid_scan_data_received\":" << boolean(scans)
        << ",\"interrupted\":" << boolean(cancelled.load())
        << ",\"operator_led_observation\":" << (led.empty() ? "null" : quote(led))
        << ",\"led_observation_is_command_proof\":false,\"evidence\":" << evidence << '}';
    return out.str();
}
} // namespace

int main(int argc, char** argv) {
    try {
        bool run = false, confirmed = false, variant = false, self_test = false, listen_only = false;
        std::string output, led;
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--run") run = true;
            else if (arg == "--confirm-hardware") confirmed = true;
            else if (arg == "--set-100deg-1deg") variant = true;
            else if (arg == "--self-test") self_test = true;
            else if (arg == "--listen-only") listen_only = true;
            else if ((arg == "--output" || arg == "--led-observation") && i + 1 < argc) {
                if (arg == "--output") output = argv[++i]; else led = argv[++i];
            } else if (arg == "--help") {
                std::cout << "lms200-native [--self-test] | --run --confirm-hardware [--set-100deg-1deg | --listen-only] [--output NEW_DIRECTORY] [--led-observation TEXT]\n";
                return 0;
            } else throw std::runtime_error("Unknown or incomplete argument: " + arg);
        }
        if (self_test) {
            if (run || confirmed || variant || listen_only || !output.empty() || !led.empty())
                throw std::runtime_error("--self-test must be used alone");
            const auto protocol = run_protocol_tests();
            const auto sequence = run_sequence_tests();
            const auto serial = run_serial_observation_tests();
            std::cout << "OFFLINE PASS: " << protocol << " protocol checks, " << sequence
                      << " sequence/handshake checks, " << serial << " injected serial observation checks. No serial port opened.\n";
            return 0;
        }
        if (listen_only && variant) throw std::runtime_error("--listen-only cannot be combined with a settings change");
        if (!run && listen_only) {
            std::cout << "OFFLINE PLAN: COM7 9600/8-N-1, ten-second passive listener, no TX commands. Live requires --run --confirm-hardware.\n";
            return 0;
        }
        if (!run) {
            std::cout << "OFFLINE PLAN: COM7 9600/8-N-1, flow control disabled. Status (at most 3 silent attempts), "
                      << (variant ? "100deg/1deg variant, " : "retain current settings, ")
                      << "start, 10-second capture, stop. Fresh powered-on/startup-complete/exclusive-port confirmation required.\n"
                      << "Run --self-test first. Live requires --run --confirm-hardware.\n";
            return 0;
        }
        if (!confirmed) throw std::runtime_error("Confirm powered ON, completed startup and all other COM7 applications closed before --confirm-hardware");
        if (output.empty()) output = "docs/diagnostics/native-COM7-" + utc(true);
        Log log(std::filesystem::absolute(output));
        log.result("{\"state\":\"running\",\"final_result_available\":false,\"stop_confirmed\":false}");
        Watchdog watchdog;
        if (!SetConsoleCtrlHandler(console_control, TRUE)) throw std::runtime_error("Cannot install Ctrl+C handler");
        WinSerial port;
        Session session(port, log);
        SequenceResult result;
        result.variant_requested = variant;
        bool opened = false, closed = false, passive_complete = false;
        log.event("{\"event\":\"run_begin\",\"native_api\":\"Win32\",\"variant_requested\":" + std::string(boolean(variant)) +
                  ",\"run_mode\":" + quote(listen_only ? "listen_only" : "status_variant_start_capture_stop") +
                  ",\"hardware_confirmation_supplied\":true,\"output_directory\":" + quote(log.root.string()) + "}");
        if (!led.empty()) log.event("{\"event\":\"operator_led_observation\",\"text\":" + quote(led) + ",\"command_proof\":false}");
        try {
            port.open(); opened = true;
            log.event("{\"event\":\"port_opened\",\"settings\":" + port.settings_json() + "}");
            port.start_reader([&](const Bytes& bytes) { session.receive(bytes); },
                              [&](const std::string& object) { session.serial_note(object); });
            log.event("{\"event\":\"reader_armed_before_tx\",\"pre_tx_listen_ms\":" + std::string(listen_only ? "10000" : "200") + "}");
            if (listen_only) {
                result.stage = "passive_listen";
                passive_complete = session.listen_passively();
                result.reason = passive_complete ? "Ten-second passive listener completed; no commands sent" :
                    "Passive listening interrupted or actual receive/log failure: " + port.reader_error();
            } else {
                std::this_thread::sleep_for(200ms);
                result = run_sequence(session, variant);
            }
        } catch (const std::exception& error) {
            result.reason = error.what();
            result.stage = opened ? (listen_only ? "passive_listen" : "reader_setup") : "open";
        }
        // run_sequence handles all start-related exceptions and bounded cleanup.
        try { port.close(); closed = port.ever_opened(); }
        catch (const std::exception& error) { result.reason += "; close: " + std::string(error.what()); }
        try { log.event("{\"event\":\"port_closed\",\"confirmed\":" + std::string(boolean(closed)) + "}"); }
        catch (...) { /* A failed event file must not prevent the separate final report. */ }
        try { session.finish(); } // Terminal-only classification; never satisfies a handshake.
        catch (const std::exception& error) { result.reason += "; terminal classification/log: " + std::string(error.what()); }
        const auto report = result_json(result, port.ever_opened(), opened, closed, port.settings_json(), session.evidence_json(), led,
            session.has_valid_scans(), listen_only, passive_complete, port.reader_ok(), port.reader_error());
        log.result(report);
        try { log.event("{\"event\":\"final_result\",\"report\":" + report + "}"); }
        catch (...) { std::cerr << "Final event log unavailable; separate result.json: " << report << '\n'; }
        SetConsoleCtrlHandler(console_control, FALSE);
        std::cout << "Evidence: " << log.root.string() << "\n";
        const bool evidence_complete = closed && port.reader_ok() && !log.failed.load();
        return evidence_complete && (listen_only ? passive_complete : result.sequence_complete && session.has_valid_scans()) ? 0 : 3;
    } catch (const std::exception& error) {
        std::cerr << "ERROR: " << error.what() << '\n';
        return 2;
    }
}
