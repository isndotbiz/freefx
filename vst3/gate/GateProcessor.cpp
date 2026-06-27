// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// gate.py (noise gate / downward expander). Below the threshold the gain is
// reduced (hard gate at high range, gentle expander at low range); above it the
// signal passes. Stereo-linked detection (one gain for both channels), an
// attack/release-smoothed gain, and a hold counter that keeps the gate open
// through short dips. Real-time port: the detector envelope, the smoothed gain,
// and the hold counter are member state carried across processBlock calls and
// initialised in prepareToPlay.

#include <JuceHeader.h>

#include <algorithm>
#include <cmath>

#include "ParameterHelpers.h"

namespace
{
constexpr auto thresholdId = "threshold";
constexpr auto rangeId     = "range";
constexpr auto ratioId     = "ratio";
constexpr auto attackId    = "attackMs";
constexpr auto holdId      = "holdMs";
constexpr auto releaseId   = "releaseMs";

// One-pole smoothing coefficient matching gate.py coef():
//   exp(-1 / (fs * ms / 1000)). ms <= 0 -> 0 (instant).
inline float onePoleCoef (float milliseconds, double sampleRate)
{
    if (milliseconds <= 0.0f)
        return 0.0f;
    return static_cast<float> (std::exp (-1.0 / (sampleRate * static_cast<double> (milliseconds) / 1000.0)));
}
} // namespace

class GateProcessor final : public juce::AudioProcessor
{
public:
    GateProcessor()
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
            Range { -80.0f, 0.0f, 0.01f }, -45.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { rangeId, 1 }, "Range",
            Range { 0.0f, 80.0f, 0.01f }, 40.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { ratioId, 1 }, "Ratio",
            freefx::dsp::skewedRange (1.0f, 20.0f, 0.01f, 4.0f), 4.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { attackId, 1 }, "Attack",
            freefx::dsp::skewedRange (0.0f, 100.0f, 0.01f, 5.0f), 1.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { holdId, 1 }, "Hold",
            freefx::dsp::skewedRange (0.0f, 500.0f, 0.01f, 50.0f), 30.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { releaseId, 1 }, "Release",
            freefx::dsp::skewedRange (1.0f, 1000.0f, 0.01f, 120.0f), 120.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int /*maximumExpectedSamplesPerBlock*/) override
    {
        sampleRate = newSampleRate;
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
        const auto thresholdDb = freefx::dsp::readParameter (parameters, thresholdId);
        const auto rangeDb     = std::max (0.0f, freefx::dsp::readParameter (parameters, rangeId));
        const auto ratio       = std::max (1.0f, freefx::dsp::readParameter (parameters, ratioId));
        const auto attackCoef  = onePoleCoef (freefx::dsp::readParameter (parameters, attackId), sampleRate);
        const auto releaseCoef = onePoleCoef (freefx::dsp::readParameter (parameters, releaseId), sampleRate);
        const auto holdSamples = static_cast<int> (sampleRate
            * static_cast<double> (freefx::dsp::readParameter (parameters, holdId)) / 1000.0);

        const auto floorGain = std::pow (10.0f, -rangeDb / 20.0f);

        for (int sample = 0; sample < numSamples; ++sample)
        {
            // Stereo-linked detection: max |x| across channels (matches gate.py).
            float rect = 0.0f;
            for (int channel = 0; channel < numInputChannels; ++channel)
                rect = std::max (rect, std::abs (buffer.getReadPointer (channel)[sample]));

            const auto envCoef = (rect > detectorEnv) ? attackCoef : releaseCoef;
            detectorEnv = envCoef * detectorEnv + (1.0f - envCoef) * rect;
            const auto envDb = 20.0f * std::log10 (detectorEnv + 1.0e-12f);

            float target;
            if (envDb >= thresholdDb)
            {
                target = 1.0f;
                holdCounter = holdSamples;
            }
            else if (holdCounter > 0)
            {
                target = 1.0f;
                --holdCounter;
            }
            else
            {
                const auto under  = thresholdDb - envDb;
                const auto grDb   = -std::min (rangeDb, under * (ratio - 1.0f));
                target = std::max (floorGain, std::pow (10.0f, grDb / 20.0f));
            }

            // Smooth the gain itself: attack when opening (target rising), release when closing.
            const auto gainCoef = (target > smoothedGain) ? attackCoef : releaseCoef;
            smoothedGain = gainCoef * smoothedGain + (1.0f - gainCoef) * target;

            for (int channel = 0; channel < numInputChannels; ++channel)
                buffer.getWritePointer (channel)[sample] *= smoothedGain;
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-gate"; }
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
        detectorEnv  = 1.0e-9f;
        smoothedGain = std::pow (10.0f, -std::max (0.0f, freefx::dsp::readParameter (parameters, rangeId)) / 20.0f);
        holdCounter  = 0;
    }

    double sampleRate { 44100.0 };
    float detectorEnv { 1.0e-9f };
    float smoothedGain { 0.01f };
    int holdCounter { 0 };
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (GateProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new GateProcessor();
}
