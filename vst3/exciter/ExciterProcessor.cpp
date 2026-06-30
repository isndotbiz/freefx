// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// exciter.py (HF harmonic exciter -- "air" / sparkle). Split off the highs,
// generate NEW harmonics up there by gently saturating that band (tanh, drive),
// keep only the new highs (high-pass again), level-match the excited band to the
// original HF energy, and blend it back in by (10^(amount/20) - 1). Oversampled
// so the new harmonic content does not alias. Unlike a high-shelf this
// synthesises new upper harmonics, so it reads as "air" rather than an EQ boost.
//
// Real-time port notes:
//  - The two high-pass filters use a single RBJ high-pass at Q=0.707 each, which
//    IS a 2nd-order Butterworth high-pass -- exactly exciter.py's butter(2, ...).
//    Each high-pass carries its own per-channel biquad state across blocks.
//  - The tanh saturation runs inside a juce::dsp::Oversampling stage so the new
//    harmonics are anti-aliased, replacing exciter.py's resample_poly up/down.
//  - exciter.py level-matches the excited band to the original HF using the
//    WHOLE-buffer RMS (np.mean). That is non-causal, so here both bands' RMS are
//    tracked with a one-pole running mean-square envelope and the excited band is
//    scaled to match the original HF energy continuously. Documented adaptation.
//  - origBuffer keeps the un-saturated HF band so its energy is available for the
//    level-match after the in-place oversampled saturation overwrites hfBuffer.

#include <JuceHeader.h>

#include <algorithm>
#include <cmath>
#include <vector>

#include "Biquad.h"
#include "ParameterHelpers.h"

namespace
{
constexpr auto freqId   = "freq";
constexpr auto driveId  = "drive";
constexpr auto amountId = "amount";

constexpr int oversampleFactorLog2 = 2; // 4x, matching exciter.py default

// RMS tracking time constant for the continuous level-match (ms).
constexpr float rmsTimeMs = 50.0f;

inline float onePoleCoef (float milliseconds, double sampleRate)
{
    if (milliseconds <= 0.0f)
        return 0.0f;
    return static_cast<float> (std::exp (-1.0 / (sampleRate * static_cast<double> (milliseconds) / 1000.0)));
}
} // namespace

