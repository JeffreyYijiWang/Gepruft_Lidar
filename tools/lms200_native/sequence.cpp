#include "sequence.hpp"
#include <exception>
#include <stdexcept>

namespace lmsnative {
const char* command_name(Command command) {
    switch (command) {
    case Command::Status: return "status";
    case Command::Variant: return "set_100deg_1deg";
    case Command::Start: return "start_continuous";
    case Command::Stop: return "stop_continuous";
    }
    throw std::logic_error("Unknown command");
}
Bytes command_bytes(Command command) {
    switch (command) {
    case Command::Status: return {kStatusRequest.begin(), kStatusRequest.end()};
    case Command::Variant: return {kSet100Deg1Deg.begin(), kSet100Deg1Deg.end()};
    case Command::Start: return {kStartContinuous.begin(), kStartContinuous.end()};
    case Command::Stop: return {kStopContinuous.begin(), kStopContinuous.end()};
    }
    throw std::logic_error("Unknown command");
}
void Handshake::observe(const Event& event) {
    if (event.offset < first_offset || !event.reason.empty()) return;
    if (event.kind == EventKind::Ack) { ack = true; return; }
    if (event.kind == EventKind::Nak) { nak = true; reason = "Standalone NAK observed"; return; }
    if (event.kind != EventKind::Frame) return;
    if (event.frame.command() == 0x92 &&
        (event.frame.address == 0x80 || event.frame.address == 0x81)) {
        rejected = true; reason = "CRC-valid framed command rejection 92"; return;
    }
    const unsigned expected = command == Command::Status ? 0xB1 :
                              command == Command::Variant ? 0xBB : 0xA0;
    if (event.frame.command() != expected) return;
    if (!ack) { reason = "Matching frame arrived before ACK; not used for handshake"; return; }
    Validation check;
    if (command == Command::Status) {
        status = decode_status(event.frame);
        check = {status.supported && (status.status_byte & 7U) < 3 && status.device_error == 0,
                 status.reason};
        if (status.supported && status.device_error) check.reason = "B1 device error flag is set";
        if (status.supported && status.baud != 9600) {
            check.ok = false; check.reason = "B1 baud code differs from the fixed 9600 host setting";
        }
    } else {
        check = command == Command::Variant ? validate_bb(event.frame) : validate_a0(event.frame);
    }
    if (!check.ok) { rejected = true; reason = check.reason; return; }
    frame = event.frame;
    reply = true;
    reason = check.reason;
}

SequenceResult run_sequence(SequenceIO& io, bool set_variant) {
    SequenceResult result;
    result.variant_requested = set_variant;
    // Once invoked for a start, conservative cleanup also covers an exception
    // between the actual WriteFile call and recording its completed count.
    const auto stop = [&]() {
        if (!result.start_attempted || result.stop_attempted) return;
        result.stop_attempted = true;
        try {
            const auto response = io.exchange(Command::Stop, true);
            result.stop_response_valid = response.success;
            result.stop_confirmed = response.success && result.start_confirmed;
            result.stop_ambiguous = !result.start_confirmed;
            if (!response.success) result.reason += "; stop: " + response.reason;
            if (result.stop_ambiguous)
                result.reason += "; cleanup A0 cannot disambiguate a delayed start reply";
        } catch (const std::exception& error) {
            result.reason += "; stop exception: " + std::string(error.what());
        }
    };
    try {
        for (int attempt = 1; attempt <= 3; ++attempt) {
            if (io.interrupted()) { result.reason = "Interrupted before status write"; return result; }
            const auto response = io.exchange(Command::Status);
            if (response.success) {
                result.status_confirmed = true;
                result.original = response.status;
                break;
            }
            result.reason = response.reason;
            if (!response.may_retry || attempt == 3 || io.interrupted()) return result;
            io.note("Status retry after a complete five-second silent receive window");
        }
        // QM p12/p14 says stop continuous output before further settings. Do not
        // insert an unrequested pre-stop/configuration sequence or reinterpret a
        // different existing mode. The operator can review the captured B1 first.
        if (result.original.operating_mode != 0x25) {
            result.reason = "Initial B1 mode is not monitoring on request (25); sequence aborted before settings/start";
            return result;
        }
        if (set_variant) {
            result.stage = "set_100deg_1deg";
            if (io.interrupted()) { result.reason = "Interrupted before variant write"; return result; }
            const auto response = io.exchange(Command::Variant);
            if (!response.success) { result.reason = response.reason; return result; }
            result.variant_confirmed = true;
        }
        result.stage = "start_continuous";
        if (io.interrupted()) { result.reason = "Interrupted before start write"; return result; }
        result.start_attempted = true;
        const auto started = io.exchange(Command::Start);
        result.start_attempted = started.write_attempted;
        if (!started.success) { result.reason = started.reason; stop(); return result; }
        result.start_confirmed = true;
        result.stage = "capture";
        result.capture_complete = io.capture();
        result.reason = result.capture_complete ? "Ten-second capture completed" : "Capture interrupted or receive worker failed";
        result.stage = result.capture_complete ? "stop_continuous" : "capture";
        stop();
        result.sequence_complete = result.capture_complete && result.stop_confirmed;
        if (result.sequence_complete) { result.stage = "complete"; result.reason = "Status, requested settings, start, capture and stop confirmed"; }
    } catch (const std::exception& error) {
        result.reason = std::string("Exception: ") + error.what();
        stop();
    }
    return result;
}
} // namespace lmsnative
