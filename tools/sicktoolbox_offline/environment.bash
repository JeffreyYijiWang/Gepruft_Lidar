# Source this file in a WSL Bash shell. It loads package metadata only.
# It never launches a ROS node, opens a serial port, or attaches USB.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  printf 'Use: source tools/sicktoolbox_offline/environment.bash\n' >&2
  exit 2
fi

_laviria_repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
_laviria_setup="$_laviria_repo_dir/.local/laviria_lms200/share/sick_lms200_node/local_setup.bash"
if [[ ! -f /opt/ros/jazzy/setup.bash || ! -f "$_laviria_setup" ]]; then
  printf 'Missing Jazzy or local LaViRIA install. See tools/sicktoolbox_offline/README.md.\n' >&2
  unset _laviria_repo_dir _laviria_setup
  return 2
fi

# ROS generated environment hooks access optional unset variables.
_laviria_restore_nounset=false
[[ "$-" == *u* ]] && _laviria_restore_nounset=true
set +u
source /opt/ros/jazzy/setup.bash
source "$_laviria_setup"
if [[ "$_laviria_restore_nounset" == true ]]; then
  set -u
fi
unset _laviria_repo_dir _laviria_setup _laviria_restore_nounset
