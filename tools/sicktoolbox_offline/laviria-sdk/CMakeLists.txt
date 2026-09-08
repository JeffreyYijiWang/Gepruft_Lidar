cmake_minimum_required(VERSION 3.16)
project(laviria_lms200_sdk LANGUAGES CXX)

# Build the same three upstream translation units used by the LaViRIA ROS 2
# wrapper. No configure, build, or install step runs a scanner executable.
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  message(FATAL_ERROR "This SickLMS backend requires Linux/POSIX; use the prepared WSL environment.")
endif()
set(LAVIRIA_SICKTOOLBOX_SOURCE
  "${CMAKE_CURRENT_LIST_DIR}/../../../third_party/sicktoolbox-1.0.1"
  CACHE PATH "Pinned LaViRIA SickToolbox checkout")
find_package(Git REQUIRED)
execute_process(
  COMMAND "${GIT_EXECUTABLE}" -C "${LAVIRIA_SICKTOOLBOX_SOURCE}" rev-parse HEAD
  RESULT_VARIABLE source_revision_result OUTPUT_VARIABLE source_revision
  OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_VARIABLE source_revision_error)
if(NOT source_revision_result EQUAL 0 OR
    NOT source_revision STREQUAL "2b486d2b3b1299f4401f04c2193f244b594fb532")
  message(FATAL_ERROR "Unexpected LaViRIA SickToolbox revision: ${source_revision} ${source_revision_error}")
endif()

find_package(Threads REQUIRED)
set(base_dir "${LAVIRIA_SICKTOOLBOX_SOURCE}/c++/drivers/base/src")
set(lms_dir "${LAVIRIA_SICKTOOLBOX_SOURCE}/c++/drivers/lms/sicklms-1.0")
add_library(SickLMS STATIC
  "${lms_dir}/SickLMS.cc"
  "${lms_dir}/SickLMSMessage.cc"
  "${lms_dir}/SickLMSBufferMonitor.cc")
target_compile_features(SickLMS PUBLIC cxx_std_17)
set_target_properties(SickLMS PROPERTIES CXX_EXTENSIONS OFF)
target_include_directories(SickLMS PUBLIC
  "$<BUILD_INTERFACE:${base_dir}>"
  "$<BUILD_INTERFACE:${lms_dir}>"
  "$<INSTALL_INTERFACE:include/sicktoolbox>")
target_link_libraries(SickLMS PUBLIC Threads::Threads)

install(TARGETS SickLMS EXPORT LaViRIASickToolboxTargets ARCHIVE DESTINATION lib)
install(EXPORT LaViRIASickToolboxTargets NAMESPACE LaViRIA::
  DESTINATION lib/cmake/LaViRIASickToolbox)
install(FILES "${CMAKE_CURRENT_LIST_DIR}/LaViRIASickToolboxConfig.cmake"
  DESTINATION lib/cmake/LaViRIASickToolbox)
install(FILES
  "${base_dir}/SickConfig.hh"
  "${base_dir}/SickException.hh"
  "${base_dir}/SickMessage.hh"
  "${base_dir}/SickBufferMonitor.hh"
  "${base_dir}/SickLIDAR.hh"
  "${lms_dir}/SickLMS.hh"
  "${lms_dir}/SickLMSMessage.hh"
  "${lms_dir}/SickLMSBufferMonitor.hh"
  "${lms_dir}/SickLMSUtility.hh"
  DESTINATION include/sicktoolbox)
# COPYING includes the upstream copyright notice and full BSD3-clause terms.
install(FILES "${LAVIRIA_SICKTOOLBOX_SOURCE}/COPYING"
  "${LAVIRIA_SICKTOOLBOX_SOURCE}/AUTHORS"
  DESTINATION share/laviria_sicktoolbox)
