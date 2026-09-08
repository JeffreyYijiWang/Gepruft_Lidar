#include "sequence.hpp"
#include <deque>
#include <stdexcept>
#include <vector>

namespace lmsnative {
namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(std::string("Sequence test: ") + message);
}
Exchange good() {
    Exchange result;
    result.success = true;
    result.write_attempted = true;
    result.status.supported = true;
    result.status.operating_mode = 0x25;
    result.status.angle_deg = 180;
    result.status.resolution_hundredths = 50;
    result.status.baud = 9600;
    return result;
}
Exchange failure(bool retry = false) {
    Exchange result;
    result.write_attempted = true;
    result.may_retry = retry;
    result.reason = retry ? "Silent five-second timeout" : "Rejected, partial, or incomplete response";
    return result;
}
struct Fake final : SequenceIO {
    std::deque<Exchange> results;
    std::vector<Command> sent;
    bool cancelled = false, cancel_on_capture = false, throw_start = false, throw_capture = false;
    bool cancel_after_status = false;
    int captures = 0, notes = 0;
    Exchange exchange(Command command, bool cleanup = false) override {
        require((command == Command::Stop) == cleanup, "only STOP uses cleanup override");
        sent.push_back(command);
        if (command == Command::Start && throw_start) throw std::runtime_error("Injected start failure");
        if (command == Command::Status && cancel_after_status) cancelled = true;
        if (results.empty()) return good();
        const auto response = results.front(); results.pop_front(); return response;
    }
    bool capture() override {
        ++captures;
        if (throw_capture) throw std::runtime_error("Injected capture failure");
        if (cancel_on_capture) cancelled = true;
        return !cancelled;
    }
    bool interrupted() const override { return cancelled; }
    void note(const std::string&) override { ++notes; }
};
Event ack(std::uint64_t offset = 0) { Event event; event.kind = EventKind::Ack; event.offset = offset; return event; }
Event frame(Bytes payload, std::uint8_t address = 0x81, std::uint64_t offset = 1) {
    Bytes wire{0x02, address, static_cast<std::uint8_t>(payload.size()), static_cast<std::uint8_t>(payload.size() >> 8)};
    wire.insert(wire.end(), payload.begin(), payload.end());
    const auto crc = crc16(wire);
    wire.push_back(static_cast<std::uint8_t>(crc)); wire.push_back(static_cast<std::uint8_t>(crc >> 8));
    Decoder decoder;
    auto events = decoder.feed(wire);
    require(events.size() == 1 && events[0].kind == EventKind::Frame, "synthetic frame construction");
    events[0].offset = offset; events[0].frame.offset = offset;
    return events[0];
}
Handshake start_handshake(std::uint64_t boundary = 0) {
    return {Command::Start, boundary, false, false, false, false, {}, {}, {}};
}
} // namespace

