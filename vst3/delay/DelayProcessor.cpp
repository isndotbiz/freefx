// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// delay.py (stereo / ping-pong feedback delay — vocal throws).
//
// Real-time note: delay.py runs an offline sample-by-sample feedback recursion
// over the whole buffer (integer delay `d`). Here that becomes a persistent
// per-channel circular delay line carried across processBlock so the feedback
// tail never resets at block boundaries. The `tone` control (delay.py lowpasses
// the signal feeding the line) is realised as a one-pole lowpass in the feedback
// path, so each successive repeat gets darker — the analog/tape-echo intent
// stated in the source docstring.

#include <JuceHeader.h>
#include <vector>

#include "ParameterHelpers.h"
#include "ToneFilter.h"

namespace
{
constexpr auto timeMsId   = "timeMs";
constexpr auto feedbackId = "feedback";
constexpr auto pingpongId = "pingpong";
constexpr auto toneId     = "tone";
constexpr auto mixId      = "mix";

constexpr double maxDelayMs = 2000.0;   // 2s line covers any tempo-throw
} // namespace

class DelayProcessor final : public juce::AudioProcessor
{
public:
    DelayProcessor()
        : juce::AudioProcessor (BusesProperties()
                                    .withInput ("Input", juce::AudioChannelSet::stereo(), true)
                                    .withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
          parameters (*this, nullptr, "PARAMETERS", createLayout())
    {
    }

    static juce::AudioProcessorValueTreeState::ParameterLayout createLayout()
    {
        using Range = juce::NormalisableRange<float>;
        std::vector<std::unique_ptr<juce::RangedAudioParameter>> params;

        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { timeMsId, 1 }, "Time",
            freefx::dsp::skewedRange (1.0f, 2000.0f, 0.1f, 375.0f), 375.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { feedbackId, 1 }, "Feedback",
            Range { 0.0f, 0.95f, 0.001f }, 0.4f));
        params.push_back (std::make_unique<juce::AudioParameterBool> (
            juce::ParameterID { pingpongId, 1 }, "Ping-Pong", false));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { toneId, 1 }, "Tone",
            freefx::dsp::skewedRange (0.0f, 20000.0f, 1.0f, 4000.0f), 0.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { mixId, 1 }, "Mix",
            Range { 0.0f, 1.0f, 0.001f }, 0.3f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int) override
    {
        sampleRate = juce::jmax (newSampleRate, 1.0);
        bufferLength = static_cast<int> (std::ceil (maxDelayMs * sampleRate / 1000.0)) + 4;

        lines.assign (2, std::vector<float> (static_cast<size_t> (bufferLength), 0.0f));
        writePositions.assign (2, 0);
        toneFilter.prepare (2, sampleRate);
        toneFilter.reset();
    }

    void releaseResources() override {}

    bool isBusesLayoutSupported (const BusesLayout& layouts) const override
    {
        const auto& mainOut = layouts.getMainOutputChannelSet();
        if (mainOut != juce::AudioChannelSet::mono() && mainOut != juce::AudioChannelSet::stereo())
            return false;
        return mainOut == layouts.getMainInputChannelSet();
    }

    void processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&) override
    {
        juce::ScopedNoDenormals noDenormals;

        const auto numInputChannels = getTotalNumInputChannels();
        const auto numOutputChannels = getTotalNumOutputChannels();
        for (auto channel = numInputChannels; channel < numOutputChannels; ++channel)
            buffer.clear (channel, 0, buffer.getNumSamples());

        const auto timeMs   = freefx::dsp::readParameter (parameters, timeMsId);
        const auto fb       = juce::jlimit (0.0f, 0.95f, freefx::dsp::readParameter (parameters, feedbackId));
        const auto pingpong = freefx::dsp::readParameter (parameters, pingpongId) > 0.5f;
        const auto tone     = freefx::dsp::readParameter (parameters, toneId);
        const auto mix      = freefx::dsp::readParameter (parameters, mixId);

        toneFilter.setCutoffHz (tone);

        const auto numSamples = buffer.getNumSamples();
        const auto delaySamples = juce::jlimit (1, bufferLength - 1,
                                                static_cast<int> (std::lround (timeMs * sampleRate / 1000.0)));

        // Stereo is processed together so ping-pong can cross the feedback L<->R.
        const bool stereo = numInputChannels >= 2;
        auto* left  = buffer.getWritePointer (0);
        auto* right = stereo ? buffer.getWritePointer (1) : nullptr;

        auto& lineL = lines[0];
        auto& lineR = lines[1];
        auto writeL = writePositions[0];
        auto writeR = writePositions[1];

        for (int sample = 0; sample < numSamples; ++sample)
        {
            const auto readL = wrapIndex (writeL - delaySamples, bufferLength);
            const auto readR = wrapIndex (writeR - delaySamples, bufferLength);

            // Delayed taps, darkened in the feedback path (progressive tape-echo tone).
            auto delayedL = toneFilter.processSample (0, lineL[static_cast<size_t> (readL)]);
            auto delayedR = toneFilter.processSample (1, stereo ? lineR[static_cast<size_t> (readR)] : 0.0f);

            const auto inL = left[sample];
            const auto inR = stereo ? right[sample] : 0.0f;

            if (pingpong && stereo)
            {
                lineL[static_cast<size_t> (writeL)] = inL + fb * delayedR;
                lineR[static_cast<size_t> (writeR)] = inR + fb * delayedL;
            }
            else
            {
                lineL[static_cast<size_t> (writeL)] = inL + fb * delayedL;
                if (stereo)
                    lineR[static_cast<size_t> (writeR)] = inR + fb * delayedR;
            }

            // delay.py keeps the dry at unity and adds the wet (delayed) on top.
            left[sample] = inL + mix * delayedL;
            if (stereo)
                right[sample] = inR + mix * delayedR;

            writeL = wrapIndex (writeL + 1, bufferLength);
            writeR = wrapIndex (writeR + 1, bufferLength);
        }

        writePositions[0] = writeL;
        writePositions[1] = writeR;
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-delay"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return maxDelayMs / 1000.0; }
    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock& destData) override
    {
        if (auto state = parameters.copyState(); state.isValid())
            if (auto xml = state.createXml())
                copyXmlToBinary (*xml, destData);
    }

    void setStateInformation (const void* data, int sizeInBytes) override
    {
        if (auto xml = getXmlFromBinary (data, sizeInBytes))
            if (xml->hasTagName (parameters.state.getType()))
                parameters.replaceState (juce::ValueTree::fromXml (*xml));
    }

private:
    static int wrapIndex (int index, int length)
    {
        index %= length;
        if (index < 0)
            index += length;
        return index;
    }

    double sampleRate { 44100.0 };
    int bufferLength { 1 };
    std::vector<std::vector<float>> lines;
    std::vector<int> writePositions;
    freefx::dsp::OnePoleLowpass toneFilter;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (DelayProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new DelayProcessor();
}
