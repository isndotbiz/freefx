// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// dyneq.py (dynamic EQ -- per-band compression / expansion). Each band is a
// constant-0 dB-peak RBJ bandpass B(x); the output is the classic parallel form
//
//     y = x + k(t) * B(x)
//
// where k(t) = 10^(g(t)/20) - 1 and g(t) is the per-sample EQ gain in dB from a
// standard compressor static curve on the band's OWN envelope, attack/release
// smoothed. k=0 -> no change; k<0 -> dynamic cut; k>0 -> dynamic boost. At band
// centre B has unity magnitude and zero phase, so the realised peak gain is
// exactly (1 + k) -> g dB.
//
// Real-time port: dyneq.py takes a variable list of --band specs. A VST3 needs a
// fixed parameter set, so this exposes THREE independent bands, each with its own
// frequency / Q / threshold / ratio / mode (cut|boost) plus an enable. Per-band
// the bandpass biquad state and the per-band detector envelope are carried across
// processBlock calls (member state, init in prepareToPlay). Global attack /
// release / range / makeup apply to every band, exactly as in dyneq.py.

#include <JuceHeader.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <vector>

#include "Biquad.h"
#include "ParameterHelpers.h"

namespace
{
constexpr int numBands = 3;

inline float onePoleCoef (float milliseconds, double sampleRate)
{
    if (milliseconds <= 0.0f)
        return 0.0f;
    return static_cast<float> (std::exp (-1.0 / (sampleRate * static_cast<double> (milliseconds) / 1000.0)));
}

// RBJ constant 0 dB peak-gain bandpass (dyneq.py bpf_0db): magnitude 1, zero
// phase at f0. b = [alpha, 0, -alpha], a = [1+alpha, -2cos, 1-alpha].
inline freefx::dsp::BiquadCoefficients makeBandpass0dB (float frequencyHz, float q, double sampleRate)
{
    const auto safeSampleRate = std::max (sampleRate, 1.0);
    const auto safeFreq = std::clamp (static_cast<double> (frequencyHz), 1.0, safeSampleRate * 0.49);
    const auto safeQ = std::max (static_cast<double> (q), 0.05);
    const auto w0 = juce::MathConstants<double>::twoPi * safeFreq / safeSampleRate;
    const auto cw = std::cos (w0);
    const auto sw = std::sin (w0);
    const auto alpha = sw / (2.0 * safeQ);
    const auto a0 = 1.0 + alpha;

    return {
        static_cast<float> (alpha / a0),
        0.0f,
        static_cast<float> (-alpha / a0),
        static_cast<float> (-2.0 * cw / a0),
        static_cast<float> ((1.0 - alpha) / a0)
    };
}

struct BandParamIds
{
    juce::String enable, freq, q, threshold, ratio, mode;
};

BandParamIds bandIds (int index)
{
    const auto suffix = juce::String (index + 1);
    return {
        "b" + suffix + "Enable",
        "b" + suffix + "Freq",
        "b" + suffix + "Q",
        "b" + suffix + "Thresh",
        "b" + suffix + "Ratio",
        "b" + suffix + "Boost" // false = cut (default), true = boost
    };
}
} // namespace

class DyneqProcessor final : public juce::AudioProcessor
{
public:
    DyneqProcessor()
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

        // Sensible default centre frequencies spread across the spectrum.
        constexpr std::array<float, numBands> defaultFreqs { 220.0f, 1200.0f, 7000.0f };

