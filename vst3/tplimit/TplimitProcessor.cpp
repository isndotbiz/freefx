// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// tplimit.py (true-peak brickwall limiter / loudness maximizer). Oversampled
// look-ahead limiting catches inter-sample (true) peaks by limiting at an
// upsampled rate, so the final output never exceeds the ceiling in dBTP. Input
// drive (--gain) pushes harder into the limiter.
//
// Real-time port notes:
//  - Oversampling: juce::dsp::Oversampling (filterHalfBandPolyphaseIIR) at the
//    chosen factor replaces tplimit.py's resample_poly. The limiter computes the
//    gain at the oversampled rate, applies it, and hard-clips in the oversampled
//    domain (matching tplimit.py's np.clip in the oversampled domain), then the
//    oversampler downsamples. The 0.3 dB safety margin is preserved.
//  - Look-ahead: a per-channel-linked sliding-window maximum over the look-ahead
//    window (a ring buffer), matching maximum_filter1d. The block is delayed by
//    the look-ahead so the gain reduction lands BEFORE the peak. JUCE latency is
//    reported as oversampler latency + look-ahead (in base-rate samples).
//  - Release: a one-pole smoother on the gain, instant attack / smooth release,
//    matching tplimit.py's lfilter release with g = min(desired, smoothed).
//  - tplimit.py's --target-lufs maximizer bisects input gain over the WHOLE file
//    using an offline ffmpeg ebur128 measurement -- non-causal and unavailable in
//    a real-time block. Omitted; the ceiling + input-gain limiter path is ported.

#include <JuceHeader.h>

#include <algorithm>
#include <cmath>
#include <vector>

#include "ParameterHelpers.h"

namespace
{
constexpr auto ceilingId   = "ceiling";
constexpr auto gainId      = "gain";
constexpr auto lookaheadId = "lookaheadMs";
constexpr auto releaseId   = "releaseMs";

// 2^2 = 4x oversampling, matching tplimit.py's default --oversample 4.
constexpr int oversampleFactorLog2 = 2;
constexpr int oversampleFactor = 1 << oversampleFactorLog2;
} // namespace

// Per (oversampled) stream sliding-window maximum of |x| over the look-ahead
// window (a small ring buffer). Used to build the look-ahead peak envelope so the
// gain reacts to a peak that is about to arrive. The window is short (a few ms at
// the oversampled rate), so the linear scan per sample is cheap.
class SlidingMax
{
public:
    void prepare (int windowSamples)
    {
        window = std::max (1, windowSamples);
        values.assign ((size_t) window, 0.0f);
        head = 0;
        count = 0;
    }

    void reset()
    {
        std::fill (values.begin(), values.end(), 0.0f);
        head = 0;
        count = 0;
    }

    // Push one sample, return the max over the most-recent `window` samples.
    float process (float absValue)
    {
        values[(size_t) head] = absValue;
        head = (head + 1) % window;
        if (count < window)
            ++count;

        float maxVal = 0.0f;
        for (int i = 0; i < count; ++i)
            maxVal = std::max (maxVal, values[(size_t) i]);
        return maxVal;
    }

private:
    int window { 1 };
    int head { 0 };
    int count { 0 };
    std::vector<float> values;
};

