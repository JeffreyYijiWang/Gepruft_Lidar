#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
node_dir="$repo_dir/third_party/sick_lms200_node"
toolbox_dir="$repo_dir/third_party/sicktoolbox-1.0.1"

check_source() {
  local source_dir="$1" expected_commit="$2" actual_commit
  actual_commit="$(git -C "$source_dir" rev-parse HEAD)"
  if [[ "$actual_commit" != "$expected_commit" ]]; then
    printf 'Unexpected commit in %s: %s\n' "$source_dir" "$actual_commit" >&2
    exit 2
  fi
  # Account for the Windows checkout without changing source or Git settings.
  if [[ -n "$(git -c core.autocrlf=true -c core.fileMode=false -C "$source_dir" status --porcelain --untracked-files=no)" ]]; then
    printf 'Upstream source has local changes: %s\n' "$source_dir" >&2
    exit 2
  fi
  printf 'Source: %s at %s\n' "$source_dir" "$actual_commit"
}

check_source "$node_dir" 0a8f7f0362bd0373b71f709003f36bace7e7cd54
check_source "$toolbox_dir" 2b486d2b3b1299f4401f04c2193f244b594fb532
# This sources the installed ROS environment, never a scanner executable.
set +u
source /opt/ros/jazzy/setup.bash
set -u
build_dir="$repo_dir/tmp/ros2-lms200-build"
install_dir="$repo_dir/.local/laviria_lms200"
cmake -S "$node_dir" -B "$build_dir" \
  -DBUILD_TESTING=OFF -DCMAKE_CXX_STANDARD=17 -DCMAKE_CXX_STANDARD_REQUIRED=ON \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$install_dir"
cmake --build "$build_dir" --parallel 4
cmake --install "$build_dir"
check_source "$node_dir" 0a8f7f0362bd0373b71f709003f36bace7e7cd54
check_source "$toolbox_dir" 2b486d2b3b1299f4401f04c2193f244b594fb532
printf 'Compiler: '
c++ --version | head -n 1
sha256sum "$(readlink -f "$(command -v c++)")" \
  "$build_dir/sick_lms200_node" \
  "$install_dir/lib/sick_lms200_node/sick_lms200_node"
printf 'ROS 2 compile and local staging complete. No node or scanner executable was run.\n'
