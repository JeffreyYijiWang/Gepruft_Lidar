#include "win_serial.hpp"

#include <array>
#include <atomic>
#include <chrono>
#include <future>
#include <limits>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <utility>

namespace lmsnative {
namespace {

std::string json_string(const std::string& value) {
    std::ostringstream out;
    out << '"';
    constexpr char hex[] = "0123456789abcdef";
    for (const auto ch : value) {
        const auto c = static_cast<unsigned char>(ch);
        if (c == '"' || c == '\\') out << '\\' << static_cast<char>(c);
        else if (c < 32) out << "\\u00" << hex[c >> 4] << hex[c & 15];
        else out << static_cast<char>(c);
    }
    out << '"';
    return out.str();
}

std::runtime_error windows_error(const char* operation, DWORD code = GetLastError()) {
    return std::runtime_error(std::string(operation) + " failed; Win32 error " +
                              std::to_string(code));
}

std::string nullable_number(bool available, DWORD value) {
    return available ? std::to_string(value) : "null";
}

struct SerialObservation {
    bool status_available = false;
    DWORD status_error = 0;
    DWORD uart_errors = 0;
    COMSTAT status{};
    bool modem_available = false;
    DWORD modem_error = 0;
    DWORD modem = 0;
};

using StatusQuery = std::function<bool(DWORD&, COMSTAT&, DWORD&)>;
using ModemQuery = std::function<bool(DWORD&, DWORD&)>;

SerialObservation collect_observation(const StatusQuery& status_query,
                                      const ModemQuery& modem_query) {
    SerialObservation result;
    result.status_available = status_query(result.uart_errors, result.status, result.status_error);
    // A failed status IOCTL does not prevent querying modem inputs independently.
    result.modem_available = modem_query(result.modem, result.modem_error);
    return result;
}

bool confirmed_empty_output(const SerialObservation& observation) {
    // Zero-initialized COMSTAT on a failed API call is never queue evidence.
    return observation.status_available && observation.status.cbOutQue == 0;
}

std::string observation_json(const SerialObservation& value, const char* stage) {
    std::ostringstream out;
    out << "{\"event\":\"serial_observation\",\"stage\":" << json_string(stage)
        << ",\"status_available\":" << (value.status_available ? "true" : "false")
        << ",\"status_error\":" << value.status_error
        << ",\"uart_error_mask\":" << nullable_number(value.status_available, value.uart_errors)
        << ",\"ce_break\":" << nullable_number(value.status_available, !!(value.uart_errors & CE_BREAK))
        << ",\"ce_frame\":" << nullable_number(value.status_available, !!(value.uart_errors & CE_FRAME))
        << ",\"ce_overrun\":" << nullable_number(value.status_available, !!(value.uart_errors & CE_OVERRUN))
        << ",\"ce_rxover\":" << nullable_number(value.status_available, !!(value.uart_errors & CE_RXOVER))
        << ",\"ce_rxparity\":" << nullable_number(value.status_available, !!(value.uart_errors & CE_RXPARITY))
        << ",\"rx_queue\":" << nullable_number(value.status_available, value.status.cbInQue)
        << ",\"tx_queue\":" << nullable_number(value.status_available, value.status.cbOutQue)
        << ",\"cts_hold\":" << nullable_number(value.status_available, value.status.fCtsHold)
        << ",\"dsr_hold\":" << nullable_number(value.status_available, value.status.fDsrHold)
        << ",\"rlsd_hold\":" << nullable_number(value.status_available, value.status.fRlsdHold)
        << ",\"xoff_hold\":" << nullable_number(value.status_available, value.status.fXoffHold)
        << ",\"xoff_sent\":" << nullable_number(value.status_available, value.status.fXoffSent)
        << ",\"modem_available\":" << (value.modem_available ? "true" : "false")
        << ",\"modem_mask\":" << nullable_number(value.modem_available, value.modem)
        << ",\"modem_error\":" << value.modem_error
        << ",\"cts\":" << nullable_number(value.modem_available, !!(value.modem & MS_CTS_ON))
        << ",\"dsr\":" << nullable_number(value.modem_available, !!(value.modem & MS_DSR_ON))
        << ",\"ring\":" << nullable_number(value.modem_available, !!(value.modem & MS_RING_ON))
        << ",\"rlsd\":" << nullable_number(value.modem_available, !!(value.modem & MS_RLSD_ON)) << "}";
    return out.str();
}

std::runtime_error preserve_primary_error(const char* operation, DWORD error,
                                          const std::function<void()>& optional_observation) {
    const auto original = windows_error(operation, error);
    try { optional_observation(); } catch (...) {}
    return original;
}

class Event {
public:
    Event() : handle_(CreateEventW(nullptr, TRUE, FALSE, nullptr)) {
        if (!handle_) throw windows_error("CreateEventW");
    }
    ~Event() { if (handle_) CloseHandle(handle_); }
    Event(const Event&) = delete;
    Event& operator=(const Event&) = delete;
    HANDLE get() const noexcept { return handle_; }
    void set() { if (!SetEvent(handle_)) throw windows_error("SetEvent"); }
    void reset() { if (!ResetEvent(handle_)) throw windows_error("ResetEvent"); }
private:
    HANDLE handle_;
};

}  // namespace

struct WinSerial::Impl {
    HANDLE port = INVALID_HANDLE_VALUE;
    bool opened_once = false;
    Event stop;
    std::thread reader;
    std::atomic<bool> healthy{true};
    std::atomic<bool> running{false};
    std::atomic<bool> armed_once{false};
    mutable std::mutex failure_mutex;
    std::string failure;
    // Only serializes ClearCommError, so no UART flags are consumed unreported.
    // User callbacks are deliberately invoked outside this mutex.
    std::mutex observation_mutex;
    bool last_observation_failed = false;
    DWORD last_status_error = 0, last_modem_error = 0;
    ULONGLONG last_failure_log_ms = 0;
    RxCallback receive;
    NoteCallback note;
    std::string settings;

