cmake_minimum_required(VERSION 3.16)
project(lms200_sicktoolbox_offline LANGUAGES CXX)

# Compile upstream LMS2xx code without requiring its ROS 1/catkin build.
# No configure, build or install step runs a driver or opens a serial port.
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  message(FATAL_ERROR "This upstream serial backend requires Linux/POSIX. Use the prepared WSL build; Windows COM ports are not Linux tty devices.")
endif()
set(SICKTOOLBOX_SOURCE "${CMAKE_CURRENT_LIST_DIR}/../../third_party/sicktoolbox" CACHE PATH "Pinned upstream checkout")
find_package(Threads REQUIRED)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(SickLMS2xx STATIC
  "${SICKTOOLBOX_SOURCE}/c++/drivers/lms2xx/sicklms2xx/SickLMS2xx.cc"
  "${SICKTOOLBOX_SOURCE}/c++/drivers/lms2xx/sicklms2xx/SickLMS2xxBufferMonitor.cc"
  "${SICKTOOLBOX_SOURCE}/c++/drivers/lms2xx/sicklms2xx/SickLMS2xxMessage.cc")
target_include_directories(SickLMS2xx PUBLIC "${SICKTOOLBOX_SOURCE}/include")
target_link_libraries(SickLMS2xx PUBLIC Threads::Threads)

# Keep upstream sources and their behavior unchanged for comparison.
foreach(example IN ITEMS lms2xx_simple_app lms2xx_config lms2xx_mean_values
    lms2xx_partial_scan lms2xx_real_time_indices lms2xx_set_variant
    lms2xx_stream_range_and_reflect lms2xx_subrange)
  add_executable(${example} "${SICKTOOLBOX_SOURCE}/c++/examples/lms2xx/${example}/src/main.cc")
  target_link_libraries(${example} PRIVATE SickLMS2xx)
endforeach()

install(TARGETS SickLMS2xx ARCHIVE DESTINATION lib)
install(DIRECTORY "${SICKTOOLBOX_SOURCE}/include/sicktoolbox" DESTINATION include)
install(FILES "${SICKTOOLBOX_SOURCE}/COPYING" DESTINATION share/sicktoolbox)
