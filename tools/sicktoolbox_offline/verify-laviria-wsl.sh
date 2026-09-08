#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
install_dir="$repo_dir/.local/laviria_lms200"
binary="$install_dir/lib/sick_lms200_node/sick_lms200_node"

check_source() {
  local directory="$1" expected_url="$2" expected_commit="$3"
  [[ "$(git -C "$directory" remote get-url origin)" == "$expected_url" ]]
  [[ "$(git -C "$directory" rev-parse HEAD)" == "$expected_commit" ]]
  [[ -z "$(git -c core.autocrlf=true -c core.fileMode=false -C "$directory" status --porcelain --untracked-files=no)" ]]
  printf 'Source verified: %s @ %s\n' "$expected_url" "$expected_commit"
}

check_source "$repo_dir/third_party/sicktoolbox-1.0.1" \
  https://github.com/LaViRIA/sicktoolbox.git \
  2b486d2b3b1299f4401f04c2193f244b594fb532
check_source "$repo_dir/third_party/sick_lms200_node" \
  https://github.com/LaViRIA/sick_lms200_node.git \
  0a8f7f0362bd0373b71f709003f36bace7e7cd54

[[ -x "$binary" ]]
expected_sha256=5c0c99c9605e71be32f88c1b4049cc3d7f6399b1864de120b2050fec74eb6c2c
actual_sha256="$(sha256sum "$binary")"
[[ "${actual_sha256%% *}" == "$expected_sha256" ]]
printf 'Installed node SHA256 verified: %s\n' "$expected_sha256"

expected_sdk_sha256=315e51cce6e1007073089e4b7b4abd7eeff59e4c8a9c69ea682e8a9ca2a66ae5
actual_sdk_sha256="$(sha256sum "$install_dir/lib/libSickLMS.a")"
[[ "${actual_sdk_sha256%% *}" == "$expected_sdk_sha256" ]]
for header in SickConfig SickException SickMessage SickBufferMonitor SickLIDAR \
    SickLMS SickLMSMessage SickLMSBufferMonitor SickLMSUtility; do
  [[ -r "$install_dir/include/sicktoolbox/$header.hh" ]]
done
[[ -r "$install_dir/lib/cmake/LaViRIASickToolbox/LaViRIASickToolboxConfig.cmake" ]]
[[ -r "$install_dir/lib/cmake/LaViRIASickToolbox/LaViRIASickToolboxTargets.cmake" ]]
[[ -r "$install_dir/share/laviria_sicktoolbox/COPYING" ]]
printf 'C++ SDK SHA256, nine headers, CMake import and license verified: %s\n' "$expected_sdk_sha256"

source "$repo_dir/tools/sicktoolbox_offline/environment.bash"
# These commands inspect the package index. They do not execute the driver.
package_prefix="$(ros2 pkg prefix sick_lms200_node)"
[[ "$package_prefix" == "$install_dir" ]]
executables="$(ros2 pkg executables sick_lms200_node)"
[[ "$executables" == 'sick_lms200_node sick_lms200_node' ]]
printf 'ROS package prefix: %s\n' "$package_prefix"
printf 'ROS executable registered: %s\n' "$executables"

# Read ELF metadata without invoking the binary or its dynamic loader.
readelf -h "$binary" | sed -n '/Class:/p; /Data:/p; /Machine:/p'
printf 'WSL kernel: '
uname -r
if [[ -r /proc/config.gz ]]; then
  zcat /proc/config.gz | grep -E '^CONFIG_USB_SERIAL_KEYSPAN=|^# CONFIG_USB_SERIAL_KEYSPAN is not set$' || true
fi
printf '\nOffline import/package checks PASSED. No scanner program was run.\n'
printf 'LIVE USE REMAINS UNVERIFIED: review Keyspan kernel support, parser/baud behavior and the no-op ROS stop service.\n'