    void emit(const std::string& value) { if (note) note(value); }

    void mark_failure(const std::string& value) noexcept {
        healthy.store(false);
        try {
            std::lock_guard<std::mutex> lock(failure_mutex);
            failure = value;
        } catch (...) {}
    }

    [[noreturn]] void fatal_shutdown(const char* operation, const char* event) noexcept {
        // Freeing an OVERLAPPED or buffer still owned by a driver is unsafe.
        // A driver which ignores cancellation is outside the ordinary cleanup
        // path: retain all local storage until process termination. Never detach
        // the worker and then permit its state to be destroyed. The outer program
        // also has a process watchdog for APIs that themselves fail to return.
        try {
            emit("{\"event\":" + json_string(event) + ",\"operation\":" +
                 json_string(operation) +
                 ",\"stop_confirmation\":\"unavailable\",\"exit_code\":70}");
        } catch (...) {}
        TerminateProcess(GetCurrentProcess(), 70);
        // TerminateProcess should not fail for our own process. This fallback also
        // terminates without unwinding objects whose storage could still be in use.
        std::_Exit(70);
    }

    [[noreturn]] void cancellation_failed(const char* operation) noexcept {
        fatal_shutdown(operation, "fatal_io_cancellation_timeout");
    }

    bool cancel_and_finish(OVERLAPPED& operation, DWORD& count,
                           DWORD& completion_error, const char* label) {
        // ERROR_NOT_FOUND can mean the operation completed before cancellation.
        // In either case retrieve its final completion before releasing storage.
        const BOOL cancelled = CancelIoEx(port, &operation);
        const DWORD cancel_error = cancelled ? ERROR_SUCCESS : GetLastError();
        if (WaitForSingleObject(operation.hEvent, 2000) != WAIT_OBJECT_0)
            cancellation_failed(label);
        count = 0;
        const BOOL done = GetOverlappedResult(port, &operation, &count, FALSE);
        completion_error = done ? ERROR_SUCCESS : GetLastError();
        if (completion_error == ERROR_IO_INCOMPLETE)
            cancellation_failed(label);
        // Logging is after kernel completion, so a failing logger cannot release
        // storage prematurely. ERROR_OPERATION_ABORTED is an expected cancellation.
        try {
            emit("{\"event\":\"io_cancel_completed\",\"operation\":" +
                 json_string(label) + ",\"cancel_error\":" + std::to_string(cancel_error) +
                 ",\"completion_error\":" + std::to_string(completion_error) +
                 ",\"os_reported_count\":" + (done ? std::to_string(count) : "null") + "}");
        } catch (...) {
            // Preserve final completion/count for the caller even if its separate
            // observational logger fails. Do not let it obscure completed writes.
            mark_failure("I/O cancellation observation callback failed");
        }
        if (!done) count = 0; // An initialized or unspecified output is not a count.
        return done != FALSE;
    }

