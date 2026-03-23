cmake_minimum_required(VERSION 3.10)
project(inference_api)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Add llama.cpp as subdirectory
add_subdirectory(llama.cpp EXCLUDE_FROM_ALL)

# Include directories
include_directories(
    ${CMAKE_SOURCE_DIR}/include
    ${CMAKE_SOURCE_DIR}/llama.cpp/include
    ${CMAKE_SOURCE_DIR}/llama.cpp
    ${CMAKE_SOURCE_DIR}/llama.cpp/ggml/include
)

# Collect all source files
file(GLOB SOURCES
    "src/*.cpp"
    "routes/*.cpp"
)

# Create executable
add_executable(inference_api ${SOURCES})

# Link only the llama library (common is optional/internal)
target_link_libraries(inference_api
    PRIVATE
    llama
)

# Threading support
find_package(Threads REQUIRED)
target_link_libraries(inference_api PRIVATE Threads::Threads)

# Platform-specific libraries
if(APPLE)
    target_link_libraries(inference_api PRIVATE "-framework Accelerate")
elseif(UNIX AND NOT APPLE)
    target_link_libraries(inference_api PRIVATE m)
endif()

# Set output directory
set_target_properties(inference_api PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}
)