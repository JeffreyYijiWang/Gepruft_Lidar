#include "protocol.hpp"

#include <algorithm>
#include <functional>
#include <stdexcept>
#include <utility>

namespace lmsnative {
namespace {
void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

// Synthetic fixture constructor: these are deliberately not hardware captures.
Bytes synthetic_frame(const Bytes& payload, std::uint8_t address = 0x81) {
    Bytes bytes{0x02, address, static_cast<std::uint8_t>(payload.size() & 0xFFU),
                static_cast<std::uint8_t>(payload.size() >> 8)};
    bytes.insert(bytes.end(), payload.begin(), payload.end());
    const auto crc = crc16(bytes);
    bytes.push_back(static_cast<std::uint8_t>(crc & 0xFFU));
    bytes.push_back(static_cast<std::uint8_t>(crc >> 8));
    return bytes;
}

Frame parsed(const Bytes& bytes) {
    Decoder decoder;
    auto events = decoder.feed(bytes);
    require(events.size() == 1 && events.front().kind == EventKind::Frame,
            "Test fixture did not produce exactly one frame");
    return events.front().frame;
}

Bytes concatenate(Bytes lhs, const Bytes& rhs) {
    lhs.insert(lhs.end(), rhs.begin(), rhs.end());
    return lhs;
}

std::size_t frames(const std::vector<Event>& events) {
    return static_cast<std::size_t>(std::count_if(events.begin(), events.end(), [](const Event& e) {
        return e.kind == EventKind::Frame;
    }));
}

Bytes synthetic_status(std::size_t size = 146, std::uint8_t address = 0x81,
                       std::uint8_t status = 0x10) {
    Bytes data(size, 0);
    const Bytes firmware{'V', '0', '2', '.', '1', '0', ' '};
    std::copy(firmware.begin(), firmware.end(), data.begin());
    data[7] = 0x25;  // Monitoring on request, TL table 7-33.
    const auto shift = size == 152 ? 6U : 0U;
    data[95 + shift] = 2;
    data[100 + shift] = 100;
    data[102 + shift] = 100;
    data[109 + shift] = 0x67;
    data[110 + shift] = 0x80;
    data[115 + shift] = 1;
    Bytes payload{0xB1};
    payload.insert(payload.end(), data.begin(), data.end());
    payload.push_back(status);
    return synthetic_frame(payload, address);
}

Bytes synthetic_scan(unsigned count = 101, std::uint16_t flags = 0x4000,
                     bool indices = false, std::uint8_t status = 0x10) {
    const auto header = static_cast<std::uint16_t>(count | flags);
    Bytes payload{0xB0, static_cast<std::uint8_t>(header & 0xFFU),
                  static_cast<std::uint8_t>(header >> 8)};
    for (unsigned index = 0; index < count; ++index) {
        // Include in-band STX, ACK and NAK values. They must remain sample bytes.
        payload.push_back(index == 0 ? 0x02 : index == 1 ? 0x06 : index == 2 ? 0x15 : 0x23);
        payload.push_back(0x01);
    }
    if (indices) { payload.push_back(0x06); payload.push_back(0x02); }
    payload.push_back(status);
    return synthetic_frame(payload);
}

template <std::size_t N>
void verify_command(const std::array<std::uint8_t, N>& command,
                    std::size_t length, std::uint16_t expected_crc) {
    require(N == length, "Explicit command length differs from manual");
    require(command[0] == 0x02 && command[1] == 0, "Command STX/address mismatch");
    require(static_cast<std::size_t>(command[2] | (command[3] << 8)) + 6 == N,
            "Command declared length mismatch");
    require(crc16(command.data(), N - 2) == expected_crc, "Manual command CRC mismatch");
    require(command[N - 2] == (expected_crc & 0xFFU) && command[N - 1] == (expected_crc >> 8),
            "Command CRC is not little-endian");
}
}  // namespace

int run_protocol_tests() {
    int count = 0;
    const auto test = [&](const char* name, const std::function<void()>& body) {
        try { body(); }
        catch (const std::exception& error) { throw std::runtime_error(std::string(name) + ": " + error.what()); }
        ++count;
    };

    // Exact printed manual examples; their CRCs are NOT created by our encoder.
    const Bytes a0{0x02, 0x81, 0x03, 0x00, 0xA0, 0x00, 0x10, 0x36, 0x1A}; // QM pp10,12,14.
    const Bytes bb{0x02, 0x81, 0x07, 0x00, 0xBB, 0x01, 0x64, 0x00,
                   0x64, 0x00, 0x10, 0x4A, 0x3F}; // QM p11,100 degrees/1 degree.
    const Bytes startup{0x02, 0x81, 0x17, 0x00, 0x90, 0x4C, 0x4D, 0x53,
        0x32, 0x30, 0x30, 0x3B, 0x33, 0x30, 0x31, 0x30, 0x36, 0x33,
        0x3B, 0x56, 0x30, 0x32, 0x2E, 0x30, 0x36, 0x20, 0x13, 0x64, 0x5A}; // QM p9.

    test("QM p9 binary status request and CRC", [&] { verify_command(kStatusRequest, 7, 0x1215); });
    test("QM p11 binary variant request and CRC", [&] { verify_command(kSet100Deg1Deg, 11, 0x0F1D); });
    test("QM p12 binary start request and CRC", [&] { verify_command(kStartContinuous, 8, 0x0834); });
    test("QM p14 binary stop request and CRC", [&] { verify_command(kStopContinuous, 8, 0x0835); });
    test("QM golden reply CRCs", [&] {
        require(crc16(a0.data(), a0.size() - 2) == 0x1A36, "A0 CRC");
        require(crc16(bb.data(), bb.size() - 2) == 0x3F4A, "BB CRC");
        require(crc16(startup.data(), startup.size() - 2) == 0x5A64, "Startup CRC");
        require(validate_a0(parsed(a0)).ok && validate_bb(parsed(bb)).ok, "Golden reply semantics");
    });
    test("Empty CRC and binary zero bytes", [&] {
        require(crc16(Bytes{}) == 0 && crc16(Bytes{0, 0, 0}) == 0, "CRC initialization");
        require(hex(Bytes(kStatusRequest.begin(), kStatusRequest.end())) == "02 00 01 00 31 15 12",
                "Binary array text rendering");
    });
    test("Every two-chunk split of manual startup", [&] {
        for (std::size_t split = 1; split < startup.size(); ++split) {
            Decoder decoder;
            require(decoder.feed(Bytes(startup.begin(), startup.begin() + static_cast<std::ptrdiff_t>(split))).empty(),
                    "Premature fragmented frame");
            const auto events = decoder.feed(Bytes(startup.begin() + static_cast<std::ptrdiff_t>(split), startup.end()));
            require(frames(events) == 1 && events[0].raw == startup, "Fragment loss");
        }
    });
    test("One-byte delivery and arbitrarily many empty reads", [&] {
        Decoder decoder;
        std::size_t seen = 0;
        for (const auto byte : a0) {
            for (unsigned gap = 0; gap < 100; ++gap) require(decoder.feed({}).empty(), "Empty read expired a fragment");
            seen += frames(decoder.feed({byte}));
        }
        require(seen == 1 && decoder.pending().empty(), "One-byte assembly");
    });
    test("ACK and reply combined", [&] {
        Decoder decoder;
        auto events = decoder.feed(concatenate({0x06}, a0));
        require(events.size() == 2 && events[0].kind == EventKind::Ack && events[1].kind == EventKind::Frame,
                "Combined ACK/frame ordering");
        require(events[0].offset == 0 && events[1].offset == 1, "Raw offsets");
    });
    test("ACK and reply separate", [&] {
        Decoder decoder;
        require(decoder.feed({0x06}).front().kind == EventKind::Ack, "Standalone ACK");
        require(frames(decoder.feed(a0)) == 1, "Subsequent response");
    });
    test("Multiple frames and retained leftover header", [&] {
        Decoder decoder;
        auto stream = concatenate(concatenate(a0, bb), {0x02, 0x81});
        require(frames(decoder.feed(stream)) == 2 && decoder.pending() == Bytes({0x02, 0x81}), "Leftover preservation");
        require(frames(decoder.feed(Bytes(a0.begin() + 2, a0.end()))) == 1, "Next read uses leftover");
    });
    test("Broadcast response addresses 80 and 81", [&] {
        require(validate_a0(parsed(synthetic_frame({0xA0, 0, 0x10}, 0x80))).ok, "Address80");
        require(validate_a0(parsed(a0)).ok, "Address81");
        require(!validate_a0(parsed(synthetic_frame({0xA0, 0, 0x10}, 0x82))).ok, "Address82 accepted");
    });
    test("CRC failure and recovery to valid reply", [&] {
        auto corrupt = a0;
        corrupt.back() ^= 0x40;
        Decoder decoder;
        require(frames(decoder.feed(concatenate(corrupt, a0))) == 1, "Resynchronization lost valid reply");
        require(decoder.stats().crc_failures == 1, "CRC failure count");
    });
    test("CRC byte order reversal rejected", [&] {
        auto corrupt = a0;
        std::swap(corrupt[corrupt.size() - 1], corrupt[corrupt.size() - 2]);
        Decoder decoder;
        require(frames(decoder.feed(corrupt)) == 0 && decoder.stats().crc_failures == 1, "Reversed CRC accepted");
    });
    test("Swapped length stays invalid even with recomputed CRC", [&] {
        // Synthetic corruption of the QM A0 example: 03 00 becomes 00 03,
        // declaring 768 payload bytes while only three are supplied. Correcting
        // the checksum of the available bytes must not make that a valid frame.
        auto corrupt = a0;
        std::swap(corrupt[2], corrupt[3]);
        const auto checksum = crc16(corrupt.data(), corrupt.size() - 2);
        corrupt[corrupt.size() - 2] = static_cast<std::uint8_t>(checksum & 0xFFU);
        corrupt[corrupt.size() - 1] = static_cast<std::uint8_t>(checksum >> 8);
        Decoder decoder;
        require(decoder.feed(corrupt).empty() && decoder.pending() == corrupt,
                "Swapped declared length was accepted or discarded prematurely");
        require(frames(decoder.finish()) == 0 && decoder.stats().valid_frames == 0,
                "Recomputed CRC concealed the inconsistent little-endian length");
        require(decoder.pending().empty(), "Terminal analysis did not classify the truncated candidate");
    });
    test("In-band STX ACK NAK are sample bytes", [&] {
        Decoder decoder;
        require(frames(decoder.feed(synthetic_scan())) == 1, "Embedded controls broke framing");
        require(decoder.stats().ack == 0 && decoder.stats().nak == 0, "Payload interpreted as controls");
    });
    test("ACK NAK and unclassified noise counts", [&] {
        Decoder decoder;
        const auto events = decoder.feed({0xA0, 0x04, 0x06, 0x15});
        require(events.size() == 3 && decoder.stats().noise == 2 && decoder.stats().ack == 1 && decoder.stats().nak == 1,
                "Raw A0 incorrectly treated as ACK");
    });
    test("Plausible false header recovered only at terminal rescan", [&] {
        const auto raw = concatenate({0x02, 0x81, 0x00, 0x03}, a0);
        Decoder decoder;
        require(decoder.feed(raw).empty() && decoder.pending() == raw, "False header not preserved");
        const auto events = decoder.finish();
        require(frames(events) == 1 && decoder.pending().empty(), "Terminal rescan missed hidden valid frame");
        const auto found = std::find_if(events.begin(), events.end(), [](const Event& e) { return e.kind == EventKind::Frame; });
        require(found->offset == 4 && !found->reason.empty(), "Recovered frame not identified");
        require(raw == concatenate({0x02, 0x81, 0x00, 0x03}, a0), "Caller raw capture changed");
        require(decoder.finish().empty(), "Repeated finish duplicates evidence");
    });
    test("Truncated final telegram never marked valid", [&] {
        Decoder decoder;
        decoder.feed(Bytes(a0.begin(), a0.end() - 1));
        require(frames(decoder.finish()) == 0 && decoder.stats().valid_frames == 0, "Truncated frame accepted");
    });
    test("Invalid zero and overlarge lengths resynchronize", [&] {
        Decoder decoder;
        auto raw = concatenate({0x02, 0x81, 0, 0, 0x02, 0x81, 0x29, 0x03}, a0);
        require(frames(decoder.feed(raw)) == 1, "Invalid length blocked next frame");
    });
    test("Ambiguous controls from bad CRC cannot masquerade as certain ACK", [&] {
        auto bad = synthetic_frame({0xB0, 0x06, 0x15, 0x10});
        bad.back() ^= 1;
        Decoder decoder;
        const auto events = decoder.feed(bad);
        for (const auto& event : events) {
            if (event.kind == EventKind::Ack || event.kind == EventKind::Nak)
                require(!event.reason.empty(), "Control byte in corrupt candidate lacks uncertainty label");
        }
    });
    test("A0 result length health and command validation", [&] {
        require(!validate_a0(parsed(synthetic_frame({0xA0, 1, 0x10}))).ok, "Rejected result accepted");
        require(!validate_a0(parsed(synthetic_frame({0xA0, 0, 0, 0x10}))).ok, "Extra data accepted");
        require(!validate_a0(parsed(synthetic_frame({0xA0, 0, 0x13}))).ok, "Error status accepted");
        require(!validate_a0(parsed(synthetic_frame({0xA1, 0, 0x10}))).ok, "Wrong response accepted");
    });
    test("BB success and exact geometry echo", [&] {
        require(!validate_bb(parsed(synthetic_frame({0xBB, 0, 100, 0, 100, 0, 0x10}))).ok, "Aborted BB accepted");
        require(!validate_bb(parsed(synthetic_frame({0xBB, 1, 180, 0, 100, 0, 0x10}))).ok, "Wrong echo accepted");
    });
    test("Framed rejection and reserved status severity", [&] {
        require(!validate_response(parsed(synthetic_frame({0x92, 0x10}))).ok, "92 rejection accepted");
        require(!validate_response(parsed(synthetic_frame({0xA0, 0, 0x15}))).ok, "Reserved severity accepted");
    });
    test("Frame validation independently checks wire CRC and metadata", [&] {
        auto frame = parsed(a0);
        frame.raw.back() ^= 1;
        require(!validate_response(frame).ok, "Modified raw CRC accepted");
        frame = parsed(a0);
        frame.payload[1] = 1;
        require(!validate_response(frame).ok, "Payload/raw mismatch accepted");
    });
    test("Both explicit B1 status layouts", [&] {
        for (const auto size : {146U, 152U}) {
            const auto status = decode_status(parsed(synthetic_status(size)));
            require(status.supported && status.angle_deg == 100 && status.resolution_hundredths == 100 &&
                    status.unit == "mm" && status.baud == 9600 && status.operating_mode == 0x25 &&
                    status.profile_data_length == size, "Known B1 field offsets");
        }
    });
    test("B1 unknown layout fails without field heuristics", [&] {
        auto status_frame = parsed(synthetic_status());
        auto payload = status_frame.payload;
        payload.insert(payload.end() - 1, 0);
        require(!decode_status(parsed(synthetic_frame(payload))).supported, "Unknown length accepted");
    });
    test("B1 invalid geometry baud and unit rejected", [&] {
        for (const auto offset : {101U, 110U, 116U}) {
            auto payload = parsed(synthetic_status()).payload;
            payload[offset] = 0xFE;
            require(!decode_status(parsed(synthetic_frame(payload))).supported, "Invalid B1 field accepted");
        }
    });
    test("B1 error is valid communication, not healthy scanner", [&] {
        const auto status = decode_status(parsed(synthetic_status(146, 0x81, 0x13)));
        require(status.supported && (status.status_byte & 7U) == 3, "Scanner error conflated with bad framing");
    });
    test("Standard scan count units and optional indices", [&] {
        const auto status = decode_status(parsed(synthetic_status()));
        for (const auto indices : {false, true}) {
            const auto scan = decode_scan(parsed(synthetic_scan(101, 0x4000, indices)), &status);
            require(scan.valid && scan.sample_count == 101 && scan.unit == "mm" && scan.has_indices == indices,
                    "Standard B0 interpretation");
        }
    });
    test("Largest 814-byte indexed scan accepted", [&] {
        const auto raw = synthetic_scan(401, 0x4000, true);
        require(raw.size() == 814, "Maximum fixture wrong");
        require(decode_scan(parsed(raw)).valid, "Maximum valid frame rejected");
    });
    test("Scan unit geometry and body length checked", [&] {
        const auto status = decode_status(parsed(synthetic_status()));
        require(!decode_scan(parsed(synthetic_scan(101, 0)), &status).valid, "Changed unit accepted");
        require(!decode_scan(parsed(synthetic_scan(181)), &status).valid, "Changed count accepted");
        auto payload = parsed(synthetic_scan()).payload;
        payload.erase(payload.begin() + 4);
        require(!decode_scan(parsed(synthetic_frame(payload))).valid, "Odd body length accepted");
    });
    test("Swapped B0 count-unit word rejected after recomputed CRC", [&] {
        // Synthetic full 101-sample mm scan: 65 40 encodes count101/unitmm.
        // Swapping to 40 65 instead declares count320 plus partial-scan bits.
        // Re-encode the wire CRC so semantic validation, not a CRC failure,
        // must detect the incorrect byte order.
        const auto expected = decode_status(parsed(synthetic_status()));
        auto payload = parsed(synthetic_scan()).payload;
        std::swap(payload[1], payload[2]);
        Decoder decoder;
        const auto events = decoder.feed(synthetic_frame(payload));
        require(frames(events) == 1 && decoder.stats().crc_failures == 0,
                "Recomputed-CRC fixture did not reach semantic validation");
        const auto scan = decode_scan(events.front().frame, &expected);
        require(!scan.valid && scan.sample_count == 320 && !scan.reason.empty(),
                "Swapped B0 count-unit word accepted as the intended scan");
    });
    test("Reserved and partial scan formats retained but not accepted", [&] {
        for (const auto flags : {0x8000, 0x4400, 0x4800, 0x6000}) {
            require(!decode_scan(parsed(synthetic_scan(101, static_cast<std::uint16_t>(flags)))).valid,
                    "Unsupported B0 format accepted");
        }
    });
    test("Bad scan status still exposes count and CRC-valid frame", [&] {
        Decoder decoder;
        const auto events = decoder.feed(synthetic_scan(101, 0x4000, false, 0x13));
        const auto scan = decode_scan(events.front().frame);
        require(decoder.stats().valid_frames == 1 && !scan.valid && scan.sample_count == 101,
                "Frame, sample-count and semantic validity conflated");
    });
    test("Status flags and response names", [&] {
        const auto text = status_text(0xF2);
        require(text.find("warning") != std::string::npos && text.find("pollution") != std::string::npos &&
                text.find("implausible") != std::string::npos && text.find("restart") != std::string::npos,
                "Status flags missing");
        require(response_name(0xB1) == "B1 status", "Response name");
    });
    return count;
}
}  // namespace lmsnative