    SerialObservation observe(const char* stage, bool always = false) {
        SerialObservation value;
        bool log_observation = false;
        {
            std::lock_guard<std::mutex> lock(observation_mutex);
            value = collect_observation(
                [this](DWORD& errors, COMSTAT& status, DWORD& error) {
                    const BOOL ok = ClearCommError(port, &errors, &status);
                    error = ok ? ERROR_SUCCESS : GetLastError();
                    return ok != FALSE;
                },
                [this](DWORD& modem, DWORD& error) {
                    const BOOL ok = GetCommModemStatus(port, &modem);
                    error = ok ? ERROR_SUCCESS : GetLastError();
                    return ok != FALSE;
                });
            const bool unavailable = !value.status_available || !value.modem_available;
            const auto now = GetTickCount64();
            if (unavailable) {
                // Do not fill the log with identical failures on every empty read
                // or 2 ms drain poll. Still record first failure, changes and recovery.
                log_observation = (value.status_available && value.uart_errors) ||
                                  !last_observation_failed || value.status_error != last_status_error ||
                                  value.modem_error != last_modem_error || now - last_failure_log_ms >= 1000;
                if (log_observation) last_failure_log_ms = now;
            } else {
                log_observation = always || value.uart_errors || last_observation_failed;
            }
            last_observation_failed = unavailable;
            last_status_error = value.status_error;
            last_modem_error = value.modem_error;
        }
        // Query failures are observations, not evidence ReadFile failed. Logger
        // failures still propagate because preserving the capture is mandatory.
        if (log_observation) emit(observation_json(value, stage));
        return value;
    }

    [[noreturn]] void read_failed(const char* operation, DWORD error) {
        // Preserve the completed read's primary failure before optional queries.
        // A secondary failed IOCTL/logger must never replace it in reader_error().
        throw preserve_primary_error(operation, error, [this, operation, error]() {
            try {
                emit("{\"event\":\"read_io_failed\",\"operation\":" + json_string(operation) +
                     ",\"win32_error\":" + std::to_string(error) + "}");
            } catch (...) {}
            observe("read_failed", true);
        });
    }

