#include "protocol.hpp"

#include <algorithm>
#include <iomanip>
#include <sstream>

namespace lmsnative {
namespace {
std::uint16_t word(const Bytes& bytes, std::size_t at) {
    return static_cast<std::uint16_t>(bytes.at(at) |
                                    (static_cast<unsigned>(bytes.at(at + 1)) << 8));
}

bool geometry(unsigned angle, unsigned resolution) {
    return (angle == 100 && (resolution == 25 || resolution == 50 || resolution == 100)) ||
           (angle == 180 && (resolution == 50 || resolution == 100));
}

Validation healthy(const Frame& frame) {
    const auto base = validate_response(frame);
    if (!base.ok) return base;
    if ((frame.status() & 7U) >= 3)
        return {false, "Scanner status is " + status_text(frame.status())};
    return {true, ""};
}
}  // namespace

std::uint16_t crc16(const std::uint8_t* data, std::size_t size) {
    // TL section 9 p107: one shift per BYTE, not eight shifts as in CRC-16/IBM.
    std::uint16_t crc = 0;
    std::uint8_t previous = 0;
    for (std::size_t index = 0; index < size; ++index) {
        const bool carry = (crc & 0x8000U) != 0;
        crc = static_cast<std::uint16_t>(crc << 1);
        if (carry) crc ^= 0x8005U;
        crc ^= static_cast<std::uint16_t>((static_cast<unsigned>(previous) << 8) | data[index]);
        previous = data[index];
    }
    return crc;
}

std::uint16_t crc16(const Bytes& data) { return crc16(data.data(), data.size()); }

std::string hex(const Bytes& data) {
    std::ostringstream out;
    out << std::hex << std::uppercase << std::setfill('0');
    for (std::size_t index = 0; index < data.size(); ++index) {
        if (index) out << ' ';
        out << std::setw(2) << static_cast<unsigned>(data[index]);
    }
    return out.str();
}

void Decoder::consume(std::size_t count) {
    buffer_.erase(buffer_.begin(), buffer_.begin() + static_cast<std::ptrdiff_t>(count));
    offset_ += count;
}

std::vector<Event> Decoder::feed(const Bytes& bytes) {
    stats_.raw_bytes += bytes.size();
    buffer_.insert(buffer_.end(), bytes.begin(), bytes.end());
    return parse(false);
}

std::vector<Event> Decoder::finish() { return parse(true); }

std::vector<Event> Decoder::parse(bool final) {
    std::vector<Event> events;
    bool recovering = false;
    const auto rejected = [&](const Bytes& raw, const std::string& reason) {
        Event event;
        event.kind = EventKind::Rejected;
        event.offset = offset_;
        event.raw = raw;
        event.reason = reason;
        events.push_back(std::move(event));
        ++stats_.rejected;
    };

    while (!buffer_.empty()) {
        const auto first = buffer_.front();
        if (first == 0x06 || first == 0x15) {
            Event event;
            event.kind = first == 0x06 ? EventKind::Ack : EventKind::Nak;
            event.offset = offset_;
            event.raw = {first};
            if (recovering || ambiguous_controls_)
                event.reason = "Control byte found during resynchronization; attribution uncertain";
            events.push_back(std::move(event));
            if (first == 0x06) ++stats_.ack; else ++stats_.nak;
            consume(1);
            continue;
        }
        if (first != 0x02) {
            auto end = std::find_if(buffer_.begin(), buffer_.end(), [](std::uint8_t byte) {
                return byte == 0x02 || byte == 0x06 || byte == 0x15;
            });
            const auto count = static_cast<std::size_t>(end - buffer_.begin());
            rejected(Bytes(buffer_.begin(), end), "Unclassified bytes outside a telegram");
            stats_.noise += count;
            consume(count);
            continue;
        }
        if (buffer_.size() < 4) {
            if (!final) break;
            rejected(buffer_, "Incomplete header at end of capture");
            recovering = true;
            ambiguous_controls_ = true;
            consume(1);
            continue;
        }
        const auto payload_size = static_cast<std::size_t>(word(buffer_, 2));
        if (payload_size == 0 || payload_size > 808) {
            rejected(Bytes(buffer_.begin(), buffer_.begin() + 4),
                     "Invalid length; payload must be 1..808 bytes (total at most 814)");
            ambiguous_controls_ = true;
            consume(1);
            continue;
        }
        const auto total_size = payload_size + 6;
        if (buffer_.size() < total_size) {
            if (!final) break;
            rejected(buffer_, "Incomplete declared telegram at end of capture; rescanning retained bytes");
            recovering = true;
            ambiguous_controls_ = true;
            consume(1);
            continue;
        }

        const auto received = word(buffer_, total_size - 2);
        const auto calculated = crc16(buffer_.data(), total_size - 2);
        if (received != calculated) {
            ++stats_.crc_failures;
            ambiguous_controls_ = true;
            Event event;
            event.kind = EventKind::Rejected;
            event.offset = offset_;
            event.raw.assign(buffer_.begin(), buffer_.begin() + static_cast<std::ptrdiff_t>(total_size));
            event.reason = "CRC mismatch; retain raw candidate and resynchronize one byte later";
            event.frame.offset = offset_;
            event.frame.address = buffer_[1];
            event.frame.raw = event.raw;
            event.frame.crc_received = received;
            event.frame.crc_calculated = calculated;
            events.push_back(std::move(event));
            ++stats_.rejected;
            consume(1);
            continue;
        }
        Event event;
        event.kind = EventKind::Frame;
        event.offset = offset_;
        event.raw.assign(buffer_.begin(), buffer_.begin() + static_cast<std::ptrdiff_t>(total_size));
        event.frame.offset = offset_;
        event.frame.address = buffer_[1];
        event.frame.payload.assign(buffer_.begin() + 4,
                                   buffer_.begin() + static_cast<std::ptrdiff_t>(4 + payload_size));
        event.frame.raw = event.raw;
        event.frame.crc_received = received;
        event.frame.crc_calculated = calculated;
        if (recovering) event.reason = "CRC-valid frame recovered by terminal rescan; original raw retained";
        events.push_back(std::move(event));
        ++stats_.valid_frames;
        consume(total_size);
        ambiguous_controls_ = false;
    }
    return events;
}

Validation validate_response(const Frame& frame) {
    if (frame.raw.size() < 7 || frame.raw[0] != 0x02)
        return {false, "Missing complete wire frame"};
    if (frame.address != 0x80 && frame.address != 0x81)
        return {false, "Unexpected address for broadcast request; expected 80 or 81"};
    if (frame.raw[1] != frame.address || word(frame.raw, 2) != frame.payload.size() ||
        frame.raw.size() != frame.payload.size() + 6 || frame.payload.size() > 808)
        return {false, "Frame metadata/length mismatch"};
    if (!std::equal(frame.payload.begin(), frame.payload.end(), frame.raw.begin() + 4))
        return {false, "Payload differs from preserved wire bytes"};
    if (crc16(frame.raw.data(), frame.raw.size() - 2) != word(frame.raw, frame.raw.size() - 2))
        return {false, "Invalid wire CRC"};
    if (frame.payload.size() < 2 || frame.command() < 0x80)
        return {false, "Response must contain a response command and status byte"};
    if ((frame.status() & 7U) > 4) return {false, "Reserved scanner status severity"};
    if (frame.command() == 0x92) return {false, "Scanner sent framed rejection 92"};
    return {true, ""};
}

Validation validate_a0(const Frame& frame) {
    const auto base = healthy(frame);
    if (!base.ok) return base;
    if (frame.command() != 0xA0) return {false, "Expected A0 operating-mode reply"};
    if (frame.payload.size() != 3) return {false, "A0 must contain one result byte and status"};
    if (frame.payload[1] != 0x00) return {false, "A0 reports rejected mode change"};
    return {true, "A0 result 00 and acceptable scanner status"};
}

Validation validate_bb(const Frame& frame) {
    const auto base = healthy(frame);
    if (!base.ok) return base;
    if (frame.command() != 0xBB) return {false, "Expected BB variant reply"};
    if (frame.payload.size() != 7) return {false, "BB must contain result, angle, resolution, status"};
    if (frame.payload[1] != 0x01) return {false, "BB reports variant change aborted"};
    if (word(frame.payload, 2) != 100 || word(frame.payload, 4) != 100)
        return {false, "BB echo differs from requested 100 degrees / 1 degree"};
    return {true, "BB result 01 and exact 100 degree / 1 degree echo"};
}

std::string status_text(std::uint8_t status) {
    static constexpr const char* severities[]{"ok", "info", "warning", "error", "fatal", "reserved", "reserved", "reserved"};
    std::ostringstream text;
    text << severities[status & 7U];
    const auto source = (status >> 3) & 3U;
    text << ", source=" << (source == 2 ? "LMS type 6" : source == 3 ? "special device" : "reserved");
    if (status & 0x20U) text << ", restart input high";
    if (status & 0x40U) text << ", implausible measured value";
    if (status & 0x80U) text << ", pollution";
    return text.str();
}

std::string response_name(std::uint8_t command) {
    switch (command) {
    case 0x90: return "90 startup";
    case 0x92: return "92 command rejection";
    case 0xA0: return "A0 operating mode";
    case 0xB0: return "B0 measurement scan";
    case 0xB1: return "B1 status";
    case 0xBB: return "BB variant";
    case 0xBA: return "BA model";
    case 0xF4: return "F4 configuration";
    case 0xF7: return "F7 configuration confirmation";
    default: return "Unrecognized response " + hex({command});
    }
}

StatusInfo decode_status(const Frame& frame) {
    StatusInfo result;
    result.status_byte = frame.status();
    const auto base = validate_response(frame);
    if (!base.ok) { result.reason = base.reason; return result; }
    if (frame.command() != 0xB1) { result.reason = "Expected B1 status response"; return result; }
    const Bytes data(frame.payload.begin() + 1, frame.payload.end() - 1);
    result.profile_data_length = data.size();
    // TL table 7-33 sums to 146 bytes; table 7-34 states 152. The latter
    // layout includes six reserved bytes before block E, corroborated by
    // SICK Toolbox _getSickStatus. No heuristic field searching is performed.
    if (data.size() != 146 && data.size() != 152) {
        result.reason = "Unsupported B1 layout: expected 146 or 152 data bytes; preserve raw for review";
        return result;
    }
    const std::size_t shift = data.size() == 152 ? 6 : 0;
    result.operating_mode = data[7];
    result.device_error = data[8];
    result.angle_deg = word(data, 100 + shift);
    result.resolution_hundredths = word(data, 102 + shift);
    result.measuring_mode = data[95 + shift];
    result.firmware.assign(data.begin(), data.begin() + 7);
    if (!std::all_of(result.firmware.begin(), result.firmware.end(), [](unsigned char c) { return c >= 0x20 && c <= 0x7E; })) {
        result.reason = "B1 firmware field is not printable ASCII";
        return result;
    }
    if (!geometry(result.angle_deg, result.resolution_hundredths)) {
        result.reason = "B1 angle/resolution outside documented LMS200 standard variants";
        return result;
    }
    if (data[115 + shift] > 1) { result.reason = "Reserved B1 measurement unit"; return result; }
    result.unit = data[115 + shift] == 1 ? "mm" : "cm";
    switch (word(data, 109 + shift)) {
    case 0x8067: result.baud = 9600; break;
    case 0x8033: result.baud = 19200; break;
    case 0x8019: result.baud = 38400; break;
    case 0x8001: result.baud = 500000; break;
    default: result.reason = "Unknown B1 baud code"; return result;
    }
    result.supported = true;
    result.reason = "Known B1 layout; scanner status: " + status_text(result.status_byte);
    return result;
}

ScanInfo decode_scan(const Frame& frame, const StatusInfo* expected) {
    ScanInfo result;
    result.status_byte = frame.status();
    const auto base = validate_response(frame);
    if (!base.ok) { result.reason = base.reason; return result; }
    if (frame.command() != 0xB0 || frame.payload.size() < 4) {
        result.reason = "Expected B0 with sample-count word and status";
        return result;
    }
    const auto header = word(frame.payload, 1);
    result.sample_count = header & 0x03FFU;
    const unsigned unit = header >> 14;
    if (unit > 1) { result.reason = "Reserved B0 measurement unit"; return result; }
    result.unit = unit == 1 ? "mm" : "cm";
    if (header & 0x3C00U) { result.reason = "Partial/interlaced or reserved B0 header unsupported"; return result; }
    if (result.sample_count == 0 || result.sample_count > 401) {
        result.reason = "B0 sample count outside LMS200 standard scan bounds";
        return result;
    }
    const std::size_t without_indices = 4 + 2 * result.sample_count;
    if (frame.payload.size() != without_indices && frame.payload.size() != without_indices + 2) {
        result.reason = "B0 body size disagrees with sample count (optional two index bytes allowed)";
        return result;
    }
    result.has_indices = frame.payload.size() == without_indices + 2;
    if (expected && expected->supported) {
        if (result.unit != expected->unit) { result.reason = "B0 unit differs from B1 status"; return result; }
        const auto expected_count = expected->angle_deg * 100 / expected->resolution_hundredths + 1;
        if (result.sample_count != expected_count) { result.reason = "B0 count differs from verified angle/resolution"; return result; }
    }
    if ((frame.status() & 7U) >= 3) { result.reason = "B0 scanner status is " + status_text(frame.status()); return result; }
    result.valid = true;
    result.reason = "Complete standard B0 scan; sample count and unit verified";
    return result;
}
}  // namespace lmsnative
