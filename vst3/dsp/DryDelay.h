// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// RBJ Audio EQ Cookbook / oversampled waveshaping.

#pragma once

#include <algorithm>
#include <vector>

namespace freefx::dsp
{
class DryDelay
{
public:
    void prepare (int numChannels, int maximumDelaySamples)
    {
        delaySamples = std::max (0, maximumDelaySamples);
        const auto bufferLength = static_cast<size_t> (delaySamples + 1);
        buffers.assign (static_cast<size_t> (std::max (numChannels, 0)), std::vector<float> (bufferLength, 0.0f));
        writePositions.assign (static_cast<size_t> (std::max (numChannels, 0)), 0);
    }

    void reset()
    {
        for (auto& buffer : buffers)
            std::fill (buffer.begin(), buffer.end(), 0.0f);

        std::fill (writePositions.begin(), writePositions.end(), 0);
    }

    void setDelaySamples (int newDelaySamples)
    {
        delaySamples = std::clamp (newDelaySamples, 0, static_cast<int> (buffers.empty() ? 0 : buffers.front().size()) - 1);
    }

    float processSample (int channel, float input)
    {
        if (delaySamples <= 0)
            return input;

        auto& buffer = buffers[static_cast<size_t> (channel)];
        auto& writePosition = writePositions[static_cast<size_t> (channel)];
        const auto size = static_cast<int> (buffer.size());
        const auto readPosition = (writePosition - delaySamples + size) % size;
        const auto output = buffer[static_cast<size_t> (readPosition)];

        buffer[static_cast<size_t> (writePosition)] = input;
        writePosition = (writePosition + 1) % size;
        return output;
    }

private:
    int delaySamples { 0 };
    std::vector<std::vector<float>> buffers;
    std::vector<int> writePositions;
};
} // namespace freefx::dsp
