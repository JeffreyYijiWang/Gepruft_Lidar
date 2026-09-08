#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
set +u
source /opt/ros/jazzy/setup.bash
set -u
export ROS_LOG_DIR="$repo_dir/tmp/ros2-status-runtime-logs"
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
exec "$repo_dir/.local/ros2_status/lib/lms200_ros2_status/lms200_ros2_status" "$@"
