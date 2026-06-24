// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// RBJ Audio EQ Cookbook / oversampled waveshaping.

#pragma once

#include <JuceHeader.h>
#include <cmath>

namespace freefx::dsp
{
inline float dbToLinear (float db)
{
    return std::pow (10.0f, db / 20.0f);
}

inline float readParameter (juce::AudioProcessorValueTreeState& parameters, const char* parameterId)
{
    return parameters.getRawParameterValue (parameterId)->load();
}

inline juce::NormalisableRange<float> skewedRange (float start, float end, float interval, float skew)
{
    juce::NormalisableRange<float> range { start, end, interval };
    range.setSkewForCentre (skew);
    return range;
}
} // namespace freefx::dsp
