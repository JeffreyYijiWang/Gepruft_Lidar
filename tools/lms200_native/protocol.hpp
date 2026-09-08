#pragma once

// Pure C++17 LMS2xx protocol. No serial, operating-system, or transport access.
// Sources: Quick Manual v1.0 June 2001 pp9,11-15,17; Telegram Listing
// 8007954/Q501, sections 4,7.4-7.6,7.16,8,9. See README.md for source links.
#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace lmsnative {
using Bytes = std::vector<std::uint8_t>;

// Explicit binary arrays, including the independently checked low/high CRC bytes.
inline constexpr std::array<std::uint8_t, 7> kStatusRequest{
    0x02, 0x00, 0x01, 0x00, 0x31, 0x15, 0x12};
inline constexpr std::array<std::uint8_t, 11> kSet100Deg1Deg{
    0x02, 0x00, 0x05, 0x00, 0x3B, 0x64, 0x00, 0x64, 0x00, 0x1D, 0x0F};
inline constexpr std::array<std::uint8_t, 8> kStartContinuous{
    0x02, 0x00, 0x02, 0x00, 0x20, 0x24, 0x34, 0x08};
inline constexpr std::array<std::uint8_t, 8> kStopContinuous{
    0x02, 0x00, 0x02, 0x00, 0x20, 0x25, 0x35, 0x08};

std::uint16_t crc16(const std::uint8_t* data, std::size_t size);
std::uint16_t crc16(const Bytes& data);
std::string hex(const Bytes& data);

struct Frame {
    std::uint64_t offset = 0;
    std::uint8_t address = 0;
    Bytes payload;  // Command, data, then status byte; excludes framing and CRC.
    Bytes raw;
    std::uint16_t crc_received = 0;
    std::uint16_t crc_calculated = 0;
    std::uint8_t command() const { return payload.empty() ? 0 : payload.front(); }
    std::uint8_t status() const { return payload.size() < 2 ? 0 : payload.back(); }
};

enum class EventKind { Ack, Nak, Frame, Rejected };
struct Event {
    EventKind kind = EventKind::Rejected;
    std::uint64_t offset = 0;
    Bytes raw;
    std::string reason;
    Frame frame;
};

struct DecoderStats {
    std::uint64_t raw_bytes = 0;
    std::uint64_t ack = 0;
    std::uint64_t nak = 0;
    std::uint64_t valid_frames = 0;  // Complete CRC-valid frames, before semantics.
    std::uint64_t crc_failures = 0;
    std::uint64_t rejected = 0;
    std::uint64_t noise = 0;
};

class Decoder {
public:
    std::vector<Event> feed(const Bytes& bytes);
    // Terminal operation: report incomplete bytes and rescan behind false headers.
    // It changes only this decoder's pending copy, never the caller's raw capture.
    // Recovered events carry an explicit recovery reason; do not use them to
    // retroactively satisfy a command handshake. No idle-based expiration exists.
    std::vector<Event> finish();
    const DecoderStats& stats() const { return stats_; }
    const Bytes& pending() const { return buffer_; }
    std::uint64_t consumed_offset() const { return offset_; }

private:
    std::vector<Event> parse(bool final);
    void consume(std::size_t count);
    Bytes buffer_;
    std::uint64_t offset_ = 0;
    DecoderStats stats_;
    bool ambiguous_controls_ = false;
};

struct Validation {
    bool ok = false;
    std::string reason;
};
Validation validate_response(const Frame& frame);
Validation validate_a0(const Frame& frame);
Validation validate_bb(const Frame& frame);  // Exact requested 100 degrees / 1 degree.
std::string status_text(std::uint8_t status);
std::string response_name(std::uint8_t command);

struct StatusInfo {
    bool supported = false;  // Known, semantically valid layout; not a health claim.
    std::string reason;
    std::string firmware;
    std::uint8_t operating_mode = 0;
    std::uint8_t device_error = 0;
    unsigned angle_deg = 0;
    unsigned resolution_hundredths = 0;
    std::string unit;
    std::uint8_t measuring_mode = 0;
    std::uint8_t status_byte = 0;
    unsigned baud = 0;
    std::size_t profile_data_length = 0;
};
StatusInfo decode_status(const Frame& frame);

struct ScanInfo {
    bool valid = false;
    std::string reason;
    unsigned sample_count = 0;  // Available even if a later semantic check fails.
    std::string unit;
    std::uint8_t status_byte = 0;
    bool has_indices = false;
};
ScanInfo decode_scan(const Frame& frame, const StatusInfo* expected = nullptr);

// Throws std::runtime_error on failure. All fixtures are offline synthetic data
// unless an exact manual example and its printed page are stated in the test.
int run_protocol_tests();
}  // namespace lmsnative
