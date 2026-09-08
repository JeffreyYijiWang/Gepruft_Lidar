// Project-owned supervised diagnostic. The pinned LaViRIA repositories are unchanged.
// The Windows relay is the sole COM7 owner; this process opens only a Linux PTY.
#include <rclcpp/rclcpp.hpp>
#include "SickLMS.hh"
#include "SickLMSMessage.hh"

#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <functional>
#include <iomanip>
#include <iostream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <fcntl.h>
#include <poll.h>
#include <sys/stat.h>
#include <termios.h>
#include <unistd.h>

namespace fs = std::filesystem;
using Bytes = std::vector<uint8_t>;
using Clock = std::chrono::steady_clock;
using SickToolbox::SickLMSMessage;

namespace {
constexpr std::array<uint8_t, 7> kStatus{0x02, 0x00, 0x01, 0x00, 0x31, 0x15, 0x12};
constexpr auto kReceiveWindow = std::chrono::seconds(6);
constexpr auto kOverallLimit = std::chrono::seconds(660);

std::string quoted(const std::string &value) {
  std::ostringstream out;
  out << '"';
  for (unsigned char ch : value) {
    if (ch == '"' || ch == '\\') out << '\\' << ch;
    else if (ch < 0x20) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(ch);
    else out << ch;
  }
  out << '"';
  return out.str();
}

std::string hex(const Bytes &bytes) {
  std::ostringstream out;
  out << std::hex << std::uppercase << std::setfill('0');
  for (size_t i = 0; i < bytes.size(); ++i) {
    if (i) out << ' ';
    out << std::setw(2) << unsigned(bytes[i]);
  }
  return out.str();
}

std::string utc_now() {
  const auto now = std::chrono::system_clock::now();
  const auto millis = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch());
  const auto seconds = std::chrono::duration_cast<std::chrono::seconds>(millis);
  const std::time_t stamp = seconds.count();
  std::tm utc{};
  gmtime_r(&stamp, &utc);
  std::ostringstream out;
  out << std::put_time(&utc, "%Y-%m-%dT%H:%M:%S") << '.'
      << std::setw(3) << std::setfill('0') << (millis - seconds).count() << 'Z';
  return out.str();
}

[[noreturn]] void system_error(const std::string &action) {
  const int code = errno;
  throw std::runtime_error(action + ": " + std::strerror(code) + " (errno " + std::to_string(code) + ")");
}

void write_all(int fd, const std::string &text) {
  size_t offset = 0;
  while (offset < text.size()) {
    const auto count = ::write(fd, text.data() + offset, text.size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) system_error("write evidence");
    offset += static_cast<size_t>(count);
  }
}

class Journal {
 public:
  explicit Journal(const fs::path &path) {
    fd_ = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd_ < 0) system_error("create exclusive ROS evidence");
  }
  ~Journal() { if (fd_ >= 0) ::close(fd_); }
  Journal(const Journal &) = delete;
  Journal &operator=(const Journal &) = delete;
  void event(const std::string &name, const std::string &fields = "") {
    std::string line = "{\"timestamp_utc\":" + quoted(utc_now()) +
      ",\"event\":" + quoted(name);
    if (!fields.empty()) line += ',' + fields;
    write_all(fd_, line + "}\n");
    if (::fsync(fd_) != 0) system_error("sync ROS evidence");
  }
 private:
  int fd_{-1};
};

Bytes build_frame(uint8_t address, const Bytes &payload) {
  if (payload.empty() || payload.size() > SickLMSMessage::MESSAGE_PAYLOAD_MAX_LENGTH)
    throw std::runtime_error("Refusing out-of-bounds library BuildMessage input");
  SickLMSMessage message;
  message.BuildMessage(address, payload.data(), static_cast<unsigned int>(payload.size()));
  Bytes bytes(message.GetMessageLength());
  message.GetMessage(bytes.data());
  return bytes;
}

struct Observation {
  std::string kind;
  Bytes bytes;
  size_t offset{0};
  bool post_tx{false};
  size_t declared_payload{0};
  bool crc_ok{false};
  uint16_t wire_crc{0};
  uint16_t calculated_crc{0};
  bool status_layout{false};
};

