// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// comp.py (full-band compressor with de-esser mode). Feed-forward soft-knee
// static curve, attack/release envelope, makeup gain, stereo-linked detection
// (one gain applied to both channels so the image stays put). Peak or RMS
// detection. With sidechain HPF > 0 the detector listens only above that
// frequency, turning it into a de-esser / vocal-rider.
//
// Real-time port notes:
//  - Detector envelope, RMS mean-square state, and smoothed gain are member
//    state carried across processBlock calls (init in prepareToPlay).
//  - comp.py's "auto" makeup measures the median gain reduction over the WHOLE
//    file, which is non-causal and impossible per-block in real time. Exposed
//    instead as a plain Makeup parameter in dB (the explicit makeup path the
//    Python also supports). Documented simplification.
//  - The sidechain HPF uses a single RBJ high-pass at Q=0.707, which IS a
//    2nd-order Butterworth high-pass -- exactly comp.py's butter(2, ...).

#include <JuceHeader.h>

#include <algorithm>
#include <cmath>

#include "Biquad.h"
#include "ParameterHelpers.h"

namespace
{
constexpr auto thresholdId = "threshold";
constexpr auto ratioId     = "ratio";
constexpr auto kneeId      = "knee";
constexpr auto attackId    = "attackMs";
constexpr auto releaseId   = "releaseMs";
constexpr auto rmsId       = "rms";
constexpr auto rmsMsId     = "rmsMs";
constexpr auto makeupId    = "makeupDb";
constexpr auto sidechainId = "sidechainHpf";

inline float onePoleCoef (float milliseconds, double sampleRate)
{
    if (milliseconds <= 0.0f)
        return 0.0f;
    return static_cast<float> (std::exp (-1.0 / (sampleRate * static_cast<double> (milliseconds) / 1000.0)));
}
} // namespace

class CompProcessor final : public juce::AudioProcessor
{
public:
    CompProcessor()
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
            Range { -60.0f, 0.0f, 0.01f }, -18.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { ratioId, 1 }, "Ratio",
            freefx::dsp::skewedRange (1.0f, 20.0f, 0.01f, 4.0f), 4.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { kneeId, 1 }, "Knee",
            Range { 0.0f, 24.0f, 0.01f }, 6.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { attackId, 1 }, "Attack",
            freefx::dsp::skewedRange (0.0f, 200.0f, 0.01f, 10.0f), 5.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { releaseId, 1 }, "Release",
            freefx::dsp::skewedRange (1.0f, 2000.0f, 0.01f, 200.0f), 120.0f));
        params.push_back (std::make_unique<juce::AudioParameterBool> (
            juce::ParameterID { rmsId, 1 }, "RMS", false));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { rmsMsId, 1 }, "RMS Window",
            freefx::dsp::skewedRange (1.0f, 100.0f, 0.01f, 10.0f), 10.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { makeupId, 1 }, "Makeup",
            Range { -24.0f, 24.0f, 0.01f }, 0.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { sidechainId, 1 }, "Sidechain HPF",
            freefx::dsp::skewedRange (0.0f, 16000.0f, 0.01f, 4000.0f), 0.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int /*maximumExpectedSamplesPerBlock*/) override
    {
        sampleRate = newSampleRate;
        sidechainHpf.prepare (1);
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

        const auto numSamples  = buffer.getNumSamples();
        const auto thresholdDb = freefx::dsp::readParameter (parameters, thresholdId);
        const auto ratio       = std::max (1.0f, freefx::dsp::readParameter (parameters, ratioId));
        const auto kneeDb      = std::max (0.0f, freefx::dsp::readParameter (parameters, kneeId));
        const auto attackCoef  = onePoleCoef (freefx::dsp::readParameter (parameters, attackId), sampleRate);
        const auto releaseCoef = onePoleCoef (freefx::dsp::readParameter (parameters, releaseId), sampleRate);
        const bool useRms      = freefx::dsp::readParameter (parameters, rmsId) >= 0.5f;
        const auto rmsCoef     = useRms ? onePoleCoef (freefx::dsp::readParameter (parameters, rmsMsId), sampleRate)
                                        : 0.0f;
        const auto makeupGain  = freefx::dsp::dbToLinear (freefx::dsp::readParameter (parameters, makeupId));
        const auto sidechainHz = freefx::dsp::readParameter (parameters, sidechainId);

        const bool sidechainOn = sidechainHz > 0.0f;
        if (sidechainOn)
            sidechainHpf.setCoefficients (freefx::dsp::makeBiquad (
                freefx::dsp::BiquadKind::hpf, sidechainHz, 0.0f, 0.707f, sampleRate));

        const auto slope     = 1.0f / ratio - 1.0f;   // negative
        const auto halfKnee  = kneeDb * 0.5f;

        for (int sample = 0; sample < numSamples; ++sample)
        {
            // Stereo-linked detection: max |x| across channels (matches comp.py).
            float det = 0.0f;
            for (int channel = 0; channel < numInputChannels; ++channel)
                det = std::max (det, std::abs (buffer.getReadPointer (channel)[sample]));

            // De-ess: high-pass the detection signal, then rectify. comp.py applies the
            // butterworth to the already-linked |x| envelope, then takes |.| again.
            if (sidechainOn)
                det = std::abs (sidechainHpf.processSample (0, det));

            float level;
            if (useRms)
            {
                rmsMeanSquare = rmsCoef * rmsMeanSquare + (1.0f - rmsCoef) * det * det;
                level = std::sqrt (rmsMeanSquare);
            }
            else
            {
                const auto envCoef = (det > detectorEnv) ? attackCoef : releaseCoef;
                detectorEnv = envCoef * detectorEnv + (1.0f - envCoef) * det;
                level = detectorEnv;
            }

            const auto levelDb = 20.0f * std::log10 (level + 1.0e-12f);
            const auto over    = levelDb - thresholdDb;

            float grDb;
            if (kneeDb > 0.0f && over >= -halfKnee && over <= halfKnee)
                grDb = slope * (over + halfKnee) * (over + halfKnee) / (2.0f * kneeDb);
            else if (over > 0.0f)
                grDb = slope * over;
            else
                grDb = 0.0f;

            const auto target = std::pow (10.0f, grDb / 20.0f);
            // Smooth the gain itself: attack when clamping harder (target falling), else release.
            const auto gainCoef = (target < smoothedGain) ? attackCoef : releaseCoef;
            smoothedGain = gainCoef * smoothedGain + (1.0f - gainCoef) * target;

            const auto totalGain = smoothedGain * makeupGain;
            for (int channel = 0; channel < numInputChannels; ++channel)
                buffer.getWritePointer (channel)[sample] *= totalGain;
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-comp"; }
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
        detectorEnv   = 1.0e-9f;
        rmsMeanSquare = 1.0e-12f;
        smoothedGain  = 1.0f;
        sidechainHpf.reset();
    }

    double sampleRate { 44100.0 };
    float detectorEnv { 1.0e-9f };
    float rmsMeanSquare { 1.0e-12f };
    float smoothedGain { 1.0f };
    freefx::dsp::BiquadFilter sidechainHpf;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (CompProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new CompProcessor();
}
