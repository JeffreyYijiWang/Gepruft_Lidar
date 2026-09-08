#pragma once

#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace lmsnative {

using Bytes = std::vector<std::uint8_t>;
using RxCallback = std::function<void(const Bytes&)>;
// A JSON object, not a preformatted timestamp. Callbacks may run concurrently.
using NoteCallback = std::function<void(const std::string&)>;

struct WriteResult {
    DWORD requested = 0;
    DWORD reported = 0;  // OS completion count; never proof of connector signals.
    bool count_available = false; // False means unknown, not zero, on failed I/O.
    DWORD error = 0;
    bool complete = false;
    bool timed_out = false;
};

// Fixed COM7/9600/8-N-1 diagnostic transport. There is exactly one read worker.
// Its owner must outlive callbacks and call stop_reader()/close() before destroying
// their captured state. No receive buffer deletion is performed, including on open.
class WinSerial {
public:
    WinSerial();
    ~WinSerial();
    WinSerial(const WinSerial&) = delete;
    WinSerial& operator=(const WinSerial&) = delete;

    void open();
    bool is_open() const noexcept;
    bool ever_opened() const noexcept;
    std::string settings_json() const;
    // Does not return until the worker has issued its first ReadFile.
    void start_reader(RxCallback receive, NoteCallback note);
    // The failed-reader exception is cleanup-only and accepts exactly the
    // documented eight-byte STOP. It cannot claim a reply without a live reader.
    WriteResult write(const Bytes& bytes, DWORD timeout_ms = 1000,
                      bool allow_failed_reader = false);
    // Polls the output queue; never deletes queued bytes. Reader stays active.
    bool drain(DWORD timeout_ms = 1000);
    bool reader_ok() const noexcept;
    std::string reader_error() const;
    void stop_reader();
    void close();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// Pure fake-query checks: never constructs WinSerial or opens a communications port.
int run_serial_observation_tests();

}  // namespace lmsnative