// No idle deadline and no frame-local read: incomplete bytes live until the whole
// supervised capture ends. Control bytes are recognized only outside a candidate.
class Accumulator {
 public:
  explicit Accumulator(std::function<void(const Observation &)> observe)
      : observe_(std::move(observe)) {}
  void mark_tx_boundary() { tx_boundary_ = received_; }
  void feed(const Bytes &bytes) {
    pending_.insert(pending_.end(), bytes.begin(), bytes.end());
    received_ += bytes.size();
    while (!pending_.empty()) {
      Observation item;
      item.offset = consumed_;
      item.post_tx = tx_boundary_ && consumed_ >= *tx_boundary_;
      if (pending_[0] != 0x02) {
        item.bytes = {pending_[0]};
        item.kind = pending_[0] == 0x06 ? "ack" : pending_[0] == 0x15 ? "nak" : "noise";
        observe_(item);
        consume(1);
        continue;
      }
      if (pending_.size() < 2) return;
      if (pending_[1] != 0x80 && pending_[1] != 0x81) {
        item.kind = "unrecognized_stx";
        item.bytes = {pending_[0]};
        observe_(item);
        consume(1);
        continue;
      }
      if (pending_.size() < 4) return;
      const size_t length = pending_[2] | (size_t(pending_[3]) << 8);
      item.declared_payload = length;
      if (length == 0 || length > SickLMSMessage::MESSAGE_PAYLOAD_MAX_LENGTH) {
        item.kind = "invalid_length";
        item.bytes.assign(pending_.begin(), pending_.begin() + 4);
        observe_(item);
        consume(4);
        continue;
      }
      const size_t total = length + 6;
      if (pending_.size() < total) return;
      item.kind = "frame";
      item.bytes.assign(pending_.begin(), pending_.begin() + total);
      const Bytes payload(pending_.begin() + 4, pending_.begin() + 4 + length);
      const Bytes rebuilt = build_frame(pending_[1], payload);
      item.wire_crc = item.bytes[total - 2] | (uint16_t(item.bytes[total - 1]) << 8);
      item.calculated_crc = rebuilt[total - 2] | (uint16_t(rebuilt[total - 1]) << 8);
      item.crc_ok = item.wire_crc == item.calculated_crc;
      item.status_layout = payload[0] == 0xB1 && (length == 148 || length == 154);
      observe_(item);
      // A complete candidate's payload is never reclassified as standalone ACK.
      // Bad candidates remain fully available in the preceding raw evidence.
      consume(total);
    }
  }
  const Bytes &pending() const { return pending_; }
  size_t received() const { return received_; }
 private:
  void consume(size_t count) {
    pending_.erase(pending_.begin(), pending_.begin() + count);
    consumed_ += count;
  }
  std::function<void(const Observation &)> observe_;
  Bytes pending_;
  size_t received_{0};
  size_t consumed_{0};
  std::optional<size_t> tx_boundary_;
};

