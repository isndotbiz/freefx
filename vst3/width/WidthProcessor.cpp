// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// width.py (Mid/Side stereo width + bass mono-maker).
//
// Real-time note: width.py is already causal (an M/S matrix plus a 2nd-order
// Butterworth low-pass on the Side signal). The only state is the crossover
// filter, so this port carries a single biquad across processBlock. Mono input
// stays mono (Side is zero -> nothing to widen).

#include <JuceHeader.h>
#include <vector>

#include "Biquad.h"
#include "ParameterHelpers.h"

namespace
{
constexpr auto widthId  = "width";
constexpr auto monoHzId = "monoHz";
} // namespace

class WidthProcessor final : public juce::AudioProcessor
{
public:
    WidthProcessor()
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
            juce::ParameterID { widthId, 1 }, "Width",
            Range { 0.0f, 2.0f, 0.001f }, 1.2f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { monoHzId, 1 }, "Mono Below",
            freefx::dsp::skewedRange (0.0f, 500.0f, 1.0f, 120.0f), 0.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int) override
    {
        sampleRate = juce::jmax (newSampleRate, 1.0);
        // Two cascaded 1-pole? No — one RBJ 2nd-order LPF matches butter(order=2).
        monoLow.prepare (1);
        monoLow.reset();
        lastMonoHz = -1.0f;
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

        const auto width  = freefx::dsp::readParameter (parameters, widthId);
        const auto monoHz = freefx::dsp::readParameter (parameters, monoHzId);

        // Mono input: no Side content — leave untouched.
        if (numInputChannels < 2)
            return;

        if (monoHz != lastMonoHz)
        {
            if (monoHz > 0.0f)
                monoLow.setCoefficients (freefx::dsp::makeBiquad (
                    freefx::dsp::BiquadKind::lpf, monoHz, 0.0f, 0.70710678f, sampleRate));
            lastMonoHz = monoHz;
        }

        const auto numSamples = buffer.getNumSamples();
        auto* left  = buffer.getWritePointer (0);
        auto* right = buffer.getWritePointer (1);

        for (int sample = 0; sample < numSamples; ++sample)
        {
            const auto l = left[sample];
            const auto r = right[sample];
            const auto mid  = 0.5f * (l + r);
            auto side = 0.5f * (l - r) * width;

            if (monoHz > 0.0f)
            {
                // Remove the low-frequency Side energy -> bass collapses to mono.
                const auto sideLow = monoLow.processSample (0, side);
                side -= sideLow;
            }

            left[sample]  = mid + side;
            right[sample] = mid - side;
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-width"; }
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
    float lastMonoHz { -1.0f };
    freefx::dsp::BiquadFilter monoLow;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (WidthProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new WidthProcessor();
}
