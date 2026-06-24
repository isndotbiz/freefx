// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// duck.py (sidechain ducking / pump via an envelope follower on a trigger key).
//
// Sidechain note: duck.py keys off an external trigger file, or — when none is
// given — self-keys on the input's own low end (a 120 Hz low-pass). A VST3 host
// can route a sidechain bus, but to keep this build self-contained and to match
// duck.py's documented fallback, this port self-keys on the low band of the
// main input. The envelope follower and gain-smoother states are carried across
// processBlock so the pump is continuous.

#include <JuceHeader.h>
#include <cmath>

#include "Biquad.h"
#include "ParameterHelpers.h"

namespace
{
constexpr auto thresholdId = "threshold";
constexpr auto amountId    = "amount";    // max duck depth in dB
constexpr auto attackId    = "attackMs";
constexpr auto releaseId   = "releaseMs";
} // namespace

class DuckProcessor final : public juce::AudioProcessor
{
public:
    DuckProcessor()
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
            juce::ParameterID { thresholdId, 1 }, "Threshold",
            Range { -60.0f, 0.0f, 0.01f }, -30.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { amountId, 1 }, "Amount",
            Range { 0.0f, 24.0f, 0.01f }, 9.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { attackId, 1 }, "Attack",
            freefx::dsp::skewedRange (0.1f, 100.0f, 0.01f, 5.0f), 2.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { releaseId, 1 }, "Release",
            freefx::dsp::skewedRange (5.0f, 1000.0f, 0.1f, 180.0f), 180.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int) override
    {
        sampleRate = juce::jmax (newSampleRate, 1.0);
        keyLowpass.prepare (1);
        keyLowpass.reset();
        keyLowpass.setCoefficients (freefx::dsp::makeBiquad (
            freefx::dsp::BiquadKind::lpf, 120.0f, 0.0f, 0.707f, sampleRate));
        env = 1.0e-9f;
        gain = 1.0f;
    }

    void releaseResources() override {}

    bool isBusesLayoutSupported (const BusesLayout& layouts) const override
    {
        const auto& mainOut = layouts.getMainOutputChannelSet();
        if (mainOut != juce::AudioChannelSet::mono() && mainOut != juce::AudioChannelSet::stereo())
            return false;
        return mainOut == layouts.getMainInputChannelSet();
    }

    static float coefFromMs (float ms, double sr)
    {
        return ms > 0.0f ? static_cast<float> (std::exp (-1.0 / (sr * ms / 1000.0))) : 0.0f;
    }

    void processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&) override
    {
        juce::ScopedNoDenormals noDenormals;

        const auto numInputChannels = getTotalNumInputChannels();
        const auto numOutputChannels = getTotalNumOutputChannels();
        for (auto channel = numInputChannels; channel < numOutputChannels; ++channel)
            buffer.clear (channel, 0, buffer.getNumSamples());

        const auto thresholdDb = freefx::dsp::readParameter (parameters, thresholdId);
        const auto amountDb    = freefx::dsp::readParameter (parameters, amountId);
        const auto atkC = coefFromMs (freefx::dsp::readParameter (parameters, attackId), sampleRate);
        const auto relC = coefFromMs (freefx::dsp::readParameter (parameters, releaseId), sampleRate);

        const auto numSamples = buffer.getNumSamples();
        const auto duckTarget = std::pow (10.0f, -amountDb / 20.0f); // gain when fully ducked

        for (int sample = 0; sample < numSamples; ++sample)
        {
            // Self-key on the max-abs across channels, low-passed to the low band
            // (mirrors duck.py's butter low-pass of max|x| fallback path).
            float maxAbs = 0.0f;
            for (int channel = 0; channel < numInputChannels; ++channel)
                maxAbs = juce::jmax (maxAbs, std::abs (buffer.getReadPointer (channel)[sample]));

            const auto keyLow = std::abs (keyLowpass.processSample (0, maxAbs));

            // Envelope follower (attack when rising, release when falling).
            const auto rect = keyLow;
            const auto envC = rect > env ? atkC : relC;
            env = envC * env + (1.0f - envC) * rect;

            const auto overDb = 20.0f * std::log10 (env + 1.0e-12f) - thresholdDb;
            const auto target = overDb > 0.0f ? duckTarget : 1.0f;

            // Smooth the gain itself (attack toward a deeper duck, release back up).
            const auto gainC = target < gain ? atkC : relC;
            gain = gainC * gain + (1.0f - gainC) * target;

            for (int channel = 0; channel < numInputChannels; ++channel)
                buffer.getWritePointer (channel)[sample] *= gain;
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-duck"; }
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
    float env { 1.0e-9f };
    float gain { 1.0f };
    freefx::dsp::BiquadFilter keyLowpass;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (DuckProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new DuckProcessor();
}