        for (int band = 0; band < numBands; ++band)
        {
            const auto ids = bandIds (band);
            const auto label = "Band " + juce::String (band + 1) + " ";

            params.push_back (std::make_unique<juce::AudioParameterBool> (
                juce::ParameterID { ids.enable, 1 }, label + "Enable", band == 0));
            params.push_back (std::make_unique<juce::AudioParameterFloat> (
                juce::ParameterID { ids.freq, 1 }, label + "Freq",
                freefx::dsp::skewedRange (20.0f, 18000.0f, 0.1f, 1000.0f), defaultFreqs[(size_t) band]));
            params.push_back (std::make_unique<juce::AudioParameterFloat> (
                juce::ParameterID { ids.q, 1 }, label + "Q",
                freefx::dsp::skewedRange (0.2f, 10.0f, 0.001f, 2.0f), 2.0f));
            params.push_back (std::make_unique<juce::AudioParameterFloat> (
                juce::ParameterID { ids.threshold, 1 }, label + "Threshold",
                Range { -80.0f, 0.0f, 0.01f }, -28.0f));
            params.push_back (std::make_unique<juce::AudioParameterFloat> (
                juce::ParameterID { ids.ratio, 1 }, label + "Ratio",
                freefx::dsp::skewedRange (1.0f, 20.0f, 0.01f, 4.0f), 4.0f));
            params.push_back (std::make_unique<juce::AudioParameterBool> (
                juce::ParameterID { ids.mode, 1 }, label + "Boost", false));
        }

        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { "attackMs", 1 }, "Attack",
            freefx::dsp::skewedRange (0.0f, 100.0f, 0.01f, 10.0f), 5.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { "releaseMs", 1 }, "Release",
            freefx::dsp::skewedRange (1.0f, 1000.0f, 0.01f, 120.0f), 80.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { "rangeDb", 1 }, "Range",
            Range { 0.0f, 24.0f, 0.01f }, 12.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { "makeupDb", 1 }, "Makeup",
            Range { -24.0f, 24.0f, 0.01f }, 0.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int /*maximumExpectedSamplesPerBlock*/) override
    {
        sampleRate = newSampleRate;
        const auto channels = juce::jmax (getTotalNumInputChannels(), getTotalNumOutputChannels(), 1);
        for (auto& band : bands)
        {
            band.filter.prepare (channels);
            band.filter.reset();
            band.detectorEnv = 1.0e-9f;
        }
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
        const auto attackCoef  = onePoleCoef (freefx::dsp::readParameter (parameters, "attackMs"), sampleRate);
        const auto releaseCoef = onePoleCoef (freefx::dsp::readParameter (parameters, "releaseMs"), sampleRate);
        const auto rangeDb     = std::max (0.0f, freefx::dsp::readParameter (parameters, "rangeDb"));
        const auto makeupGain  = freefx::dsp::dbToLinear (freefx::dsp::readParameter (parameters, "makeupDb"));

        // Refresh per-band parameters / coefficients once per block.
        for (int b = 0; b < numBands; ++b)
        {
            const auto ids = bandIds (b);
            auto& band = bands[(size_t) b];
            band.enabled = freefx::dsp::readParameter (parameters, ids.enable.toRawUTF8()) >= 0.5f;
            band.threshold = freefx::dsp::readParameter (parameters, ids.threshold.toRawUTF8());
            band.ratio = std::max (1.0f, freefx::dsp::readParameter (parameters, ids.ratio.toRawUTF8()));
            band.modeCut = freefx::dsp::readParameter (parameters, ids.mode.toRawUTF8()) < 0.5f;
            const auto freq = freefx::dsp::readParameter (parameters, ids.freq.toRawUTF8());
            const auto q = freefx::dsp::readParameter (parameters, ids.q.toRawUTF8());
            band.filter.setCoefficients (makeBandpass0dB (freq, q, sampleRate));
        }

        for (int sample = 0; sample < numSamples; ++sample)
        {
            for (int b = 0; b < numBands; ++b)
            {
                auto& band = bands[(size_t) b];
                if (! band.enabled)
                    continue;

                const auto slope = 1.0f - 1.0f / band.ratio;

                // Isolate the band on EACH channel, then drive one shared gain from a
                // stereo-linked (max) band envelope so the stereo image stays put.
                std::array<float, 2> bandSamples { 0.0f, 0.0f };
                float linkedRect = 0.0f;
                for (int channel = 0; channel < numInputChannels; ++channel)
                {
                    const auto bandValue = band.filter.processSample (channel,
                        buffer.getReadPointer (channel)[sample]);
                    if (channel < 2)
                        bandSamples[(size_t) channel] = bandValue;
                    linkedRect = std::max (linkedRect, std::abs (bandValue));
                }

                const auto envCoef = (linkedRect > band.detectorEnv) ? attackCoef : releaseCoef;
                band.detectorEnv = envCoef * band.detectorEnv + (1.0f - envCoef) * linkedRect;
                const auto envDb = 20.0f * std::log10 (band.detectorEnv + 1.0e-12f);

                float gDb;
                if (band.modeCut)
                {
                    const auto over = envDb - band.threshold;
                    gDb = (over > 0.0f) ? (-slope * over) : 0.0f;     // cut when ABOVE thr
                }
                else
                {
                    const auto under = band.threshold - envDb;
                    gDb = (under > 0.0f) ? (slope * under) : 0.0f;    // boost when BELOW thr
                }
                gDb = std::clamp (gDb, -rangeDb, rangeDb);
                const auto k = std::pow (10.0f, gDb / 20.0f) - 1.0f;

                // Parallel form: y = x + k * B(x), per channel.
                for (int channel = 0; channel < numInputChannels && channel < 2; ++channel)
                    buffer.getWritePointer (channel)[sample] += k * bandSamples[(size_t) channel];
            }

            if (makeupGain != 1.0f)
                for (int channel = 0; channel < numInputChannels; ++channel)
                    buffer.getWritePointer (channel)[sample] *= makeupGain;
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-dyneq"; }
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
    struct Band
    {
        freefx::dsp::BiquadFilter filter;
        float detectorEnv { 1.0e-9f };
        float threshold { -28.0f };
        float ratio { 4.0f };
        bool modeCut { true };
        bool enabled { false };
    };

    double sampleRate { 44100.0 };
    std::array<Band, numBands> bands;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (DyneqProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new DyneqProcessor();
}
