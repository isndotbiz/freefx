// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// clipper.py (oversampled soft-tanh / hard clip, drive + ceiling + mix).

#include <JuceHeader.h>

#include "DryDelay.h"
#include "ParameterHelpers.h"

namespace
{
constexpr auto driveId   = "drive";
constexpr auto ceilingId = "ceiling";
constexpr auto hardId    = "hard";
constexpr auto mixId     = "mix";
constexpr int  oversampleFactorLog2 = 2; // 2^2 = 4x oversampling
} // namespace

class ClipperProcessor final : public juce::AudioProcessor
{
public:
    ClipperProcessor()
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
            juce::ParameterID { driveId, 1 }, "Drive",
            Range { 0.0f, 24.0f, 0.01f }, 3.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { ceilingId, 1 }, "Ceiling",
            Range { -24.0f, 0.0f, 0.01f }, -1.0f));
        params.push_back (std::make_unique<juce::AudioParameterBool> (
            juce::ParameterID { hardId, 1 }, "Hard", false));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { mixId, 1 }, "Mix",
            Range { 0.0f, 1.0f, 0.001f }, 1.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int maximumExpectedSamplesPerBlock) override
    {
        sampleRate = newSampleRate;
        const auto channels = static_cast<juce::uint32> (
            juce::jmax (getTotalNumInputChannels(), getTotalNumOutputChannels(), 1));

        oversampler = std::make_unique<juce::dsp::Oversampling<float>> (
            channels,
            oversampleFactorLog2,
            juce::dsp::Oversampling<float>::filterHalfBandPolyphaseIIR);
        oversampler->initProcessing (static_cast<size_t> (juce::jmax (maximumExpectedSamplesPerBlock, 1)));
        oversampler->reset();

        // The oversampler reports a fractional group delay; round to whole samples
        // and delay the dry path by the same amount so the parallel mix stays aligned.
        latencySamples = static_cast<int> (std::lround (oversampler->getLatencyInSamples()));
        setLatencySamples (latencySamples);

        dryDelay.prepare (static_cast<int> (channels), juce::jmax (latencySamples, 1));
        dryDelay.setDelaySamples (latencySamples);
        dryDelay.reset();
    }

    void releaseResources() override
    {
        if (oversampler != nullptr)
            oversampler->reset();
    }

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

        if (oversampler == nullptr)
            return;

        const auto numSamples = buffer.getNumSamples();
        const auto driveGain = freefx::dsp::dbToLinear (freefx::dsp::readParameter (parameters, driveId));
        const auto ceiling   = freefx::dsp::dbToLinear (freefx::dsp::readParameter (parameters, ceilingId));
        const auto hard      = freefx::dsp::readParameter (parameters, hardId) >= 0.5f;
        const auto mix       = freefx::dsp::readParameter (parameters, mixId);

        // Capture the delayed dry signal BEFORE the wet path overwrites the buffer.
        juce::AudioBuffer<float> dryBuffer (numInputChannels, numSamples);
        for (int channel = 0; channel < numInputChannels; ++channel)
        {
            const auto* input = buffer.getReadPointer (channel);
            auto* dry = dryBuffer.getWritePointer (channel);
            for (int sample = 0; sample < numSamples; ++sample)
                dry[sample] = dryDelay.processSample (channel, input[sample]);
        }

        juce::dsp::AudioBlock<float> block (buffer);
        auto oversampledBlock = oversampler->processSamplesUp (block);

        const auto safeCeiling = juce::jmax (ceiling, 1.0e-6f);
        for (size_t channel = 0; channel < oversampledBlock.getNumChannels(); ++channel)
        {
            auto* data = oversampledBlock.getChannelPointer (channel);
            const auto length = oversampledBlock.getNumSamples();
            for (size_t sample = 0; sample < length; ++sample)
            {
                const auto driven = driveGain * data[sample];
                data[sample] = hard
                                   ? juce::jlimit (-safeCeiling, safeCeiling, driven)
                                   : safeCeiling * std::tanh (driven / safeCeiling);
            }
        }

        oversampler->processSamplesDown (block);

        // Parallel (dry/wet) blend against the latency-aligned dry signal.
        for (int channel = 0; channel < numInputChannels; ++channel)
        {
            auto* wet = buffer.getWritePointer (channel);
            const auto* dry = dryBuffer.getReadPointer (channel);
            for (int sample = 0; sample < numSamples; ++sample)
                wet[sample] = (1.0f - mix) * dry[sample] + mix * wet[sample];
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-clipper"; }
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
    double sampleRate { 44100.0 };
    int latencySamples { 0 };
    std::unique_ptr<juce::dsp::Oversampling<float>> oversampler;
    freefx::dsp::DryDelay dryDelay;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ClipperProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new ClipperProcessor();
}
