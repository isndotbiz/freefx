// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// RBJ Audio EQ Cookbook / oversampled waveshaping.

#pragma once

#include <JuceHeader.h>
#include <algorithm>
#include <cmath>
#include <vector>

namespace freefx::dsp
{
class OnePoleLowpass
{
public:
    void prepare (int numChannels, double newSampleRate)
    {
        sampleRate = std::max (newSampleRate, 1.0);
        states.assign (static_cast<size_t> (std::max (numChannels, 0)), 0.0f);
    }

    void reset()
    {
        std::fill (states.begin(), states.end(), 0.0f);
    }

    void setCutoffHz (float cutoffHz)
    {
        if (cutoffHz <= 0.0f)
        {
            enabled = false;
            alpha = 1.0f;
            return;
        }

        enabled = true;
        const auto safeCutoffHz = std::clamp (static_cast<double> (cutoffHz), 1.0, sampleRate * 0.49);
        alpha = static_cast<float> (1.0 - std::exp (-juce::MathConstants<double>::twoPi * safeCutoffHz / sampleRate));
    }

    float processSample (int channel, float input)
    {
        if (! enabled)
            return input;

        auto& state = states[static_cast<size_t> (channel)];
        state += alpha * (input - state);
        return state;
    }

private:
    double sampleRate { 44100.0 };
    float alpha { 1.0f };
    bool enabled { false };
    std::vector<float> states;
};
} // namespace freefx::dsp
