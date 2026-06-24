// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// sat.py (oversampled asymmetric-tanh waveshaper, drive + bias + tone + mix).
// NOTE: flutter (modulated fractional delay / tape wow) from sat.py is OUT OF
// SCOPE for this v1 VST3 port — see vst3/README.md.

#include <JuceHeader.h>

#include "DryDelay.h"
#include "ParameterHelpers.h"
#include "ToneFilter.h"

namespace
{
constexpr auto driveId = "drive";
constexpr auto biasId  = "bias";
constexpr auto toneId  = "tone";
constexpr auto mixId   = "mix";
constexpr int  oversampleFactorLog2 = 2; // 2^2 = 4x oversampling
} // namespace

class SatProcessor final : public juce::AudioProcessor
{
public:
    SatProcessor()
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
            Range { 0.0f, 24.0f, 0.01f }, 6.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { biasId, 1 }, "Bias",
            Range { -0.5f, 0.5f, 0.001f }, 0.1f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { toneId, 1 }, "Tone",
            freefx::dsp::skewedRange (0.0f, 20000.0f, 1.0f, 4000.0f), 0.0f)); // 0 = off
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

        latencySamples = static_cast<int> (std::lround (oversampler->getLatencyInSamples()));
        setLatencySamples (latencySamples);

        tone.prepare (static_cast<int> (channels), sampleRate);
        tone.reset();

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
        const auto bias      = freefx::dsp::readParameter (parameters, biasId);
        const auto toneHz    = freefx::dsp::readParameter (parameters, toneId);
        const auto mix       = freefx::dsp::readParameter (parameters, mixId);

        // sat.py unity-ish normalisation: yo /= max(tanh(g + |bias|), 1e-9).
        const auto normaliser = juce::jmax (std::tanh (driveGain + std::abs (bias)), 1.0e-9f);
        const auto biasOffset = std::tanh (bias);

        tone.setCutoffHz (toneHz);

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

        for (size_t channel = 0; channel < oversampledBlock.getNumChannels(); ++channel)
        {
            auto* data = oversampledBlock.getChannelPointer (channel);
            const auto length = oversampledBlock.getNumSamples();
            for (size_t sample = 0; sample < length; ++sample)
            {
                const auto shaped = std::tanh (driveGain * data[sample] + bias) - biasOffset;
                data[sample] = shaped / normaliser;
            }
        }

        oversampler->processSamplesDown (block);

        // Tape HF rolloff at native rate (carries state across blocks).
        for (int channel = 0; channel < numInputChannels; ++channel)
        {
            auto* wet = buffer.getWritePointer (channel);
            for (int sample = 0; sample < numSamples; ++sample)
                wet[sample] = tone.processSample (channel, wet[sample]);
        }

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
    const juce::String getName() const override { return "freefx-sat"; }
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
    freefx::dsp::OnePoleLowpass tone;
    freefx::dsp::DryDelay dryDelay;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SatProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new SatProcessor();
}