    void read_loop(const std::shared_ptr<std::promise<void>>& armed) noexcept {
        bool signalled = false;
        try {
            Event ready;
            std::array<std::uint8_t, 4096> buffer{};
            OVERLAPPED operation{};
            operation.hEvent = ready.get();
            observe("reader_start", true);
            for (;;) {
                if (WaitForSingleObject(stop.get(), 0) == WAIT_OBJECT_0) break;
                ready.reset();
                DWORD count = 0;
                const BOOL immediate = ReadFile(port, buffer.data(),
                    static_cast<DWORD>(buffer.size()), nullptr, &operation);
                const DWORD initial_error = immediate ? ERROR_SUCCESS : GetLastError();
                if (!immediate && initial_error != ERROR_IO_PENDING)
                    read_failed("ReadFile", initial_error);
                if (!signalled) {
                    armed_once.store(true);
                    signalled = true;
                    armed->set_value();  // The first ReadFile has actually been issued.
                }
                DWORD error = ERROR_SUCCESS;
                const char* error_operation = "GetOverlappedResult(ReadFile)";
                bool stopping = false;
                if (immediate) {
                    // Obtain the completed OS count through the overlapped API
                    // for synchronous completion too; no asynchronous count pointer.
                    if (!GetOverlappedResult(port, &operation, &count, FALSE)) {
                        error = GetLastError();
                        count = 0; // No documented completion count on failure.
                    }
                    if (error == ERROR_IO_INCOMPLETE)
                        cancel_and_finish(operation, count, error, "ReadFile");
                } else {
                    HANDLE events[] = {ready.get(), stop.get()};
                    // COMMTIMEOUTS bounds reads to 50 ms. The 1 s guard catches a
                    // driver ignoring those timeouts; stop wakes this wait at once.
                    const DWORD wait = WaitForMultipleObjects(2, events, FALSE, 1000);
                    if (wait != WAIT_OBJECT_0) {
                        stopping = wait == WAIT_OBJECT_0 + 1;
                        const DWORD wait_error = wait == WAIT_TIMEOUT ? ERROR_TIMEOUT :
                                                 wait == WAIT_FAILED ? GetLastError() : ERROR_GEN_FAILURE;
                        cancel_and_finish(operation, count, error, "ReadFile");
                        if (!stopping) {
                            error = wait_error;
                            error_operation = "WaitForMultipleObjects(ReadFile)";
                        }
                    } else {
                        count = 0;
                        if (!GetOverlappedResult(port, &operation, &count, FALSE)) {
                            error = GetLastError();
                            count = 0;
                        }
                        if (error == ERROR_IO_INCOMPLETE)
                            cancel_and_finish(operation, count, error, "ReadFile");
                    }
                }
                // Preserve any OS-reported bytes, including a partial completion
                // at cancellation. The application callback writes raw bytes before
                // parsing and is the only path through which read bytes are exposed.
                if (count > buffer.size())
                    throw std::runtime_error("ReadFile reported count beyond its supplied buffer");
                if (count) receive(Bytes(buffer.begin(), buffer.begin() + count));
                if (!stopping && error != ERROR_SUCCESS)
                    read_failed(error_operation, error);
                observe(stopping ? "reader_stop" : "read_completed", count != 0);
                if (stopping) break;
            }
        } catch (const std::exception& error) {
            mark_failure(error.what());
            if (!signalled) {
                try { armed->set_exception(std::current_exception()); } catch (...) {}
            }
            try {
                emit("{\"event\":\"serial_reader_failed\",\"message\":" +
                     json_string(error.what()) + "}");
            } catch (...) {}
        } catch (...) {
            mark_failure("Unknown serial reader/callback failure");
            if (!signalled) {
                try { armed->set_exception(std::current_exception()); } catch (...) {}
            }
        }
        running.store(false);
    }
};

WinSerial::WinSerial() : impl_(std::make_unique<Impl>()) {}
WinSerial::~WinSerial() {
    try { close(); } catch (...) {}
}

bool WinSerial::is_open() const noexcept { return impl_->port != INVALID_HANDLE_VALUE; }
bool WinSerial::ever_opened() const noexcept { return impl_->opened_once; }

void WinSerial::open() {
    if (is_open()) throw std::logic_error("COM7 is already open");
    impl_->armed_once.store(false);
    impl_->port = CreateFileW(L"\\\\.\\COM7", GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                            OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED,
                            nullptr);
    if (!is_open()) throw windows_error("CreateFileW(COM7)");
    impl_->opened_once = true;
    try {
        DCB dcb{};
        dcb.DCBlength = sizeof(dcb);
        dcb.BaudRate = CBR_9600;
        dcb.fBinary = TRUE;
        dcb.fParity = FALSE;
        dcb.fOutxCtsFlow = FALSE;
        dcb.fOutxDsrFlow = FALSE;
        dcb.fDtrControl = DTR_CONTROL_DISABLE;
        dcb.fDsrSensitivity = FALSE;
        dcb.fTXContinueOnXoff = TRUE;
        dcb.fOutX = FALSE;
        dcb.fInX = FALSE;
        dcb.fErrorChar = FALSE;
        dcb.fNull = FALSE;
        dcb.fRtsControl = RTS_CONTROL_DISABLE;
        dcb.fAbortOnError = FALSE;
        dcb.fDummy2 = 0;
        dcb.wReserved = 0;
        dcb.XonLim = 128;
        dcb.XoffLim = 128;
        dcb.ByteSize = 8;
        dcb.Parity = NOPARITY;
        dcb.StopBits = ONESTOPBIT;
        dcb.XonChar = 0x11;
        dcb.XoffChar = 0x13;
        dcb.ErrorChar = 0;
        dcb.EofChar = 0;
        dcb.EvtChar = 0;
        dcb.wReserved1 = 0;
        if (!SetCommState(impl_->port, &dcb)) throw windows_error("SetCommState");

        COMMTIMEOUTS timeouts{};
        timeouts.ReadIntervalTimeout = MAXDWORD;
        timeouts.ReadTotalTimeoutMultiplier = 0;
        timeouts.ReadTotalTimeoutConstant = 50;
        timeouts.WriteTotalTimeoutMultiplier = 0;
        timeouts.WriteTotalTimeoutConstant = 1000;
        if (!SetCommTimeouts(impl_->port, &timeouts)) throw windows_error("SetCommTimeouts");

        DCB actual{};
        actual.DCBlength = sizeof(actual);
        COMMTIMEOUTS actual_timeouts{};
        if (!GetCommState(impl_->port, &actual)) throw windows_error("GetCommState");
        if (!GetCommTimeouts(impl_->port, &actual_timeouts))
            throw windows_error("GetCommTimeouts");
        DWORD modem = 0;
        const BOOL modem_ok = GetCommModemStatus(impl_->port, &modem);
        const DWORD modem_error = modem_ok ? ERROR_SUCCESS : GetLastError();
        std::ostringstream out;
        out << "{\"port\":\"COM7\",\"api\":\"Win32 overlapped\",\"baud\":" << actual.BaudRate
            << ",\"byte_size\":" << static_cast<unsigned>(actual.ByteSize)
            << ",\"parity\":" << static_cast<unsigned>(actual.Parity)
            << ",\"stop_bits\":" << static_cast<unsigned>(actual.StopBits)
            << ",\"fBinary\":" << actual.fBinary << ",\"fParity\":" << actual.fParity
            << ",\"fOutxCtsFlow\":" << actual.fOutxCtsFlow
            << ",\"fOutxDsrFlow\":" << actual.fOutxDsrFlow
            << ",\"fDtrControl\":" << actual.fDtrControl
            << ",\"fDsrSensitivity\":" << actual.fDsrSensitivity
            << ",\"fTXContinueOnXoff\":" << actual.fTXContinueOnXoff
            << ",\"fOutX\":" << actual.fOutX << ",\"fInX\":" << actual.fInX
            << ",\"fErrorChar\":" << actual.fErrorChar << ",\"fNull\":" << actual.fNull
            << ",\"fRtsControl\":" << actual.fRtsControl
            << ",\"fAbortOnError\":" << actual.fAbortOnError
            << ",\"fDummy2\":" << actual.fDummy2
            << ",\"xon_limit\":" << actual.XonLim << ",\"xoff_limit\":" << actual.XoffLim
            << ",\"xon_char\":" << static_cast<unsigned>(static_cast<unsigned char>(actual.XonChar))
            << ",\"xoff_char\":" << static_cast<unsigned>(static_cast<unsigned char>(actual.XoffChar))
            << ",\"error_char\":" << static_cast<unsigned>(static_cast<unsigned char>(actual.ErrorChar))
            << ",\"eof_char\":" << static_cast<unsigned>(static_cast<unsigned char>(actual.EofChar))
            << ",\"event_char\":" << static_cast<unsigned>(static_cast<unsigned char>(actual.EvtChar))
            << ",\"read_interval_ms\":" << actual_timeouts.ReadIntervalTimeout
            << ",\"read_multiplier_ms\":" << actual_timeouts.ReadTotalTimeoutMultiplier
            << ",\"read_constant_ms\":" << actual_timeouts.ReadTotalTimeoutConstant
            << ",\"write_multiplier_ms\":" << actual_timeouts.WriteTotalTimeoutMultiplier
            << ",\"write_constant_ms\":" << actual_timeouts.WriteTotalTimeoutConstant
            << ",\"modem_available\":" << (modem_ok ? "true" : "false")
            << ",\"modem_mask\":" << nullable_number(modem_ok != FALSE, modem)
            << ",\"modem_error\":" << modem_error
            << ",\"cts\":" << nullable_number(modem_ok != FALSE, !!(modem & MS_CTS_ON))
            << ",\"dsr\":" << nullable_number(modem_ok != FALSE, !!(modem & MS_DSR_ON))
            << ",\"ring\":" << nullable_number(modem_ok != FALSE, !!(modem & MS_RING_ON))
            << ",\"rlsd\":" << nullable_number(modem_ok != FALSE, !!(modem & MS_RLSD_ON))
            << ",\"receive_purge_called\":false}";
        impl_->settings = out.str();
        if (actual.BaudRate != CBR_9600 || actual.ByteSize != 8 ||
            actual.Parity != NOPARITY || actual.StopBits != ONESTOPBIT ||
            !actual.fBinary || actual.fParity || actual.fOutxCtsFlow || actual.fOutxDsrFlow ||
            actual.fDtrControl != DTR_CONTROL_DISABLE || actual.fDsrSensitivity ||
            actual.fOutX || actual.fInX || actual.fErrorChar || actual.fNull ||
            actual.fRtsControl != RTS_CONTROL_DISABLE || actual.fAbortOnError ||
            actual_timeouts.ReadIntervalTimeout != MAXDWORD ||
            actual_timeouts.ReadTotalTimeoutMultiplier != 0 ||
            actual_timeouts.ReadTotalTimeoutConstant != 50 ||
            actual_timeouts.WriteTotalTimeoutMultiplier != 0 ||
            actual_timeouts.WriteTotalTimeoutConstant != 1000)
            throw std::runtime_error("Actual COM7 settings differ from required fixed settings: " +
                                     impl_->settings);
    } catch (...) {
        CloseHandle(impl_->port);
        impl_->port = INVALID_HANDLE_VALUE;
        throw;
    }
}

std::string WinSerial::settings_json() const { return impl_->settings; }

void WinSerial::start_reader(RxCallback receive, NoteCallback note) {
    if (!is_open()) throw std::logic_error("COM7 is not open");
    if (impl_->reader.joinable()) throw std::logic_error("Serial reader already exists");
    if (!receive) throw std::invalid_argument("A raw RX callback is required");
    impl_->receive = std::move(receive);
    impl_->note = std::move(note);
    impl_->stop.reset();
    impl_->healthy.store(true);
    impl_->running.store(true);
    auto armed = std::make_shared<std::promise<void>>();
    auto future = armed->get_future();
    impl_->reader = std::thread([state = impl_.get(), armed]() { state->read_loop(armed); });
    // The outer executable watchdog also covers a driver API which itself blocks.
    if (future.wait_for(std::chrono::seconds(2)) != std::future_status::ready)
        impl_->cancellation_failed("initial ReadFile did not arm");
    future.get();
}

WriteResult WinSerial::write(const Bytes& bytes, DWORD timeout_ms, bool allow_failed_reader) {
    const Bytes stop_bytes{0x02, 0x00, 0x02, 0x00, 0x20, 0x25, 0x35, 0x08};
    if (allow_failed_reader && bytes != stop_bytes)
        throw std::invalid_argument("Failed-reader cleanup permits only exact documented STOP");
    if (!is_open() || !impl_->armed_once.load())
        throw std::logic_error("Write requires an open port and a previously armed reader");
    if ((!impl_->running.load() || !impl_->healthy.load()) && !allow_failed_reader)
        throw std::logic_error("Write requires an open port and healthy persistent reader");
    if (bytes.empty() || bytes.size() > std::numeric_limits<DWORD>::max())
        throw std::invalid_argument("Invalid binary write length");
    if (timeout_ms == 0 || timeout_ms > 5000)
        throw std::invalid_argument("Write deadline must be 1..5000 ms");
    if (allow_failed_reader && (!impl_->running.load() || !impl_->healthy.load())) {
        try {
            impl_->emit("{\"event\":\"cleanup_stop_with_failed_reader\","
                        "\"stop_confirmation\":\"unavailable\"}");
        } catch (...) {
            // A logger error can itself be why the reader failed. It must not
            // prevent the exact, explicitly authorized emergency STOP WriteFile.
            impl_->mark_failure("Cleanup STOP observation callback failed");
        }
    }
    Event ready;
    OVERLAPPED operation{};
    operation.hEvent = ready.get();
    WriteResult result;
    result.requested = static_cast<DWORD>(bytes.size());
    // Exactly one WriteFile: no partial-write retries and no byte-at-a-time delays.
    const BOOL immediate = WriteFile(impl_->port, bytes.data(), result.requested,
                                    nullptr, &operation);
    const DWORD initial_error = immediate ? ERROR_SUCCESS : GetLastError();
    if (!immediate && initial_error != ERROR_IO_PENDING) {
        result.error = initial_error;
    } else if (immediate) {
        result.count_available = GetOverlappedResult(impl_->port, &operation, &result.reported, FALSE) != FALSE;
        if (!result.count_available)
            result.error = GetLastError();
        if (result.error == ERROR_IO_INCOMPLETE)
            result.count_available = impl_->cancel_and_finish(operation, result.reported, result.error, "WriteFile");
    } else {
        const DWORD wait = WaitForSingleObject(ready.get(), timeout_ms);
        if (wait == WAIT_OBJECT_0) {
            result.reported = 0;
            result.count_available = GetOverlappedResult(impl_->port, &operation, &result.reported, FALSE) != FALSE;
            if (!result.count_available)
                result.error = GetLastError();
            if (result.error == ERROR_IO_INCOMPLETE)
                result.count_available = impl_->cancel_and_finish(operation, result.reported, result.error, "WriteFile");
        } else {
            const DWORD wait_error = wait == WAIT_TIMEOUT ? ERROR_TIMEOUT : GetLastError();
            result.timed_out = wait == WAIT_TIMEOUT;
            DWORD completion_error = 0;
            result.count_available = impl_->cancel_and_finish(operation, result.reported, completion_error, "WriteFile");
            result.error = wait_error;
        }
    }
    if (!result.count_available) result.reported = 0; // Caller must serialize unknown as null.
    result.complete = result.count_available && result.error == ERROR_SUCCESS && result.reported == result.requested;
    if (!result.complete && result.error == ERROR_SUCCESS) result.error = ERROR_WRITE_FAULT;
    try {
        impl_->observe("write_completed", true);
    } catch (const std::exception& error) {
        impl_->mark_failure(error.what());
        try {
            impl_->emit("{\"event\":\"post_write_observation_failed\",\"message\":" +
                        json_string(error.what()) + "}");
        } catch (...) {}
    } catch (...) {
        impl_->mark_failure("Post-write observation callback failed");
    }
    return result;
}

bool WinSerial::drain(DWORD timeout_ms) {
    if (!is_open()) throw std::logic_error("COM7 is not open");
    if (timeout_ms == 0 || timeout_ms > 5000)
        throw std::invalid_argument("Drain deadline must be 1..5000 ms");
    const auto deadline = GetTickCount64() + timeout_ms;
    impl_->emit("{\"event\":\"output_drain_begin\",\"method\":\"ClearCommError cbOutQue polling\","
                "\"deletes_rx\":false,\"deletes_tx\":false}");
    for (;;) {
        const auto observation = impl_->observe("output_drain");
        if (confirmed_empty_output(observation)) {
            impl_->emit("{\"event\":\"output_drain_complete\",\"os_output_queue\":0,"
                        "\"physical_transmission_proven\":false}");
            return true;
        }
        if (GetTickCount64() >= deadline) {
            impl_->emit("{\"event\":\"output_drain_timeout\",\"queue_available\":" +
                        std::string(observation.status_available ? "true" : "false") +
                        ",\"os_output_queue\":" + nullable_number(observation.status_available, observation.status.cbOutQue) +
                        ",\"status_error\":" + std::to_string(observation.status_error) +
                        ",\"drain_confirmed\":false}");
            return false;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
}

bool WinSerial::reader_ok() const noexcept { return impl_->healthy.load(); }
std::string WinSerial::reader_error() const {
    std::lock_guard<std::mutex> lock(impl_->failure_mutex);
    return impl_->failure;
}

void WinSerial::stop_reader() {
    if (!impl_->reader.joinable()) return;
    try { impl_->stop.set(); }
    catch (...) { impl_->fatal_shutdown("stop_reader SetEvent failed", "fatal_reader_shutdown_failure"); }
    // Worker wakes from WaitForMultipleObjects and cancels its own ReadFile. It
    // retrieves completion before releasing buffer/event/OVERLAPPED or returning.
    // The ordinary path is <=2 s; a non-cancelling driver invokes the fatal path.
    try { impl_->reader.join(); }
    catch (...) { impl_->fatal_shutdown("stop_reader join failed", "fatal_reader_shutdown_failure"); }
}

void WinSerial::close() {
    stop_reader();
    if (is_open()) {
        const HANDLE port = impl_->port;
        impl_->port = INVALID_HANDLE_VALUE;
        if (!CloseHandle(port)) throw windows_error("CloseHandle(COM7)");
    }
}

int run_serial_observation_tests() {
    int checks = 0;
    const auto require = [&checks](bool condition, const char* label) {
        if (!condition) throw std::runtime_error(std::string("Serial observation self-test: ") + label);
        ++checks;
    };
    unsigned modem_calls = 0;
    const StatusQuery denied = [](DWORD& errors, COMSTAT& status, DWORD& error) {
        // Deliberately supply garbage outputs: failed queries have no values,
        // even if the API happened to modify the caller's buffers.
        errors = CE_BREAK;
        status.cbInQue = 77;
        status.cbOutQue = 88;
        error = ERROR_ACCESS_DENIED;
        return false;
    };
    const ModemQuery modem_ok = [&modem_calls](DWORD& modem, DWORD& error) {
        ++modem_calls;
        modem = MS_DSR_ON;
        error = ERROR_SUCCESS;
        return true;
    };
    const auto unavailable = collect_observation(denied, modem_ok);
    require(!unavailable.status_available && unavailable.status_error == ERROR_ACCESS_DENIED,
            "ClearCommError access denied is a result, not an exception");
    require(modem_calls == 1 && unavailable.modem_available && unavailable.modem == MS_DSR_ON,
            "modem query runs independently after status failure");
    require(!confirmed_empty_output(unavailable), "unavailable status cannot confirm output drain");
    const auto serialized = observation_json(unavailable, "synthetic");
    require(serialized.find("\"status_available\":false") != std::string::npos,
            "status availability explicitly serialized");
    require(serialized.find("\"rx_queue\":null") != std::string::npos &&
            serialized.find("\"tx_queue\":null") != std::string::npos,
            "unavailable queues are null");
    require(serialized.find("\"uart_error_mask\":null") != std::string::npos &&
            serialized.find("\"ce_break\":null") != std::string::npos,
            "unavailable UART outputs are null, ignoring modified API buffers");
    require(serialized.find("\"dsr\":1") != std::string::npos,
            "independently available modem signal is retained");

    const StatusQuery denied_zero = [](DWORD&, COMSTAT&, DWORD& error) {
        error = ERROR_ACCESS_DENIED;
        return false;
    };
    const ModemQuery modem_denied = [](DWORD& modem, DWORD& error) {
        modem = MS_CTS_ON; // Also must not be reported on failure.
        error = ERROR_NOT_SUPPORTED;
        return false;
    };
    const auto zero_unknown = collect_observation(denied_zero, modem_denied);
    require(zero_unknown.status.cbOutQue == 0 && !confirmed_empty_output(zero_unknown),
            "default initialized zero queue is not drain evidence");
    const auto unknown_json = observation_json(zero_unknown, "synthetic");
    require(unknown_json.find("\"modem_available\":false") != std::string::npos &&
            unknown_json.find("\"modem_mask\":null") != std::string::npos &&
            unknown_json.find("\"cts\":null") != std::string::npos,
            "unavailable modem fields are null");

    const StatusQuery queue_zero = [](DWORD& errors, COMSTAT& status, DWORD& error) {
        errors = 0; status.cbOutQue = 0; error = ERROR_SUCCESS; return true;
    };
    const auto drained = collect_observation(queue_zero, modem_denied);
    require(confirmed_empty_output(drained),
            "known empty output confirms drain despite unavailable modem query");
    const auto known_json = observation_json(drained, "synthetic");
    require(known_json.find("\"tx_queue\":0") != std::string::npos,
            "successful query zero is serialized as zero");
    const StatusQuery queue_busy = [](DWORD& errors, COMSTAT& status, DWORD& error) {
        errors = 0; status.cbOutQue = 4; error = ERROR_SUCCESS; return true;
    };
    require(!confirmed_empty_output(collect_observation(queue_busy, modem_ok)),
            "nonempty output cannot confirm drain");

    bool optional_called = false;
    const auto primary = preserve_primary_error("GetOverlappedResult(ReadFile)", ERROR_GEN_FAILURE,
        [&optional_called]() {
            optional_called = true;
            throw windows_error("ClearCommError", ERROR_ACCESS_DENIED);
        });
    require(optional_called && std::string(primary.what()).find("GetOverlappedResult(ReadFile)") != std::string::npos &&
            std::string(primary.what()).find("Win32 error 31") != std::string::npos,
            "primary read completion failure survives failed optional observation");
    require(std::string(primary.what()).find("ClearCommError") == std::string::npos,
            "secondary diagnostic failure never masks primary read failure");
    const auto original = preserve_primary_error("ReadFile", ERROR_ACCESS_DENIED, []() {});
    require(std::string(original.what()).find("ReadFile failed; Win32 error 5") != std::string::npos,
            "actual read access denied remains a read failure");
    return checks;
}

}  // namespace lmsnative