class StatusPort : public SickToolbox::SickLMS {
 public:
  explicit StatusPort(const std::string &path) : SickLMS(path) {
    // Calling neither Initialize nor the inherited setup avoids scanner baud writes,
    // fallback search, buffer purges and the vendor monitor's parser.
    _sick_fd = ::open(path.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW);
    if (_sick_fd < 0) system_error("open PTY");
    try {
      if (::tcgetattr(_sick_fd, &_old_term) != 0) system_error("read PTY termios");
      termios desired = _old_term;
      ::cfmakeraw(&desired);
      desired.c_cflag &= ~(CSIZE | PARENB | PARODD | CSTOPB | CRTSCTS);
      desired.c_cflag |= CS8 | CLOCAL | CREAD;
      desired.c_iflag &= ~(IXON | IXOFF | IXANY);
      desired.c_cc[VMIN] = 0;
      desired.c_cc[VTIME] = 0;
      if (::cfsetispeed(&desired, B9600) != 0 || ::cfsetospeed(&desired, B9600) != 0)
        system_error("set PTY baud");
      if (::tcsetattr(_sick_fd, TCSANOW, &desired) != 0) system_error("configure PTY");
      termios actual{};
      if (::tcgetattr(_sick_fd, &actual) != 0) system_error("read back PTY termios");
      if ((actual.c_cflag & CSIZE) != CS8 ||
          (actual.c_cflag & (PARENB | CSTOPB | CRTSCTS)) ||
          (actual.c_iflag & (IXON | IXOFF | IXANY)) ||
          (actual.c_lflag & (ICANON | ECHO | ISIG)) ||
          (actual.c_oflag & OPOST) ||
          ::cfgetispeed(&actual) != B9600 || ::cfgetospeed(&actual) != B9600)
        throw std::runtime_error("PTY termios readback mismatch");
    } catch (...) {
      ::close(_sick_fd);
      _sick_fd = -1;
      throw;
    }
  }
  ~StatusPort() override { close_owned(); }
  int fd() const { return _sick_fd; }
  void send_status_once() {
    if (sent_) throw std::runtime_error("Second transmission prohibited");
    sent_ = true;  // A failed/partial write is also never retried.
    const uint8_t command = 0x31;
    SickLMSMessage message;
    message.BuildMessage(0x00, &command, 1);
    Bytes serialized(message.GetMessageLength());
    message.GetMessage(serialized.data());
    if (serialized != Bytes(kStatus.begin(), kStatus.end()))
      throw std::runtime_error("LaViRIA status bytes differ from manual vector");
    try {
      _sendMessage(message, 0);  // Original library performs one checked write of all 7 bytes.
    } catch (const SickToolbox::SickException &error) {
      // The legacy exception inherits std::exception privately, so normalize it
      // explicitly to preserve its actual reason in our evidence and main handler.
      throw std::runtime_error(std::string("LaViRIA status write failed: ") + error.what());
    }
  }
  bool close_owned() noexcept {
    const int fd = _sick_fd;
    _sick_fd = -1;
    // Keep false: the base destructor must not close our descriptor a second time.
    _sick_initialized = false;
    return fd < 0 || ::close(fd) == 0;
  }
 private:
  bool sent_{false};
};

