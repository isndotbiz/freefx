// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// RBJ Audio EQ Cookbook (eq.py biquad()). 3-band parametric EQ:
// HPF -> peak -> high-shelf, each a standard RBJ second-order section.

#include <JuceHeader.h>

#include "Biquad.h"
#include "ParameterHelpers.h"

namespace
{
constexpr auto hpfFreqId   = "hpfFreq";
constexpr auto peakFreqId  = "peakFreq";
constexpr auto peakGainId  = "peakGain";
constexpr auto peakQId     = "peakQ";
constexpr auto shelfFreqId = "shelfFreq";
constexpr auto shelfGainId = "shelfGain";
} // namespace

class EqProcessor final : public juce::AudioProcessor
{
public:
    EqProcessor()
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
            juce::ParameterID { hpfFreqId, 1 }, "HPF Freq",
            freefx::dsp::skewedRange (20.0f, 2000.0f, 0.1f, 200.0f), 30.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { peakFreqId, 1 }, "Peak Freq",
            freefx::dsp::skewedRange (40.0f, 18000.0f, 0.1f, 1200.0f), 1000.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { peakGainId, 1 }, "Peak Gain",
            Range { -18.0f, 18.0f, 0.01f }, 0.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { peakQId, 1 }, "Peak Q",
            freefx::dsp::skewedRange (0.1f, 10.0f, 0.001f, 1.0f), 1.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { shelfFreqId, 1 }, "Shelf Freq",
            freefx::dsp::skewedRange (1000.0f, 20000.0f, 0.1f, 8000.0f), 10000.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { shelfGainId, 1 }, "Shelf Gain",
            Range { -18.0f, 18.0f, 0.01f }, 0.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int /*maximumExpectedSamplesPerBlock*/) override
    {
        sampleRate = newSampleRate;
        const auto channels = juce::jmax (getTotalNumInputChannels(), getTotalNumOutputChannels(), 1);
        hpf.prepare (channels);
        peak.prepare (channels);
        shelf.prepare (channels);
        hpf.reset();
        peak.reset();
        shelf.reset();
        updateCoefficients();
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

        updateCoefficients();

        const auto numSamples = buffer.getNumSamples();
        for (int channel = 0; channel < numInputChannels; ++channel)
        {
            auto* channelData = buffer.getWritePointer (channel);
            for (int sample = 0; sample < numSamples; ++sample)
            {
                auto value = hpf.processSample (channel, channelData[sample]);
                value = peak.processSample (channel, value);
                value = shelf.processSample (channel, value);
                channelData[sample] = value;
            }
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-eq"; }
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
    void updateCoefficients()
    {
        const auto hpfFreq   = freefx::dsp::readParameter (parameters, hpfFreqId);
        const auto peakFreq  = freefx::dsp::readParameter (parameters, peakFreqId);
        const auto peakGain  = freefx::dsp::readParameter (parameters, peakGainId);
        const auto peakQ     = freefx::dsp::readParameter (parameters, peakQId);
        const auto shelfFreq = freefx::dsp::readParameter (parameters, shelfFreqId);
        const auto shelfGain = freefx::dsp::readParameter (parameters, shelfGainId);

        hpf.setCoefficients (freefx::dsp::makeBiquad (
            freefx::dsp::BiquadKind::hpf, hpfFreq, 0.0f, 0.707f, sampleRate));
        peak.setCoefficients (freefx::dsp::makeBiquad (
            freefx::dsp::BiquadKind::peak, peakFreq, peakGain, peakQ, sampleRate));
        shelf.setCoefficients (freefx::dsp::makeBiquad (
            freefx::dsp::BiquadKind::highshelf, shelfFreq, shelfGain, 0.707f, sampleRate));
    }

    double sampleRate { 44100.0 };
    freefx::dsp::BiquadFilter hpf;
    freefx::dsp::BiquadFilter peak;
    freefx::dsp::BiquadFilter shelf;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (EqProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new EqProcessor();
}
