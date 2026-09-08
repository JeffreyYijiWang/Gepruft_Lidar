#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source_dir="$repo_dir/third_party/sicktoolbox-1.0.1"
expected_commit=2b486d2b3b1299f4401f04c2193f244b594fb532
[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$expected_commit" ]]
[[ -z "$(git -c core.autocrlf=true -c core.fileMode=false -C "$source_dir" status --porcelain --untracked-files=no)" ]]
build_dir="$repo_dir/tmp/laviria-sdk-build"
install_dir="$repo_dir/.local/laviria_lms200"
cmake -S "$repo_dir/tools/sicktoolbox_offline/laviria-sdk" -B "$build_dir" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$install_dir"
cmake --build "$build_dir" --parallel 4
cmake --install "$build_dir"
[[ -z "$(git -c core.autocrlf=true -c core.fileMode=false -C "$source_dir" status --porcelain --untracked-files=no)" ]]
sha256sum "$install_dir/lib/libSickLMS.a"
printf 'LaViRIA C++ SDK built and locally installed. No scanner executable was run.\n'