void create_ready(const fs::path &directory) {
  const auto temporary = directory / ("ros2.ready.tmp." + std::to_string(::getpid()));
  const int fd = ::open(temporary.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
  if (fd < 0) system_error("create temporary ready marker");
  try {
    write_all(fd, "{\"timestamp_utc\":" + quoted(utc_now()) + ",\"state\":\"passive_reader_armed\"}\n");
    if (::fsync(fd) != 0) system_error("sync ready marker");
    ::close(fd);
  } catch (...) {
    ::close(fd);
    ::unlink(temporary.c_str());
    throw;
  }
  // link() publishes a complete marker atomically and refuses to replace a file.
  if (::link(temporary.c_str(), (directory / "ros2.ready").c_str()) != 0) {
    const int code = errno;
    ::unlink(temporary.c_str());
    errno = code;
    system_error("publish ready marker");
  }
  ::unlink(temporary.c_str());
}

bool trigger_exists(const fs::path &path) {
  const auto status = fs::symlink_status(path);
  if (!fs::exists(status)) return false;
  if (!fs::is_regular_file(status)) throw std::runtime_error("Trigger must be a regular file: " + path.string());
  return true;
}

class StatusNode : public rclcpp::Node {
 public:
  StatusNode() : Node("lms200_ros2_status") {}
  int run(const std::string &port_name, const fs::path &directory) {
    Journal journal(directory / "ros2-events.jsonl");
    journal.event("run_started", "\"port\":" + quoted(port_name) +
      ",\"overall_limit_seconds\":660,\"receive_window_seconds\":6,\"backend\":\"LaViRIA_library_status_only\"");
    bool ack = false, nak = false, valid_status = false, valid_status_after_ack = false;
    size_t frame_count = 0, bad_crc_count = 0;
    Accumulator incoming([&](const Observation &item) {
      const auto truth = [](bool value) { return value ? "true" : "false"; };
      std::string fields = "\"hex\":" + quoted(hex(item.bytes)) + ",\"offset\":" + std::to_string(item.offset) +
        ",\"post_tx\":" + truth(item.post_tx);
      if (item.kind == "frame") {
        fields += ",\"declared_payload\":" + std::to_string(item.declared_payload) +
          ",\"total_length\":" + std::to_string(item.bytes.size()) +
          ",\"address\":" + std::to_string(item.bytes[1]) +
          ",\"command\":" + std::to_string(item.bytes[4]) +
          ",\"crc_valid\":" + truth(item.crc_ok) +
          ",\"wire_crc\":" + std::to_string(item.wire_crc) +
          ",\"calculated_crc\":" + std::to_string(item.calculated_crc) +
          ",\"status_layout_valid\":" + truth(item.status_layout);
        if (item.crc_ok) ++frame_count; else ++bad_crc_count;
        if (item.post_tx && item.crc_ok && item.status_layout) {
          valid_status = true;
          if (ack) valid_status_after_ack = true;
        }
      }
      if (item.post_tx && item.kind == "ack") ack = true;
      if (item.post_tx && item.kind == "nak") nak = true;
      journal.event(item.kind, fields);
    });
    std::optional<Clock::time_point> sent_at;
    const auto overall_deadline = Clock::now() + kOverallLimit;
    bool closed = false;
    try {
      StatusPort port(port_name);
      journal.event("pty_open", "\"baud\":9600,\"data_bits\":8,\"parity\":\"none\",\"stop_bits\":1,\"flow_control\":\"none\",\"termios_readback\":true");
      create_ready(directory);
      journal.event("reader_ready", "\"commands_sent\":0");
      RCLCPP_INFO(get_logger(), "Passive ROS 2 PTY reader ready; waiting for external status trigger.");
      bool cancelled = false, overall_timeout = false;
      while (true) {
        const auto now = Clock::now();
        if (!rclcpp::ok() || trigger_exists(directory / "cancel.trigger")) { cancelled = true; break; }
        if (sent_at && now - *sent_at >= kReceiveWindow) break;
        if (now >= overall_deadline) { overall_timeout = true; break; }
        pollfd descriptor{port.fd(), POLLIN, 0};
        const int available = ::poll(&descriptor, 1, 25);
        if (available < 0 && errno == EINTR) continue;
        if (available < 0) system_error("poll PTY");
        bool received_this_iteration = false;
        if (descriptor.revents & POLLIN) {
          std::array<uint8_t, 4096> data{};
          const auto count = ::read(port.fd(), data.data(), data.size());
          if (count < 0 && errno != EAGAIN && errno != EINTR) system_error("read PTY");
          if (count > 0) {
            received_this_iteration = true;
            Bytes chunk(data.begin(), data.begin() + count);
            journal.event("rx_raw", "\"count\":" + std::to_string(count) +
              ",\"hex\":" + quoted(hex(chunk)) + ",\"offset\":" + std::to_string(incoming.received()) +
              ",\"phase\":" + quoted(sent_at ? "post_tx" : "passive"));
            incoming.feed(chunk);  // Evidence is persisted before any parser invocation.
          }
        }
        if (descriptor.revents & (POLLERR | POLLHUP | POLLNVAL))
          throw std::runtime_error("PTY disconnected or reported a poll error");
        if (!sent_at && !received_this_iteration && trigger_exists(directory / "status.trigger")) {
          if (!rclcpp::ok() || trigger_exists(directory / "cancel.trigger")) { cancelled = true; break; }
          if (Clock::now() + kReceiveWindow >= overall_deadline) { overall_timeout = true; break; }
          // Parent creates this only after the physical startup gates. No trigger
          // is ever created here, and there is no automatic scanner command.
          incoming.mark_tx_boundary();
          journal.event("library_tx_requested", "\"count\":7,\"hex\":\"02 00 01 00 31 15 12\",\"receive_boundary\":" + std::to_string(incoming.received()));
          port.send_status_once();
          sent_at = Clock::now();
          journal.event("library_tx_completed", "\"checked_pty_write_count\":7,\"native_transmission_evidence\":\"Windows relay journal\"");
        }
      }
      closed = port.close_owned();
      journal.event("pty_closed", std::string("\"success\":") + (closed ? "true" : "false"));
      const bool success = sent_at && !cancelled && !overall_timeout && closed && ack && !nak && valid_status_after_ack;
      journal.event("result", std::string("\"success\":") + (success ? "true" : "false") +
        ",\"sent\":" + (sent_at ? "true" : "false") + ",\"rx_count\":" + std::to_string(incoming.received()) +
        ",\"ack\":" + (ack ? "true" : "false") + ",\"nak\":" + (nak ? "true" : "false") +
        ",\"valid_status\":" + (valid_status ? "true" : "false") +
        ",\"valid_status_after_ack\":" + (valid_status_after_ack ? "true" : "false") +
        ",\"valid_frames\":" + std::to_string(frame_count) + ",\"invalid_crc_frames\":" + std::to_string(bad_crc_count) +
        ",\"pending_hex\":" + quoted(hex(incoming.pending())) +
        ",\"post_send_seconds\":" + (sent_at ? std::to_string(std::chrono::duration<double>(Clock::now() - *sent_at).count()) : "null") +
        ",\"cancelled\":" + (cancelled ? "true" : "false") + ",\"overall_timeout\":" + (overall_timeout ? "true" : "false"));
      return success ? 0 : 3;
    } catch (const SickToolbox::SickException &error) {
      journal.event("error", "\"message\":" + quoted(error.what()) + ",\"port_raii_cleanup_completed\":true");
      throw std::runtime_error(std::string("LaViRIA library exception: ") + error.what());
    } catch (const std::exception &error) {
      // The port's RAII destructor has closed its owned descriptor before here.
      journal.event("error", "\"message\":" + quoted(error.what()) + ",\"port_raii_cleanup_completed\":true");
      throw;
    }
  }
};

int self_test() {
  size_t checks = 0;
  const auto require = [&](bool condition, const std::string &label) {
    if (!condition) throw std::runtime_error("Self-test failed: " + label);
    ++checks;
  };
  require(build_frame(0x00, {0x31}) == Bytes(kStatus.begin(), kStatus.end()), "manual status request bytes/CRC");
  // SICK June 2001 Quick Manual p9: complete original startup telegram.
  const Bytes startup{0x02,0x81,0x17,0x00,0x90,0x4C,0x4D,0x53,0x32,0x30,0x30,0x3B,0x33,0x30,0x31,0x30,0x36,0x33,0x3B,0x56,0x30,0x32,0x2E,0x30,0x36,0x20,0x13,0x64,0x5A};
  require(build_frame(0x81, Bytes(startup.begin()+4, startup.end()-2)) == startup, "manual startup CRC using actual 81 address");
  std::vector<Observation> observations;
  const auto reset = [&] { observations.clear(); };
  const auto observe = [&](const Observation &item) { observations.push_back(item); };
  Accumulator original(observe);
  original.feed(startup);
  require(observations.size() == 1 && observations[0].crc_ok && !observations[0].post_tx, "passive startup frame");
  for (const uint8_t address : {0x80, 0x81}) {
    for (const size_t length : {148U, 154U}) {
      Bytes payload(length, 0); payload[0] = 0xB1;
      // Synthetic status fixture: layout/CRC only, not actual scanner status.
      const auto status = build_frame(address, payload);
      for (size_t split = 0; split <= status.size(); ++split) {
        reset(); Accumulator parser(observe); parser.mark_tx_boundary();
        parser.feed({0x06});
        parser.feed(Bytes(status.begin(), status.begin() + split));
        parser.feed({});
        parser.feed(Bytes(status.begin() + split, status.end()));
        require(observations.size() == 2 && observations[0].kind == "ack" && observations[1].crc_ok &&
          observations[1].status_layout && observations[1].post_tx && parser.pending().empty(), "all two-part splits / both response addresses and status layouts");
      }
    }
  }
  reset(); Accumulator delayed(observe);
  delayed.feed(Bytes(startup.begin(), startup.begin() + 9));
  std::this_thread::sleep_for(std::chrono::milliseconds(600));
  delayed.feed({});
  delayed.feed(Bytes(startup.begin() + 9, startup.end()));
  require(observations.size() == 1 && observations[0].crc_ok, "600 ms gap retains partial telegram");
  reset(); Accumulator noise(observe); noise.mark_tx_boundary();
  noise.feed({0xC0,0x39,0x14,0x31,0x21,0x31,0x01,0x15});
  require(observations.size() == 8 && observations.back().kind == "nak" &&
    std::none_of(observations.begin(), observations.end(), [](const auto &item) { return item.kind == "frame"; }), "noise is not a frame; standalone NAK");
  reset(); Accumulator malformed(observe);
  malformed.feed({0x02,0x81,0x2D,0x03,0x02,0x80,0x00,0x00});  // 813 and zero, both invalid.
  require(observations.size() == 2 && observations[0].kind == "invalid_length" && observations[1].kind == "invalid_length", "length bounds before library operations");
  reset(); Accumulator corrupt(observe);
  Bytes bad = startup; bad.back() ^= 1; corrupt.feed(bad);
  require(observations.size() == 1 && !observations[0].crc_ok, "CRC mismatch rejected");
  reset(); Accumulator embedded(observe);
  embedded.feed(build_frame(0x81, {0x90,0x06,0x15}));
  require(observations.size() == 1 && observations[0].kind == "frame", "payload ACK/NAK not controls");
  reset(); Accumulator stale(observe);
  stale.feed(Bytes(startup.begin(), startup.begin()+8)); stale.mark_tx_boundary();
  stale.feed(Bytes(startup.begin()+8, startup.end()));
  require(observations.size() == 1 && !observations[0].post_tx, "pre-TX frame does not become post-TX reply");
  reset(); Accumulator unsupported(observe);
  unsupported.feed(build_frame(0x81, {0xB1,0x00}));
  require(observations.size() == 1 && observations[0].crc_ok && !observations[0].status_layout, "unsupported B1 layout rejected");
  std::cout << "{\"self_test\":\"passed\",\"checks\":" << checks
            << ",\"serial_opened\":false,\"ros_initialized\":false}\n";
  return 0;
}

void validate_paths(const std::string &port, const fs::path &directory) {
  const std::string prefix = "/dev/pts/";
  if (port.rfind(prefix, 0) != 0 || port.size() == prefix.size() ||
      !std::all_of(port.begin()+prefix.size(), port.end(), [](unsigned char ch) { return ch >= '0' && ch <= '9'; }))
    throw std::runtime_error("Only a relay PTY path /dev/pts/N is permitted");
  if (!directory.is_absolute() || !fs::is_directory(directory))
    throw std::runtime_error("--run-dir must name an existing absolute directory");
  for (const char *name : {"ros2-events.jsonl", "ros2.ready", "status.trigger", "cancel.trigger"}) {
    if (fs::exists(fs::symlink_status(directory / name)))
      throw std::runtime_error(std::string("Fresh run required; existing ") + name);
  }
}
}  // namespace

int main(int argc, char **argv) {
  try {
    if (argc == 2 && std::string(argv[1]) == "--self-test") return self_test();
    std::string port, run_dir;
    for (int i = 1; i < argc; ++i) {
      const std::string argument(argv[i]);
      if (argument == "--port" && i + 1 < argc && port.empty()) port = argv[++i];
      else if (argument == "--run-dir" && i + 1 < argc && run_dir.empty()) run_dir = argv[++i];
      else throw std::runtime_error("Usage: lms200_ros2_status --port /dev/pts/N --run-dir ABS | --self-test");
    }
    if (port.empty() || run_dir.empty()) throw std::runtime_error("Both --port and --run-dir are required");
    validate_paths(port, run_dir);
    rclcpp::init(argc, argv);
    int result;
    try { result = std::make_shared<StatusNode>()->run(port, run_dir); }
    catch (...) { rclcpp::shutdown(); throw; }
    rclcpp::shutdown();
    return result;
  } catch (const std::exception &error) {
    std::cerr << "lms200_ros2_status: " << error.what() << '\n';
    return 2;
  } catch (...) {
    std::cerr << "lms200_ros2_status: unknown library exception; no automatic retry\n";
    return 2;
  }
}
