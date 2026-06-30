// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// transient.py (attack/sustain shaper, the SPL Transient Designer principle).
// A fast envelope follower tracks onsets, a slow one tracks the body; their
// dB ratio says whether we are in an attack (fast > slow) or in the sustain
// (slow > fast). The gain is level-independent so it shapes punch without
// behaving like a compressor. Stereo-linked detection. Real-time port: both
// envelope followers and the stereo-linked detector are member state carried
// across processBlock calls, initialised in prepareToPlay. The fast/slow
// follower times (0.5/40 ms and 18/120 ms) are fixed, matching transient.py.

#include <JuceHeader.h>

#include <algorithm>
#include <cmath>

#include "ParameterHelpers.h"

namespace
{
constexpr auto attackId  = "attack";
constexpr auto sustainId = "sustain";
constexpr auto maxDbId   = "maxDb";

// transient.py fixed follower times.
constexpr float fastAttackMs  = 0.5f;
constexpr float fastReleaseMs = 40.0f;
constexpr float slowAttackMs  = 18.0f;
constexpr float slowReleaseMs = 120.0f;

inline float onePoleCoef (float milliseconds, double sampleRate)
{
    if (milliseconds <= 0.0f)
        return 0.0f;
    return static_cast<float> (std::exp (-1.0 / (sampleRate * static_cast<double> (milliseconds) / 1000.0)));
}
} // namespace

class TransientProcessor final : public juce::AudioProcessor
{
public:
    TransientProcessor()
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
            juce::ParameterID { attackId, 1 }, "Attack",
            Range { -24.0f, 24.0f, 0.01f }, 0.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { sustainId, 1 }, "Sustain",
            Range { -24.0f, 24.0f, 0.01f }, 0.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { maxDbId, 1 }, "Max",
            Range { 0.0f, 24.0f, 0.01f }, 12.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int /*maximumExpectedSamplesPerBlock*/) override
    {
        sampleRate = newSampleRate;
        fastAttackCoef  = onePoleCoef (fastAttackMs, sampleRate);
        fastReleaseCoef = onePoleCoef (fastReleaseMs, sampleRate);
        slowAttackCoef  = onePoleCoef (slowAttackMs, sampleRate);
        slowReleaseCoef = onePoleCoef (slowReleaseMs, sampleRate);
        resetState();
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

        const auto numInputChannels  = getTotalNumInputChannels();
        const auto numOutputChannels = getTotalNumOutputChannels();
        for (auto channel = numInputChannels; channel < numOutputChannels; ++channel)
            buffer.clear (channel, 0, buffer.getNumSamples());

        if (numInputChannels <= 0)
            return;

        const auto numSamples = buffer.getNumSamples();
        const auto attackAmt = freefx::dsp::readParameter (parameters, attackId);
        const auto sustainAmt = freefx::dsp::readParameter (parameters, sustainId);
        const auto maxDb = std::max (0.0f, freefx::dsp::readParameter (parameters, maxDbId));

        for (int sample = 0; sample < numSamples; ++sample)
        {
            // Stereo-linked detection: max |x| across channels (matches transient.py).
            float rect = 0.0f;
            for (int channel = 0; channel < numInputChannels; ++channel)
                rect = std::max (rect, std::abs (buffer.getReadPointer (channel)[sample]));

            const auto fastCoef = (rect > fastEnv) ? fastAttackCoef : fastReleaseCoef;
            fastEnv = fastCoef * fastEnv + (1.0f - fastCoef) * rect;
            const auto slowCoef = (rect > slowEnv) ? slowAttackCoef : slowReleaseCoef;
            slowEnv = slowCoef * slowEnv + (1.0f - slowCoef) * rect;

            // >0 -> attack region, <0 -> sustain region.
            const auto diffDb = 20.0f * std::log10 ((fastEnv + 1.0e-9f) / (slowEnv + 1.0e-9f));
            auto gainDb = (diffDb >= 0.0f) ? (attackAmt * diffDb)
                                           : (-sustainAmt * diffDb);
            gainDb = std::clamp (gainDb, -maxDb, maxDb);
            const auto gain = std::pow (10.0f, gainDb / 20.0f);

            for (int channel = 0; channel < numInputChannels; ++channel)
                buffer.getWritePointer (channel)[sample] *= gain;
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-transient"; }
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
    void resetState()
    {
        fastEnv = 1.0e-9f;
        slowEnv = 1.0e-9f;
    }

    double sampleRate { 44100.0 };
    float fastAttackCoef { 0.0f };
    float fastReleaseCoef { 0.0f };
    float slowAttackCoef { 0.0f };
    float slowReleaseCoef { 0.0f };
    float fastEnv { 1.0e-9f };
    float slowEnv { 1.0e-9f };
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TransientProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new TransientProcessor();
}
