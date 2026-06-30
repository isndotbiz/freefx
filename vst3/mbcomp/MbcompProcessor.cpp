// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// mbcomp.py (3-band multiband compressor / master glue). Splits into low / mid /
// high at two crossovers, compresses each band independently (soft-knee,
// attack/release), and sums. mbcomp.py uses a complementary split (mid = full -
// low - high) so the bands reconstruct exactly when nothing is compressing.
//
// Real-time port notes:
//  - mbcomp.py uses butter(4, ...) low-pass / high-pass for the splits. Here the
//    low-pass and high-pass are JUCE LinkwitzRileyFilter (LR4, 4th-order,
//    phase-coherent crossovers -- the JUCE-recommended crossover) and the mid is
//    the complementary residual (full - low - high), preserving mbcomp.py's
//    exact-reconstruction property when no compression is active.
//  - Each band has its own soft-knee compressor with attack/release envelope and
//    smoothed gain, stereo-linked detection -- all carried as member state across
//    processBlock calls (init in prepareToPlay).

#include <JuceHeader.h>

#include <algorithm>
#include <array>
#include <cmath>

#include "ParameterHelpers.h"

namespace
{
constexpr auto xover1Id    = "xoverLow";
constexpr auto xover2Id    = "xoverHigh";
constexpr auto thresholdId = "threshold";
constexpr auto ratioId     = "ratio";
constexpr auto kneeId      = "knee";
constexpr auto attackId    = "attackMs";
constexpr auto releaseId   = "releaseMs";
constexpr auto makeupId    = "makeupDb";

inline float onePoleCoef (float milliseconds, double sampleRate)
{
    if (milliseconds <= 0.0f)
        return 0.0f;
    return static_cast<float> (std::exp (-1.0 / (sampleRate * static_cast<double> (milliseconds) / 1000.0)));
}
} // namespace

// Per-band soft-knee compressor with attack/release smoothing and stereo-linked
// detection. State (detector envelope + smoothed gain) persists across blocks.
class BandCompressor
{
public:
    void reset()
    {
        detectorEnv  = 1.0e-9f;
        smoothedGain = 1.0f;
    }

    void setParameters (float thresholdDb, float ratio, float kneeDb, float attackCoef, float releaseCoef)
    {
        threshold = thresholdDb;
        slope     = 1.0f / std::max (1.0f, ratio) - 1.0f;
        knee      = std::max (0.0f, kneeDb);
        halfKnee  = knee * 0.5f;
        atkCoef   = attackCoef;
        relCoef   = releaseCoef;
    }

    // Advance the detector/gain by one (stereo-linked) sample and return the gain.
    float computeGain (float linkedRect)
    {
        const auto envCoef = (linkedRect > detectorEnv) ? atkCoef : relCoef;
        detectorEnv = envCoef * detectorEnv + (1.0f - envCoef) * linkedRect;

        const auto over = 20.0f * std::log10 (detectorEnv + 1.0e-12f) - threshold;
        float grDb;
        if (knee > 0.0f && over >= -halfKnee && over <= halfKnee)
            grDb = slope * (over + halfKnee) * (over + halfKnee) / (2.0f * knee);
        else if (over > 0.0f)
            grDb = slope * over;
        else
            grDb = 0.0f;

        const auto target = std::pow (10.0f, grDb / 20.0f);
        const auto gainCoef = (target < smoothedGain) ? atkCoef : relCoef;
        smoothedGain = gainCoef * smoothedGain + (1.0f - gainCoef) * target;
        return smoothedGain;
    }

private:
    float threshold { -20.0f };
    float slope { -0.66f };
    float knee { 6.0f };
    float halfKnee { 3.0f };
    float atkCoef { 0.0f };
    float relCoef { 0.0f };
    float detectorEnv { 1.0e-9f };
    float smoothedGain { 1.0f };
};

