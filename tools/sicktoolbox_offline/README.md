# LaViRIA packages for the next session

Both exact repositories requested by the user are downloaded locally and pinned:

| Repository | Local checkout | Commit |
|---|---|---|
| [LaViRIA/sicktoolbox](https://github.com/LaViRIA/sicktoolbox) | `third_party/sicktoolbox-1.0.1` | `2b486d2b3b1299f4401f04c2193f244b594fb532` |
| [LaViRIA/sick_lms200_node](https://github.com/LaViRIA/sick_lms200_node) | `third_party/sick_lms200_node` | `0a8f7f0362bd0373b71f709003f36bace7e7cd54` |

The `sicktoolbox-1.0.1` folder name is intentional: the ROS node's original CMake
expects that sibling directory. The separate `third_party/sicktoolbox` checkout is
the ROS drivers fork and is not a substitute for this dependency.

The permanent local installation is `.local/laviria_lms200` within the repository.
It contains the ROS 2 executable/package, standalone `libSickLMS.a`, C++ headers,
CMake import files and upstream library license. It does not depend on retaining
the temporary compiler build directories for package discovery. Keep the project
at its current path for these prepared commands. The upstream repositories remain
unchanged. Nothing is launched automatically, including after a reboot.

**For tomorrow: software import/build preparation is complete; live scanner use
still has the specific blockers described below.** No live test is scheduled.

From the repository in PowerShell, verify the saved packages without connecting
the scanner:

```powershell
.\tools\sicktoolbox_offline\check-laviria.ps1
```

This checks the two source versions, installed artifact hashes, ROS package
discovery, ELF metadata and the current WSL kernel setting. It does not open a
port, bind/attach USB, start a ROS node, or execute the scanner program. A passing
offline check does not mean hardware communication works.

To import the ROS package in a WSL Ubuntu-24.04 Bash shell:

```bash
cd /mnt/c/Users/Jeffr/OneDrive/Documents/GitHub/Gepruft_Lidar
source tools/sicktoolbox_offline/environment.bash
ros2 pkg prefix sick_lms200_node
ros2 pkg executables sick_lms200_node
```

These commands only load the environment and inspect package metadata. The
expected package prefix ends in `.local/laviria_lms200`; the executable listing
is `sick_lms200_node sick_lms200_node`. No changes to `.bashrc` or system-wide ROS
configuration are required.

For a C++ application built in Linux/WSL, use the SDK's CMake import:

```cmake
find_package(LaViRIASickToolbox CONFIG REQUIRED)
target_link_libraries(your_application PRIVATE LaViRIA::SickLMS)
```

Set `CMAKE_PREFIX_PATH` to this repository's `.local/laviria_lms200` directory.
Include `SickLMS.hh` and use the original `SickToolbox::SickLMS` API. The imported
target supplies the include path, C++17 requirement and POSIX Threads dependency.
This is a Linux SDK; it is not a native Windows COM-port library.

Rebuild commands, if needed, from the repository in WSL Bash:

```bash
bash tools/sicktoolbox_offline/build-laviria-sdk-wsl.sh
bash tools/sicktoolbox_offline/build-ros2-wsl.sh
```

These compile/install files only. Preparation evidence is in
[laviria-install-evidence.json](laviria-install-evidence.json). Full compiler logs
remain in `tmp/laviria-sdk-build.log` and `tmp/laviria-permanent-install.log`.
Sources and the installed package are excluded from Git/Docker contexts; cloning
this project elsewhere would require fetching those pinned vendor repositories
and rebuilding. The files are present on this computer now.

Before a connected session, resolve the verified issues in the
[source and host readiness report](../../docs/SICKTOOLBOX_READINESS.md): the current
WSL kernel lacks Keyspan serial support, the library has an oversized payload
check and automatic baud fallback, and the ROS node's stop service is a no-op.
Those issues were documented, not patched away during import preparation. Start
by establishing a raw, valid status reply through an agreed serial host path;
do not mistake a ROS package listing for a successful scanner response.

When returning, the request can be: “Continue from
`tools/sicktoolbox_offline/README.md`. Review the remaining LaViRIA/Keyspan issues
before any live scanner test.” Reconfirm the connected setup and port at that
time. The earlier COM7 name does not establish tomorrow's device path.
