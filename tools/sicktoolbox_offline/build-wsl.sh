#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source_dir="$repo_dir/third_party/sicktoolbox"
expected_commit=9ad2fbf962e7ac46991ced5ce81a6536895bed6c
actual_commit="$(git -C "$source_dir" rev-parse HEAD)"
if [[ "$actual_commit" != "$expected_commit" ]]; then
  printf 'Unexpected SickToolbox commit: %s\n' "$actual_commit" >&2
  exit 2
fi
# Windows Git checked these files out with CRLF. Normalize for comparison only;
# do not change the checkout or global Git settings from WSL.
if [[ -n "$(git -c core.autocrlf=true -c core.fileMode=false -C "$source_dir" status --porcelain --untracked-files=no)" ]]; then
  printf 'Upstream SickToolbox source has local changes; review before building.\n' >&2
  exit 2
fi
build_dir="$repo_dir/tmp/sicktoolbox-build"
cmake -S "$repo_dir/tools/sicktoolbox_offline" -B "$build_dir" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$build_dir/install"
cmake --build "$build_dir" --parallel 4
cmake --install "$build_dir"
printf 'Build and local SDK installation complete. No scanner executable was run.\n'
