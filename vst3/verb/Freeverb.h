// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// verb.py (public-domain Freeverb topology).

#pragma once

#include <JuceHeader.h>

#include <algorithm>
#include <array>
#include <vector>

namespace freefx::verb
{
constexpr std::array<int, 8> combTunings { 1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617 };
constexpr std::array<int, 4> allpassTunings { 556, 441, 341, 225 };
constexpr int stereoSpread = 23;
constexpr float fixedGain = 0.015f;

class LowpassFeedbackComb
{
public:
    void prepare (int delaySamples)
    {
        buffer.assign (static_cast<size_t> (std::max (delaySamples, 1)), 0.0f);
        index = 0;
        filterStore = 0.0f;
    }

    void reset()
    {
        std::fill (buffer.begin(), buffer.end(), 0.0f);
        index = 0;
        filterStore = 0.0f;
    }

    float processSample (float input, float feedback, float damping)
    {
        auto& delayed = buffer[static_cast<size_t> (index)];
        const auto output = delayed;
        filterStore = output * (1.0f - damping) + filterStore * damping;
        delayed = input + filterStore * feedback;
        index = (index + 1) % static_cast<int> (buffer.size());
        return output;
    }

private:
    std::vector<float> buffer;
    int index { 0 };
    float filterStore { 0.0f };
};

class Allpass
{
public:
    void prepare (int delaySamples)
    {
        buffer.assign (static_cast<size_t> (std::max (delaySamples, 1)), 0.0f);
        index = 0;
    }

    void reset()
    {
        std::fill (buffer.begin(), buffer.end(), 0.0f);
        index = 0;
    }

    float processSample (float input)
    {
        auto& delayed = buffer[static_cast<size_t> (index)];
        const auto bufferOutput = delayed;
        const auto output = -input + bufferOutput;
        delayed = input + bufferOutput * 0.5f;
        index = (index + 1) % static_cast<int> (buffer.size());
        return output;
    }

private:
    std::vector<float> buffer;
    int index { 0 };
};

class Channel
{
public:
    void prepare (double sampleRate, bool right)
    {
        const auto scale = static_cast<float> (sampleRate / 44100.0);
        for (size_t i = 0; i < combs.size(); ++i)
        {
            const auto spread = right ? stereoSpread : 0;
            combs[i].prepare (juce::jmax (1, static_cast<int> (std::lround (
                static_cast<float> (combTunings[i] + spread) * scale))));
        }

        for (size_t i = 0; i < allpasses.size(); ++i)
        {
            const auto spread = right ? stereoSpread : 0;
            allpasses[i].prepare (juce::jmax (1, static_cast<int> (std::lround (
                static_cast<float> (allpassTunings[i] + spread) * scale))));
        }
    }

    void reset()
    {
        for (auto& comb : combs)
            comb.reset();
        for (auto& allpass : allpasses)
            allpass.reset();
    }

    float processSample (float input, float feedback, float damping)
    {
        auto output = 0.0f;
        for (auto& comb : combs)
            output += comb.processSample (input, feedback, damping);
        for (auto& allpass : allpasses)
            output = allpass.processSample (output);
        return output;
    }

private:
    std::array<LowpassFeedbackComb, combTunings.size()> combs;
    std::array<Allpass, allpassTunings.size()> allpasses;
};

class Freeverb
{
public:
    void prepare (double sampleRate)
    {
        left.prepare (sampleRate, false);
        right.prepare (sampleRate, true);
    }

    void reset()
    {
        left.reset();
        right.reset();
    }

    std::array<float, 2> processSample (float leftInput,
                                        float rightInput,
                                        float roomSize,
                                        float damping)
    {
        const auto feedback = roomSize * 0.28f + 0.7f;
        const auto dampValue = damping * 0.4f;
        return {
            left.processSample (leftInput * fixedGain, feedback, dampValue),
            right.processSample (rightInput * fixedGain, feedback, dampValue)
        };
    }

private:
    Channel left;
    Channel right;
};
} // namespace freefx::verb