class MbcompProcessor final : public juce::AudioProcessor
{
public:
    MbcompProcessor()
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
            juce::ParameterID { xover1Id, 1 }, "Low/Mid Xover",
            freefx::dsp::skewedRange (40.0f, 1000.0f, 0.1f, 200.0f), 200.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { xover2Id, 1 }, "Mid/High Xover",
            freefx::dsp::skewedRange (800.0f, 12000.0f, 0.1f, 2500.0f), 2500.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { thresholdId, 1 }, "Threshold",
            Range { -60.0f, 0.0f, 0.01f }, -20.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { ratioId, 1 }, "Ratio",
            freefx::dsp::skewedRange (1.0f, 20.0f, 0.01f, 3.0f), 3.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { kneeId, 1 }, "Knee",
            Range { 0.0f, 24.0f, 0.01f }, 6.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { attackId, 1 }, "Attack",
            freefx::dsp::skewedRange (0.0f, 200.0f, 0.01f, 10.0f), 10.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { releaseId, 1 }, "Release",
            freefx::dsp::skewedRange (1.0f, 2000.0f, 0.01f, 200.0f), 120.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { makeupId, 1 }, "Makeup",
            Range { -24.0f, 24.0f, 0.01f }, 0.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int maximumExpectedSamplesPerBlock) override
    {
        sampleRate = newSampleRate;
        const auto channels = static_cast<juce::uint32> (
            juce::jmax (getTotalNumInputChannels(), getTotalNumOutputChannels(), 1));

        juce::dsp::ProcessSpec spec;
        spec.sampleRate = sampleRate;
        spec.maximumBlockSize = static_cast<juce::uint32> (juce::jmax (maximumExpectedSamplesPerBlock, 1));
        spec.numChannels = channels;

        lowpass.prepare (spec);
        highpass.prepare (spec);
        lowpass.setType (juce::dsp::LinkwitzRileyFilterType::lowpass);
        highpass.setType (juce::dsp::LinkwitzRileyFilterType::highpass);
        lowpass.reset();
        highpass.reset();

        for (auto& comp : compressors)
            comp.reset();

        lowBuffer.setSize ((int) channels, spec.maximumBlockSize, false, false, true);
        highBuffer.setSize ((int) channels, spec.maximumBlockSize, false, false, true);
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

        const auto xover1 = freefx::dsp::readParameter (parameters, xover1Id);
        const auto xover2 = std::max (xover1 + 1.0f, freefx::dsp::readParameter (parameters, xover2Id));
        const auto thresholdDb = freefx::dsp::readParameter (parameters, thresholdId);
        const auto ratio = freefx::dsp::readParameter (parameters, ratioId);
        const auto kneeDb = freefx::dsp::readParameter (parameters, kneeId);
        const auto attackCoef = onePoleCoef (freefx::dsp::readParameter (parameters, attackId), sampleRate);
        const auto releaseCoef = onePoleCoef (freefx::dsp::readParameter (parameters, releaseId), sampleRate);
        const auto makeupGain = freefx::dsp::dbToLinear (freefx::dsp::readParameter (parameters, makeupId));

        lowpass.setCutoffFrequency (juce::jlimit (10.0f, static_cast<float> (sampleRate * 0.49), xover1));
        highpass.setCutoffFrequency (juce::jlimit (10.0f, static_cast<float> (sampleRate * 0.49), xover2));
        for (auto& comp : compressors)
            comp.setParameters (thresholdDb, ratio, kneeDb, attackCoef, releaseCoef);

        // Copy the full signal into the low and high work buffers, then filter in place.
        lowBuffer.setSize (numInputChannels, numSamples, false, false, true);
        highBuffer.setSize (numInputChannels, numSamples, false, false, true);
        for (int channel = 0; channel < numInputChannels; ++channel)
        {
            lowBuffer.copyFrom (channel, 0, buffer, channel, 0, numSamples);
            highBuffer.copyFrom (channel, 0, buffer, channel, 0, numSamples);
        }

        {
            juce::dsp::AudioBlock<float> lowBlock (lowBuffer);
            juce::dsp::ProcessContextReplacing<float> lowCtx (lowBlock);
            lowpass.process (lowCtx);

            juce::dsp::AudioBlock<float> highBlock (highBuffer);
            juce::dsp::ProcessContextReplacing<float> highCtx (highBlock);
            highpass.process (highCtx);
        }

        for (int sample = 0; sample < numSamples; ++sample)
        {
            // Stereo-linked detection per band (max |x| across channels), then a single
            // gain per band applied to both channels -- matches mbcomp.py's linked detection.
            float lowRect = 0.0f, midRect = 0.0f, highRect = 0.0f;
            std::array<float, 2> lowVals { 0.0f, 0.0f };
            std::array<float, 2> midVals { 0.0f, 0.0f };
            std::array<float, 2> highVals { 0.0f, 0.0f };

            for (int channel = 0; channel < numInputChannels; ++channel)
            {
                const auto full = buffer.getReadPointer (channel)[sample];
                const auto low  = lowBuffer.getReadPointer (channel)[sample];
                const auto high = highBuffer.getReadPointer (channel)[sample];
                const auto mid  = full - low - high;   // complementary residual

                if (channel < 2)
                {
                    lowVals[(size_t) channel]  = low;
                    midVals[(size_t) channel]  = mid;
                    highVals[(size_t) channel] = high;
                }
                lowRect  = std::max (lowRect,  std::abs (low));
                midRect  = std::max (midRect,  std::abs (mid));
                highRect = std::max (highRect, std::abs (high));
            }

            const auto gLow  = compressors[0].computeGain (lowRect);
            const auto gMid  = compressors[1].computeGain (midRect);
            const auto gHigh = compressors[2].computeGain (highRect);

            for (int channel = 0; channel < numInputChannels && channel < 2; ++channel)
            {
                const auto summed = gLow * lowVals[(size_t) channel]
                                  + gMid * midVals[(size_t) channel]
                                  + gHigh * highVals[(size_t) channel];
                buffer.getWritePointer (channel)[sample] = summed * makeupGain;
            }
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-mbcomp"; }
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
    juce::dsp::LinkwitzRileyFilter<float> lowpass;
    juce::dsp::LinkwitzRileyFilter<float> highpass;
    std::array<BandCompressor, 3> compressors; // [0]=low, [1]=mid, [2]=high
    juce::AudioBuffer<float> lowBuffer;
    juce::AudioBuffer<float> highBuffer;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MbcompProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new MbcompProcessor();
}
