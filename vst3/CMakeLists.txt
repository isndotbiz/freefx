# MIT License
#
# Copyright (c) 2026 Jonathan Mallinger
#
# Part of the freefx open-source effects suite; clean-room DSP ported from
# RBJ Audio EQ Cookbook / oversampled waveshaping.

cmake_minimum_required(VERSION 3.22)

project(freefx_vst3 VERSION 1.0.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Pull JUCE in-tree so the build is fully self-contained (no system install).
# Bump GIT_TAG here if 8.0.4 ever fails to clone/build.
include(FetchContent)
FetchContent_Declare(
    JUCE
    GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
    GIT_TAG        8.0.4
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(JUCE)

# Shared, header-only DSP layer used by every plugin target.
add_library(freefx_dsp INTERFACE)
target_include_directories(freefx_dsp INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/dsp)

# ---------------------------------------------------------------------------
# Helper that wires one freefx plugin target with our common settings.
# ---------------------------------------------------------------------------
function(freefx_add_plugin target productName pluginCode)
    juce_add_plugin(${target}
        PRODUCT_NAME       "${productName}"
        COMPANY_NAME       "freefx"
        BUNDLE_ID          "biz.isn.freefx.${target}"
        PLUGIN_MANUFACTURER_CODE Frfx
        PLUGIN_CODE        ${pluginCode}
        FORMATS            VST3
        IS_SYNTH           FALSE
        NEEDS_MIDI_INPUT   FALSE
        NEEDS_MIDI_OUTPUT  FALSE
        VST3_CATEGORIES    "Fx"
        COPY_PLUGIN_AFTER_BUILD FALSE
    )

    target_sources(${target} PRIVATE ${ARGN})

    # Generates the umbrella "JuceHeader.h" the processor sources include.
    juce_generate_juce_header(${target})

    target_compile_definitions(${target} PUBLIC
        JUCE_WEB_BROWSER=0
        JUCE_USE_CURL=0
        JUCE_VST3_CAN_REPLACE_VST2=0
        JUCE_DISPLAY_SPLASH_SCREEN=0
    )

    target_link_libraries(${target} PRIVATE
        freefx_dsp
        juce::juce_audio_utils
        juce::juce_dsp
        PUBLIC
        juce::juce_recommended_config_flags
        juce::juce_recommended_lto_flags
        juce::juce_recommended_warning_flags
    )
endfunction()

freefx_add_plugin(freefx_eq      "freefx-eq"      Feq1 ${CMAKE_CURRENT_SOURCE_DIR}/eq/EqProcessor.cpp)
freefx_add_plugin(freefx_clipper "freefx-clipper" Fclp ${CMAKE_CURRENT_SOURCE_DIR}/clipper/ClipperProcessor.cpp)
freefx_add_plugin(freefx_sat     "freefx-sat"     Fsat ${CMAKE_CURRENT_SOURCE_DIR}/sat/SatProcessor.cpp)
