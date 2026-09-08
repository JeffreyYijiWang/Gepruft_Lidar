#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
bash "$repo_dir/tools/sicktoolbox_offline/verify-laviria-wsl.sh"
set +u
source /opt/ros/jazzy/setup.bash
set -u
cmake -S "$repo_dir/tools/ros2_status" -B "$repo_dir/tmp/ros2-status-build" \
  -DCMAKE_PREFIX_PATH="$repo_dir/.local/laviria_lms200" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$repo_dir/.local/ros2_status"
cmake --build "$repo_dir/tmp/ros2-status-build" --parallel 4
cmake --install "$repo_dir/tmp/ros2-status-build"
"$repo_dir/.local/ros2_status/lib/lms200_ros2_status/lms200_ros2_status" --self-test
python3 - "$repo_dir" <<'PY'
import hashlib, json, sys
from pathlib import Path
from datetime import datetime, timezone
repo = Path(sys.argv[1])
files = list((repo / 'tools/ros2_status').rglob('*'))
files += list((repo / '.local/laviria_lms200/include/sicktoolbox').glob('*.hh'))
files += [repo / '.local/laviria_lms200/lib/libSickLMS.a',
          repo / '.local/ros2_status/lib/lms200_ros2_status/lms200_ros2_status',
          repo / 'src/lms200/ros2_status_experiment.py']
records = {}
for path in files:
    if path.is_file() and path.name != 'build-evidence.json' and '__pycache__' not in path.parts:
        records[path.relative_to(repo).as_posix()] = {
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'size': path.stat().st_size}
manifest = {'retrieved_or_built_utc': datetime.now(timezone.utc).isoformat(),
            'offline_only': True, 'files': records}
(repo / 'tools/ros2_status/build-evidence.json').write_text(json.dumps(manifest, indent=2)+'\n')
PY
