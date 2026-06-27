// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// bitcrush.py (bit-depth quantise, integer sample-and-hold downsample, mix).

#include <JuceHeader.h>

#include "ParameterHelpers.h"

#include <algorithm>
#include <cmath>
#include <vector>

namespace
{
constexpr auto bitsId       = "bits";
constexpr auto downsampleId = "downsample";
constexpr auto mixId        = "mix";
} // namespace

class BitcrushProcessor final : public juce::AudioProcessor
{
public:
    BitcrushProcessor()
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

        params.push_back (std::make_unique<juce::AudioParameterInt> (
            juce::ParameterID { bitsId, 1 }, "Bits", 1, 16, 8));
        params.push_back (std::make_unique<juce::AudioParameterInt> (
            juce::ParameterID { downsampleId, 1 }, "Downsample", 1, 32, 1));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { mixId, 1 }, "Mix", Range { 0.0f, 1.0f, 0.001f }, 1.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double /*newSampleRate*/, int /*maximumExpectedSamplesPerBlock*/) override
    {
        const auto channels = juce::jmax (getTotalNumInputChannels(), getTotalNumOutputChannels(), 1);
        holdCounters.assign (static_cast<size_t> (channels), 0);
        heldValues.assign (static_cast<size_t> (channels), 0.0f);
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

        const auto bits = juce::jlimit (1, 16, static_cast<int> (std::lround (
            freefx::dsp::readParameter (parameters, bitsId))));
        const auto downsample = juce::jlimit (1, 32, static_cast<int> (std::lround (
            freefx::dsp::readParameter (parameters, downsampleId))));
        const auto mix = freefx::dsp::readParameter (parameters, mixId);
        const auto quantiser = static_cast<float> (1 << (bits - 1));

        auto peak = 0.0f;
        const auto numSamples = buffer.getNumSamples();
        for (int channel = 0; channel < numInputChannels; ++channel)
        {
            auto* channelData = buffer.getWritePointer (channel);
            auto& counter = holdCounters[static_cast<size_t> (channel)];
            auto& held = heldValues[static_cast<size_t> (channel)];

            for (int sample = 0; sample < numSamples; ++sample)
            {
                const auto dry = channelData[sample];
                const auto quantised = std::round (dry * quantiser) / quantiser;

                if (downsample <= 1 || counter <= 0)
                {
                    held = quantised;
                    counter = downsample - 1;
                }
                else
                {
                    --counter;
                }

                const auto output = (1.0f - mix) * dry + mix * held;
                channelData[sample] = output;
                peak = juce::jmax (peak, std::abs (output));
            }
        }

        if (peak > 0.999f)
            buffer.applyGain (0, numSamples, 0.999f / peak);
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-bitcrush"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }
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
    std::vector<int> holdCounters;
    std::vector<float> heldValues;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (BitcrushProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new BitcrushProcessor();
}
