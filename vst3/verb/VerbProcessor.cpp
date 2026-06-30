// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// verb.py (public-domain Freeverb topology with wet predelay).

#include <JuceHeader.h>

#include "DryDelay.h"
#include "Freeverb.h"
#include "ParameterHelpers.h"

#include <algorithm>
#include <cmath>

namespace
{
constexpr auto roomsizeId   = "roomsize";
constexpr auto dampId       = "damp";
constexpr auto wetId        = "wet";
constexpr auto dryId        = "dry";
constexpr auto widthId      = "width";
constexpr auto predelayMsId = "predelayMs";
constexpr auto maxPredelayMs = 100.0f;
} // namespace

class VerbProcessor final : public juce::AudioProcessor
{
public:
    VerbProcessor()
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
            juce::ParameterID { roomsizeId, 1 }, "Roomsize", Range { 0.0f, 1.0f, 0.001f }, 0.6f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { dampId, 1 }, "Damp", Range { 0.0f, 1.0f, 0.001f }, 0.5f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { wetId, 1 }, "Wet", Range { 0.0f, 1.0f, 0.001f }, 0.3f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { dryId, 1 }, "Dry", Range { 0.0f, 1.0f, 0.001f }, 0.7f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { widthId, 1 }, "Width", Range { 0.0f, 1.0f, 0.001f }, 1.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { predelayMsId, 1 }, "Predelay Ms", Range { 0.0f, maxPredelayMs, 0.01f }, 0.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int /*maximumExpectedSamplesPerBlock*/) override
    {
        sampleRate = newSampleRate;
        reverb.prepare (sampleRate);
        reverb.reset();

        const auto maxPredelaySamples = static_cast<int> (std::ceil (sampleRate * maxPredelayMs / 1000.0f));
        wetPredelay.prepare (2, juce::jmax (maxPredelaySamples, 1));
        wetPredelay.reset();
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

        const auto roomsize = freefx::dsp::readParameter (parameters, roomsizeId);
        const auto damp = freefx::dsp::readParameter (parameters, dampId);
        const auto wet = freefx::dsp::readParameter (parameters, wetId);
        const auto dry = freefx::dsp::readParameter (parameters, dryId);
        const auto width = freefx::dsp::readParameter (parameters, widthId);
        const auto predelayMs = freefx::dsp::readParameter (parameters, predelayMsId);
        wetPredelay.setDelaySamples (static_cast<int> (std::lround (sampleRate * predelayMs / 1000.0)));

        const auto wet1 = wet * (width * 0.5f + 0.5f);
        const auto wet2 = wet * ((1.0f - width) * 0.5f);

        const auto numSamples = buffer.getNumSamples();
        auto* left = buffer.getWritePointer (0);
        auto* right = numInputChannels > 1 ? buffer.getWritePointer (1) : nullptr;

        for (int sample = 0; sample < numSamples; ++sample)
        {
            const auto dryLeft = left[sample];
            const auto dryRight = right != nullptr ? right[sample] : dryLeft;
            auto wetPair = reverb.processSample (dryLeft, dryRight, roomsize, damp);
            wetPair[0] = wetPredelay.processSample (0, wetPair[0]);
            wetPair[1] = wetPredelay.processSample (1, wetPair[1]);

            left[sample] = dry * dryLeft + wet1 * wetPair[0] + wet2 * wetPair[1];
            if (right != nullptr)
                right[sample] = dry * dryRight + wet1 * wetPair[1] + wet2 * wetPair[0];
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-verb"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 5.0 + maxPredelayMs / 1000.0; }
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
    double sampleRate { 44100.0 };
    freefx::verb::Freeverb reverb;
    freefx::dsp::DryDelay wetPredelay;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (VerbProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new VerbProcessor();
}