int run_sequence_tests() {
    int tests = 0;
    { Fake io; const auto r = run_sequence(io, false);
      require(r.sequence_complete && r.stop_confirmed && io.captures == 1, "default complete sequence");
      require(io.sent == std::vector<Command>{Command::Status, Command::Start, Command::Stop}, "default retains angle"); ++tests; }
    { Fake io; const auto r = run_sequence(io, true);
      require(r.variant_confirmed && r.original.angle_deg == 180 && r.original.resolution_hundredths == 50, "original geometry retained");
      require(io.sent == std::vector<Command>{Command::Status, Command::Variant, Command::Start, Command::Stop}, "optional command order"); ++tests; }
    { Fake io; io.results = {failure(true), failure(true), failure(true)}; const auto r = run_sequence(io, true);
      require(!r.start_attempted && io.sent == std::vector<Command>(3, Command::Status), "three silent status failures abort"); ++tests; }
    { Fake io; io.results = {failure(), good()}; const auto r = run_sequence(io, false);
      require(!r.status_confirmed && io.sent.size() == 1, "partial write/invalid RX does not retry"); ++tests; }
    { Fake io; io.results = {failure(true), good()}; const auto r = run_sequence(io, false);
      require(r.sequence_complete && io.sent.size() == 4 && io.notes == 1, "silent status retry then success"); ++tests; }
    { Fake io; auto initial = good(); initial.status.operating_mode = 0x24; io.results = {initial};
      const auto r = run_sequence(io, true); require(r.status_confirmed && !r.start_attempted && io.sent.size() == 1, "pre-existing continuous mode aborts before settings"); ++tests; }
    { Fake io; io.results = {good(), failure()}; const auto r = run_sequence(io, true);
      require(!r.start_attempted && !r.stop_attempted && io.sent.size() == 2, "variant failure prevents start"); ++tests; }
    { Fake io; io.results = {good(), failure(), good()}; const auto r = run_sequence(io, false);
      require(r.start_attempted && !r.start_confirmed && r.stop_attempted && r.stop_response_valid && !r.stop_confirmed && r.stop_ambiguous, "uncertain start cleanup does not overclaim stop");
      require(io.sent.size() == 3 && io.captures == 0, "uncertain start has one stop and no capture"); ++tests; }
    { Fake io; io.cancel_on_capture = true; const auto r = run_sequence(io, false);
      require(!r.capture_complete && r.stop_confirmed && io.sent.back() == Command::Stop, "Ctrl+C during capture stops"); ++tests; }
    { Fake io; io.cancelled = true; const auto r = run_sequence(io, false);
      require(!r.start_attempted && io.sent.empty(), "Ctrl+C before status sends nothing"); ++tests; }
    { Fake io; io.cancel_after_status = true; const auto r = run_sequence(io, false);
      require(!r.start_attempted && !r.stop_attempted && io.sent.size() == 1, "Ctrl+C before start needs no stop"); ++tests; }
    { Fake io; io.results = {good(), good(), failure()}; const auto r = run_sequence(io, false);
      require(r.stop_attempted && !r.stop_confirmed && io.sent.size() == 3, "failed stop is not blindly retried"); ++tests; }
    { Fake io; io.throw_start = true; const auto r = run_sequence(io, false);
      require(r.start_attempted && r.stop_attempted && !r.stop_confirmed, "exception during ambiguous start invokes cleanup"); ++tests; }
    { Fake io; io.throw_capture = true; const auto r = run_sequence(io, false);
      require(r.start_confirmed && r.stop_confirmed && !r.sequence_complete, "capture exception still stops"); ++tests; }
    { auto h = start_handshake(); h.observe(ack()); h.observe(frame({0xA0,0x00,0x10}));
      require(h.successful(), "ACK then successful A0"); ++tests; }
    { auto h = start_handshake(); h.observe(frame({0xA0,0x00,0x10})); h.observe(ack(10));
      require(!h.successful(), "frame before ACK cannot satisfy handshake"); ++tests; }
    { auto h = start_handshake(100); h.observe(ack(10)); h.observe(frame({0xA0,0x00,0x10},0x81,110));
      require(!h.successful(), "pre-TX ACK excluded"); ++tests; }
    { auto h = start_handshake(100); h.observe(ack(100)); h.observe(frame({0xA0,0x00,0x10},0x81,99));
      require(!h.successful(), "frame beginning before TX boundary excluded"); ++tests; }
    { auto h = start_handshake(); auto ambiguous = ack(); ambiguous.reason = "resync"; h.observe(ambiguous); h.observe(frame({0xA0,0x00,0x10}));
      require(!h.successful(), "ambiguous embedded control cannot satisfy handshake"); ++tests; }
    { auto h = start_handshake(); h.observe(ack()); auto nak = ack(1); nak.kind = EventKind::Nak; h.observe(nak); h.observe(frame({0xA0,0x00,0x10}));
      require(!h.successful(), "NAK prevents success"); ++tests; }
    { auto h = start_handshake(); h.observe(ack()); h.observe(frame({0xA0,0x01,0x10}));
      require(!h.successful() && h.rejected, "A0 result failure gates sequence"); ++tests; }
    { auto h = start_handshake(); h.observe(ack()); h.observe(frame({0xA0,0x00,0x13}));
      require(!h.successful(), "scanner error status gates sequence"); ++tests; }
    { auto h = start_handshake(); h.observe(ack()); h.observe(frame({0xA0,0x00,0x10},0x82));
      require(!h.successful(), "unaccepted address cannot satisfy handshake"); ++tests; }
    { auto h = start_handshake(); h.observe(ack()); h.observe(frame({0xA0,0x00,0x10},0x80));
      require(h.successful(), "address80 accepted along with81"); ++tests; }
    { auto h = start_handshake(); h.observe(ack()); auto recovered = frame({0xA0,0x00,0x10}); recovered.reason = "terminal rescan"; h.observe(recovered);
      require(!h.successful(), "terminal recovery cannot retroactively confirm command"); ++tests; }
    return tests;
}
} // namespace lmsnative
