// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// deesser.py (split de-esser: band-pass the sibilance band, follow its energy,
// and duck only that band so "sss"/"shh" stop spitting without dulling the rest).
//
// Real-time note: deesser.py band-passes the whole file, takes max|band| as the
// detector, computes a gain-reduction envelope, then reconstructs
// y = x - band + band*g. Here the band is extracted per-sample with a persistent
// 2nd-order band-pass (HPF then LPF) per channel, the detector envelope is
// carried across blocks, and the same split reconstruction is applied.

#include <JuceHeader.h>
#include <cmath>

#include "Biquad.h"
#include "ParameterHelpers.h"

namespace
{
constexpr auto freqId      = "freq";       // sibilance band center
constexpr auto thresholdId = "threshold";
constexpr auto ratioId     = "ratio";
constexpr auto rangeId     = "range";      // max reduction dB
constexpr auto attackId    = "attackMs";
constexpr auto releaseId   = "releaseMs";
constexpr auto listenId    = "listen";     // bool: output the detection band only
} // namespace

class DeesserProcessor final : public juce::AudioProcessor
{
public:
    DeesserProcessor()
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
            freefx::dsp::skewedRange (2000.0f, 12000.0f, 1.0f, 6500.0f), 6500.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { thresholdId, 1 }, "Threshold",
            Range { -60.0f, 0.0f, 0.01f }, -30.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { ratioId, 1 }, "Ratio",
            freefx::dsp::skewedRange (1.0f, 20.0f, 0.01f, 4.0f), 4.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { rangeId, 1 }, "Range",
            Range { 0.0f, 24.0f, 0.01f }, 8.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { attackId, 1 }, "Attack",
            freefx::dsp::skewedRange (0.1f, 50.0f, 0.01f, 1.0f), 0.5f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { releaseId, 1 }, "Release",
            freefx::dsp::skewedRange (5.0f, 500.0f, 0.1f, 40.0f), 40.0f));
        params.push_back (std::make_unique<juce::AudioParameterBool> (
            juce::ParameterID { listenId, 1 }, "Listen", false));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int) override
    {
        sampleRate = juce::jmax (newSampleRate, 1.0);
        const auto channels = juce::jmax (getTotalNumInputChannels(), getTotalNumOutputChannels(), 1);
        bandHpf.prepare (channels);
        bandLpf.prepare (channels);
        bandHpf.reset();
        bandLpf.reset();
        env = 1.0e-9f;
        lastFreq = -1.0f;
        updateBandCoefficients (freefx::dsp::readParameter (parameters, freqId));
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

        const auto freq        = freefx::dsp::readParameter (parameters, freqId);
        const auto thresholdDb = freefx::dsp::readParameter (parameters, thresholdId);
        const auto ratio       = juce::jmax (1.0f, freefx::dsp::readParameter (parameters, ratioId));
        const auto rangeDb     = freefx::dsp::readParameter (parameters, rangeId);
        const auto atkC = coefFromMs (freefx::dsp::readParameter (parameters, attackId), sampleRate);
        const auto relC = coefFromMs (freefx::dsp::readParameter (parameters, releaseId), sampleRate);
        const auto listen = freefx::dsp::readParameter (parameters, listenId) >= 0.5f;

        if (! juce::approximatelyEqual (freq, lastFreq))
            updateBandCoefficients (freq);

        const auto numSamples = buffer.getNumSamples();
        const auto slope = 1.0f - 1.0f / ratio;

        // Extract the sibilance band per channel; keep it for the split reconstruction.
        juce::AudioBuffer<float> bandBuffer (numInputChannels, numSamples);
        for (int channel = 0; channel < numInputChannels; ++channel)
        {
            const auto* in = buffer.getReadPointer (channel);
            auto* band = bandBuffer.getWritePointer (channel);
            for (int sample = 0; sample < numSamples; ++sample)
            {
                auto value = bandHpf.processSample (channel, in[sample]);
                value = bandLpf.processSample (channel, value);
                band[sample] = value;
            }
        }

        if (listen)
        {
            for (int channel = 0; channel < numInputChannels; ++channel)
                buffer.copyFrom (channel, 0, bandBuffer, channel, 0, numSamples);
            return;
        }

        for (int sample = 0; sample < numSamples; ++sample)
        {
            // Detector = max|band| across channels (matches deesser.py det).
            float det = 0.0f;
            for (int channel = 0; channel < numInputChannels; ++channel)
                det = juce::jmax (det, std::abs (bandBuffer.getReadPointer (channel)[sample]));

            const auto envC = det > env ? atkC : relC;
            env = envC * env + (1.0f - envC) * det;

            const auto overDb = 20.0f * std::log10 (env + 1.0e-12f) - thresholdDb;
            const auto gr = overDb > 0.0f ? -juce::jmin (rangeDb, slope * overDb) : 0.0f;
            const auto g = std::pow (10.0f, gr / 20.0f);

            // Split de-ess: y = x - band + band*g  ==  x + band*(g - 1).
            for (int channel = 0; channel < numInputChannels; ++channel)
            {
                const auto band = bandBuffer.getReadPointer (channel)[sample];
                buffer.getWritePointer (channel)[sample] += band * (g - 1.0f);
            }
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-deesser"; }
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
    void updateBandCoefficients (float freq)
    {
        // deesser.py: lo = max(freq*0.7, 1000); hi = min(freq*1.5, nyquist-1).
        const auto nyquist = static_cast<float> (sampleRate * 0.5);
        const auto lo = juce::jmax (freq * 0.7f, 1000.0f);
        const auto hi = juce::jmin (freq * 1.5f, nyquist - 1.0f);
        bandHpf.setCoefficients (freefx::dsp::makeBiquad (
            freefx::dsp::BiquadKind::hpf, lo, 0.0f, 0.707f, sampleRate));
        bandLpf.setCoefficients (freefx::dsp::makeBiquad (
            freefx::dsp::BiquadKind::lpf, hi, 0.0f, 0.707f, sampleRate));
        lastFreq = freq;
    }

    double sampleRate { 44100.0 };
    float env { 1.0e-9f };
    float lastFreq { -1.0f };
    freefx::dsp::BiquadFilter bandHpf;
    freefx::dsp::BiquadFilter bandLpf;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (DeesserProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new DeesserProcessor();
}
