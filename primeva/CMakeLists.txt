cmake_minimum_required(VERSION 3.20)
project(primeva_core VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

find_package(Threads REQUIRED)

# Bit-exact determinism across platforms: no FMA contraction, no fast-math,
# strict IEEE evaluation. Clients regenerate terrain locally and must match
# the server bit for bit.
if(MSVC)
  set(PRIMEVA_FP_FLAGS /fp:precise /fp:contract-)
  set(PRIMEVA_WARN /W4 /permissive-)
else()
  set(PRIMEVA_FP_FLAGS -ffp-contract=off -fno-fast-math -fexcess-precision=standard)
  if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    set(PRIMEVA_FP_FLAGS -ffp-contract=off -fno-fast-math)
  endif()
  set(PRIMEVA_WARN -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wno-sign-conversion)
endif()

add_library(primeva_core
  core/src/noise.cpp
  core/src/material.cpp
  core/src/biome.cpp
  core/src/macro_map.cpp
  core/src/world_generator.cpp
  core/src/chunk.cpp
  core/src/chunk_codec.cpp
  core/src/voxel_world.cpp
  core/src/mesher.cpp
  core/src/mesh_export.cpp
  core/src/image.cpp
)
target_include_directories(primeva_core PUBLIC core/include)
target_compile_options(primeva_core PRIVATE ${PRIMEVA_WARN} ${PRIMEVA_FP_FLAGS})
target_link_libraries(primeva_core PUBLIC Threads::Threads)

add_executable(primeva_cli tools/primeva_cli.cpp)
target_link_libraries(primeva_cli PRIVATE primeva_core)
target_compile_options(primeva_cli PRIVATE ${PRIMEVA_WARN} ${PRIMEVA_FP_FLAGS})

enable_testing()
add_executable(primeva_tests tests/test_main.cpp tests/test_core.cpp)
target_link_libraries(primeva_tests PRIVATE primeva_core)
target_compile_options(primeva_tests PRIVATE ${PRIMEVA_FP_FLAGS})
add_test(NAME primeva_tests COMMAND primeva_tests)
