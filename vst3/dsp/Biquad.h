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
enum class BiquadKind
{
    peak,
    hpf,
    lpf,
    highshelf
};

struct BiquadCoefficients
{
    float b0 { 1.0f };
    float b1 { 0.0f };
    float b2 { 0.0f };
    float a1 { 0.0f };
    float a2 { 0.0f };
};

inline BiquadCoefficients makeBiquad (BiquadKind kind,
                                      float frequencyHz,
                                      float gainDb,
                                      float q,
                                      double sampleRate)
{
    const auto safeSampleRate = std::max (sampleRate, 1.0);
    const auto safeFrequencyHz = std::clamp (static_cast<double> (frequencyHz), 1.0, safeSampleRate * 0.49);
    const auto safeQ = std::max (static_cast<double> (q), 0.05);
    const auto w0 = juce::MathConstants<double>::twoPi * safeFrequencyHz / safeSampleRate;
    const auto cw = std::cos (w0);
    const auto sw = std::sin (w0);
    const auto alpha = sw / (2.0 * safeQ);
    const auto amplitude = std::pow (10.0, static_cast<double> (gainDb) / 40.0);

    double b0 = 1.0;
    double b1 = 0.0;
    double b2 = 0.0;
    double a0 = 1.0;
    double a1 = 0.0;
    double a2 = 0.0;

    switch (kind)
    {
        case BiquadKind::peak:
            b0 = 1.0 + alpha * amplitude;
            b1 = -2.0 * cw;
            b2 = 1.0 - alpha * amplitude;
            a0 = 1.0 + alpha / amplitude;
            a1 = -2.0 * cw;
            a2 = 1.0 - alpha / amplitude;
            break;

        case BiquadKind::hpf:
            b0 = (1.0 + cw) * 0.5;
            b1 = -(1.0 + cw);
            b2 = (1.0 + cw) * 0.5;
            a0 = 1.0 + alpha;
            a1 = -2.0 * cw;
            a2 = 1.0 - alpha;
            break;

        case BiquadKind::lpf:
            b0 = (1.0 - cw) * 0.5;
            b1 = 1.0 - cw;
            b2 = (1.0 - cw) * 0.5;
            a0 = 1.0 + alpha;
            a1 = -2.0 * cw;
            a2 = 1.0 - alpha;
            break;

        case BiquadKind::highshelf:
        {
            const auto shelfAlpha = 2.0 * std::sqrt (amplitude) * alpha;
            b0 = amplitude * ((amplitude + 1.0) + (amplitude - 1.0) * cw + shelfAlpha);
            b1 = -2.0 * amplitude * ((amplitude - 1.0) + (amplitude + 1.0) * cw);
            b2 = amplitude * ((amplitude + 1.0) + (amplitude - 1.0) * cw - shelfAlpha);
            a0 = (amplitude + 1.0) - (amplitude - 1.0) * cw + shelfAlpha;
            a1 = 2.0 * ((amplitude - 1.0) - (amplitude + 1.0) * cw);
            a2 = (amplitude + 1.0) - (amplitude - 1.0) * cw - shelfAlpha;
            break;
        }
    }

    return {
        static_cast<float> (b0 / a0),
        static_cast<float> (b1 / a0),
        static_cast<float> (b2 / a0),
        static_cast<float> (a1 / a0),
        static_cast<float> (a2 / a0)
    };
}

struct BiquadState
{
    float z1 { 0.0f };
    float z2 { 0.0f };

    void reset()
    {
        z1 = 0.0f;
        z2 = 0.0f;
    }

    float process (float input, const BiquadCoefficients& coefficients)
    {
        const auto output = coefficients.b0 * input + z1;
        z1 = coefficients.b1 * input - coefficients.a1 * output + z2;
        z2 = coefficients.b2 * input - coefficients.a2 * output;
        return output;
    }
};

class BiquadFilter
{
public:
    void prepare (int numChannels)
    {
        states.assign (static_cast<size_t> (std::max (numChannels, 0)), {});
    }

    void reset()
    {
        for (auto& state : states)
            state.reset();
    }

    void setCoefficients (BiquadCoefficients newCoefficients)
    {
        coefficients = newCoefficients;
    }

    float processSample (int channel, float input)
    {
        return states[static_cast<size_t> (channel)].process (input, coefficients);
    }

private:
    BiquadCoefficients coefficients;
    std::vector<BiquadState> states;
};
} // namespace freefx::dsp
