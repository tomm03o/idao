cmake_minimum_required(VERSION 3.15)
project(genomic_selection_core VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3 -march=native -fopenmp -Wall -Wextra")

# Find dependencies
find_package(Eigen3 3.3 REQUIRED NO_MODULE)
find_package(OpenMP REQUIRED)
find_package(pybind11 REQUIRED)

# Include directories
include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${EIGEN3_INCLUDE_DIR}
)

# Core library sources
set(CORE_SOURCES
    src/ld_matrix.cpp
    src/ldpred.cpp
    src/grm.cpp
)

# Build static library
add_library(genomic_core STATIC ${CORE_SOURCES})
target_link_libraries(genomic_core
    Eigen3::Eigen
    OpenMP::OpenMP_CXX
)

# Build Python bindings
pybind11_add_module(genomic_core_cpp pybind/bindings.cpp)
target_link_libraries(genomic_core_cpp PRIVATE genomic_core)

# Install targets
install(TARGETS genomic_core_cpp
    LIBRARY DESTINATION ${CMAKE_INSTALL_PREFIX}/lib
)
