#pragma once
#include "protocol.hpp"
#include <string>

namespace lmsnative {
enum class Command { Status, Variant, Start, Stop };
const char* command_name(Command command);
Bytes command_bytes(Command command);

// No serial transaction IDs exist. The receive boundary excludes earlier bytes;
// it is a correlation rule, not proof of which command caused a later reply.
struct Handshake {
    Command command;
    std::uint64_t first_offset;
    bool ack = false, nak = false, reply = false, rejected = false;
    Frame frame;
    StatusInfo status;
    std::string reason;
    void observe(const Event& event);
    bool successful() const { return ack && reply && !nak && !rejected; }
};

struct Exchange {
    bool success = false;
    bool write_attempted = false;
    bool may_retry = false; // Only a complete, drained status write with no RX.
    StatusInfo status;
    std::string reason;
};
struct SequenceResult {
    std::string stage = "status", reason;
    StatusInfo original;
    bool status_confirmed = false, variant_requested = false, variant_confirmed = false;
    bool start_attempted = false, start_confirmed = false, capture_complete = false;
    bool stop_attempted = false, stop_response_valid = false, stop_confirmed = false;
    bool stop_ambiguous = false, sequence_complete = false;
};
class SequenceIO {
public:
    virtual ~SequenceIO() = default;
    virtual Exchange exchange(Command command, bool cleanup = false) = 0;
    virtual bool capture() = 0; // Exactly 10 s from confirmed start; cancel may shorten it.
    virtual bool interrupted() const = 0;
    virtual void note(const std::string& text) = 0;
};
SequenceResult run_sequence(SequenceIO& io, bool set_variant);
int run_sequence_tests();
} // namespace lmsnative