class ExciterProcessor final : public juce::AudioProcessor
{
public:
    ExciterProcessor()
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
            juce::ParameterID { freqId, 1 }, "Freq",
            freefx::dsp::skewedRange (1000.0f, 16000.0f, 0.1f, 5000.0f), 5000.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { driveId, 1 }, "Drive",
            Range { 0.0f, 24.0f, 0.01f }, 6.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { amountId, 1 }, "Amount",
            Range { 0.0f, 12.0f, 0.01f }, 3.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int maximumExpectedSamplesPerBlock) override
    {
        sampleRate = newSampleRate;
        const auto channels = static_cast<juce::uint32> (
            juce::jmax (getTotalNumInputChannels(), getTotalNumOutputChannels(), 1));

        splitHpf.prepare ((int) channels);
        keepHpf.prepare ((int) channels);
        splitHpf.reset();
        keepHpf.reset();

        oversampler = std::make_unique<juce::dsp::Oversampling<float>> (
            channels,
            oversampleFactorLog2,
            juce::dsp::Oversampling<float>::filterHalfBandPolyphaseIIR);
        oversampler->initProcessing (static_cast<size_t> (juce::jmax (maximumExpectedSamplesPerBlock, 1)));
        oversampler->reset();

        rmsCoef = onePoleCoef (rmsTimeMs, sampleRate);
        originalHfMs.assign ((size_t) channels, 1.0e-12f);
        excitedMs.assign ((size_t) channels, 1.0e-12f);

        const auto maxSamples = juce::jmax (maximumExpectedSamplesPerBlock, 1);
        hfBuffer.setSize ((int) channels, maxSamples, false, false, true);
        origBuffer.setSize ((int) channels, maxSamples, false, false, true);
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

        const auto numInputChannels  = getTotalNumInputChannels();
        const auto numOutputChannels = getTotalNumOutputChannels();
        for (auto channel = numInputChannels; channel < numOutputChannels; ++channel)
            buffer.clear (channel, 0, buffer.getNumSamples());

        if (oversampler == nullptr || numInputChannels <= 0)
            return;

        const auto numSamples = buffer.getNumSamples();
        const auto freq    = freefx::dsp::readParameter (parameters, freqId);
        const auto driveDb = freefx::dsp::readParameter (parameters, driveId);
        const auto amount  = freefx::dsp::readParameter (parameters, amountId);

        const auto hpfCoeffs = freefx::dsp::makeBiquad (
            freefx::dsp::BiquadKind::hpf,
            std::min (freq, static_cast<float> (sampleRate * 0.5 - 1.0)),
            0.0f, 0.707f, sampleRate);
        splitHpf.setCoefficients (hpfCoeffs);
        keepHpf.setCoefficients (hpfCoeffs);

        const auto drive = std::pow (10.0f, driveDb / 20.0f);
        const auto tanhNorm = std::max (std::tanh (drive), 1.0e-9f);
        const auto blend = std::pow (10.0f, amount / 20.0f) - 1.0f;

        hfBuffer.setSize (numInputChannels, numSamples, false, false, true);
        origBuffer.setSize (numInputChannels, numSamples, false, false, true);

        // 1) Split off the highs (original HF band). Keep a clean copy in origBuffer for
        //    the level-match, and the to-be-saturated copy in hfBuffer.
        for (int channel = 0; channel < numInputChannels; ++channel)
        {
            const auto* in = buffer.getReadPointer (channel);
            auto* hf   = hfBuffer.getWritePointer (channel);
            auto* orig = origBuffer.getWritePointer (channel);
            for (int sample = 0; sample < numSamples; ++sample)
            {
                const auto band = splitHpf.processSample (channel, in[sample]);
                hf[sample]   = band;
                orig[sample] = band;
            }
        }

        // 2) Saturate the HF band inside the oversampler to synthesise new harmonics.
        juce::dsp::AudioBlock<float> hfBlock (hfBuffer);
        auto osBlock = oversampler->processSamplesUp (hfBlock);
        for (size_t channel = 0; channel < osBlock.getNumChannels(); ++channel)
        {
            auto* data = osBlock.getChannelPointer (channel);
            const auto length = osBlock.getNumSamples();
            for (size_t sample = 0; sample < length; ++sample)
                data[sample] = std::tanh (drive * data[sample]) / tanhNorm;
        }
        oversampler->processSamplesDown (hfBlock);

        // 3) Keep only the NEW highs (high-pass the saturated band again), level-match
        //    the excited band to the original HF energy via running RMS, and blend in.
        for (int channel = 0; channel < numInputChannels; ++channel)
        {
            auto* out       = buffer.getWritePointer (channel);
            const auto* sat  = hfBuffer.getReadPointer (channel);
            const auto* orig = origBuffer.getReadPointer (channel);
            auto& origMs = originalHfMs[(size_t) channel];
            auto& excMs  = excitedMs[(size_t) channel];

            for (int sample = 0; sample < numSamples; ++sample)
            {
                const auto excited = keepHpf.processSample (channel, sat[sample]);

                origMs = rmsCoef * origMs + (1.0f - rmsCoef) * orig[sample] * orig[sample];
                excMs  = rmsCoef * excMs  + (1.0f - rmsCoef) * excited * excited;

                const auto matchGain = std::sqrt (origMs) / (std::sqrt (excMs) + 1.0e-12f);
                out[sample] += blend * excited * matchGain;
            }
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-exciter"; }
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
    freefx::dsp::BiquadFilter splitHpf;
    freefx::dsp::BiquadFilter keepHpf;
    std::unique_ptr<juce::dsp::Oversampling<float>> oversampler;
    float rmsCoef { 0.0f };
    std::vector<float> originalHfMs;
    std::vector<float> excitedMs;
    juce::AudioBuffer<float> hfBuffer;
    juce::AudioBuffer<float> origBuffer;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ExciterProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new ExciterProcessor();
}