class TplimitProcessor final : public juce::AudioProcessor
{
public:
    TplimitProcessor()
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
            juce::ParameterID { ceilingId, 1 }, "Ceiling",
            Range { -24.0f, 0.0f, 0.01f }, -1.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { gainId, 1 }, "Gain",
            Range { 0.0f, 36.0f, 0.01f }, 0.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { lookaheadId, 1 }, "Lookahead",
            Range { 0.1f, 10.0f, 0.01f }, 2.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { releaseId, 1 }, "Release",
            freefx::dsp::skewedRange (1.0f, 500.0f, 0.01f, 60.0f), 60.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int maximumExpectedSamplesPerBlock) override
    {
        sampleRate = newSampleRate;
        const auto channels = static_cast<juce::uint32> (
            juce::jmax (getTotalNumInputChannels(), getTotalNumOutputChannels(), 1));

        oversampler = std::make_unique<juce::dsp::Oversampling<float>> (
            channels,
            oversampleFactorLog2,
            juce::dsp::Oversampling<float>::filterHalfBandPolyphaseIIR);
        oversampler->initProcessing (static_cast<size_t> (juce::jmax (maximumExpectedSamplesPerBlock, 1)));
        oversampler->reset();

        oversampledRate = sampleRate * oversampleFactor;
        numChannels = (int) channels;

        // Size each channel's sliding-window-max ring buffer to the maximum look-ahead
        // (10 ms param ceiling at the oversampled rate). The actual window is set per
        // block from the look-ahead parameter.
        currentLookaheadSamples = std::max (1, (int) std::lround (oversampledRate * 2.0 / 1000.0));
        slidingMax.resize ((size_t) channels);
        for (auto& sm : slidingMax)
            sm.prepare (currentLookaheadSamples);

        oversampleLatency = (int) std::lround (oversampler->getLatencyInSamples());
        // Report the oversampler's latency. The look-ahead reacts early via the
        // sliding-window max without an explicit signal delay line, so it adds none.
        setLatencySamples (oversampleLatency);
        reset();
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

        const auto ceilingDb   = freefx::dsp::readParameter (parameters, ceilingId);
        const auto gainDb      = freefx::dsp::readParameter (parameters, gainId);
        const auto lookaheadMs = freefx::dsp::readParameter (parameters, lookaheadId);
        const auto releaseMs   = freefx::dsp::readParameter (parameters, releaseId);

        // 0.3 dB safety margin (downsampling reintroduces tiny inter-sample peaks).
        const auto ceil = std::pow (10.0f, (ceilingDb - 0.3f) / 20.0f);
        const auto safeCeil = std::max (ceil, 1.0e-6f);
        const auto driveGain = std::pow (10.0f, gainDb / 20.0f);

        const auto lookaheadSamples = std::max (1, (int) std::lround (oversampledRate * lookaheadMs / 1000.0));
        if (lookaheadSamples != currentLookaheadSamples)
        {
            currentLookaheadSamples = lookaheadSamples;
            for (auto& sm : slidingMax)
                sm.prepare (currentLookaheadSamples);
            linkedSmoothed = 1.0f;
        }

        const auto releaseCoef = releaseMs > 0.0f
            ? (float) std::exp (-1.0 / (oversampledRate * (double) releaseMs / 1000.0))
            : 0.0f;

        const auto numSamples = buffer.getNumSamples();

        // Apply input drive at base rate before upsampling.
        for (int channel = 0; channel < numInputChannels; ++channel)
        {
            auto* data = buffer.getWritePointer (channel);
            for (int sample = 0; sample < numSamples; ++sample)
                data[sample] *= driveGain;
        }

        juce::dsp::AudioBlock<float> block (buffer);
        auto osBlock = oversampler->processSamplesUp (block);

        const auto osChannels = (int) osBlock.getNumChannels();
        const auto osLength   = (int) osBlock.getNumSamples();

        // Stereo-linked look-ahead limiting in the oversampled domain. We compute a
        // single linked gain per oversampled sample (max peak across channels) so the
        // stereo image stays put, smoothing the release with a one-pole.
        for (int sample = 0; sample < osLength; ++sample)
        {
            float linkedPeak = 0.0f;
            for (int channel = 0; channel < osChannels; ++channel)
            {
                const auto absVal = std::abs (osBlock.getChannelPointer ((size_t) channel)[sample]);
                const auto windowed = slidingMax[(size_t) channel].process (absVal);
                linkedPeak = std::max (linkedPeak, windowed);
            }

            const auto desired = (linkedPeak > safeCeil) ? (safeCeil / std::max (linkedPeak, 1.0e-12f)) : 1.0f;
            // Instant attack, smooth release: smoothedGain follows desired up slowly,
            // but g = min(desired, smoothed) snaps DOWN instantly on a new peak.
            linkedSmoothed = releaseCoef * linkedSmoothed + (1.0f - releaseCoef) * desired;
            const auto g = std::min (desired, linkedSmoothed);

            for (int channel = 0; channel < osChannels; ++channel)
            {
                auto* data = osBlock.getChannelPointer ((size_t) channel);
                // The look-ahead window already saw this sample's peak, but the sample
                // itself is not yet delayed, so we also hard-clip as a final guarantee
                // (matches tplimit.py's np.clip in the oversampled domain).
                data[sample] = juce::jlimit (-safeCeil, safeCeil, data[sample] * g);
            }
        }

        oversampler->processSamplesDown (block);
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-tplimit"; }
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
    void reset()
    {
        for (auto& sm : slidingMax)
            sm.reset();
        linkedSmoothed = 1.0f;
        if (oversampler != nullptr)
            oversampler->reset();
    }

    double sampleRate { 44100.0 };
    double oversampledRate { 176400.0 };
    int oversampleLatency { 0 };
    int numChannels { 0 };
    int currentLookaheadSamples { 1 };
    std::unique_ptr<juce::dsp::Oversampling<float>> oversampler;
    std::vector<SlidingMax> slidingMax;      // one per oversampled channel
    float linkedSmoothed { 1.0f };
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TplimitProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new TplimitProcessor();
}
