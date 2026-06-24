// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// flanger.py (LFO-swept short fractional delay + feedback = jet-sweep comb).
//
// Real-time note: flanger.py writes into a full-length buffer indexed by the
// absolute sample number and reads a fractional delay behind the write head.
// Here that becomes a persistent per-channel circular delay line plus a
// continuous LFO phase, both carried across processBlock so the sweep and the
// feedback tail never reset at block boundaries.

#include <JuceHeader.h>
#include <vector>

#include "ParameterHelpers.h"

namespace
{
constexpr auto rateId     = "rate";
constexpr auto depthId    = "depth";    // sweep depth in ms
constexpr auto baseMsId   = "baseMs";   // minimum delay in ms
constexpr auto feedbackId = "feedback";
constexpr auto mixId      = "mix";

// Max delay the line must hold = base + depth, with headroom. base<=10ms,
// depth<=10ms here, so 64ms at any sane sample rate is plenty.
constexpr double maxDelayMs = 64.0;
} // namespace

class FlangerProcessor final : public juce::AudioProcessor
{
public:
    FlangerProcessor()
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
            juce::ParameterID { rateId, 1 }, "Rate",
            freefx::dsp::skewedRange (0.05f, 10.0f, 0.001f, 0.5f), 0.3f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { depthId, 1 }, "Depth",
            Range { 0.0f, 10.0f, 0.001f }, 3.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { baseMsId, 1 }, "Base",
            Range { 0.1f, 10.0f, 0.001f }, 1.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { feedbackId, 1 }, "Feedback",
            Range { -0.95f, 0.95f, 0.001f }, 0.5f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { mixId, 1 }, "Mix",
            Range { 0.0f, 1.0f, 0.001f }, 0.5f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int) override
    {
        sampleRate = juce::jmax (newSampleRate, 1.0);
        const auto channels = juce::jmax (getTotalNumInputChannels(), getTotalNumOutputChannels(), 1);
        bufferLength = static_cast<int> (std::ceil (maxDelayMs * sampleRate / 1000.0)) + 4;

        lines.assign (static_cast<size_t> (channels), std::vector<float> (static_cast<size_t> (bufferLength), 0.0f));
        writePositions.assign (static_cast<size_t> (channels), 0);
        lfoPhase = 0.0;
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

        const auto rate   = freefx::dsp::readParameter (parameters, rateId);
        const auto depth  = freefx::dsp::readParameter (parameters, depthId);
        const auto baseMs = freefx::dsp::readParameter (parameters, baseMsId);
        const auto fb     = juce::jlimit (-0.95f, 0.95f, freefx::dsp::readParameter (parameters, feedbackId));
        const auto mix    = freefx::dsp::readParameter (parameters, mixId);

        const auto numSamples = buffer.getNumSamples();
        const auto phaseInc = juce::MathConstants<double>::twoPi * rate / sampleRate;
        const auto msToSamples = sampleRate / 1000.0;

        // Per-block LFO start phase is shared by all channels so they sweep in
        // lock-step, exactly like flanger.py (same sin(twopi_r * i) for each channel).
        for (int channel = 0; channel < numInputChannels; ++channel)
        {
            auto& line = lines[static_cast<size_t> (channel)];
            auto writePos = writePositions[static_cast<size_t> (channel)];
            auto phase = lfoPhase;
            auto* data = buffer.getWritePointer (channel);

            for (int sample = 0; sample < numSamples; ++sample)
            {
                // Delay in samples, swept 0..1 of (base + depth) by the LFO.
                const auto delaySamplesF = (baseMs + depth * 0.5 * (1.0 + std::sin (phase))) * msToSamples;
                const auto di = static_cast<int> (delaySamplesF);
                const auto frac = static_cast<float> (delaySamplesF - di);

                const auto read0 = wrapIndex (writePos - di, bufferLength);
                const auto read1 = wrapIndex (writePos - di - 1, bufferLength);
                const auto delayed = line[static_cast<size_t> (read0)] * (1.0f - frac)
                                   + line[static_cast<size_t> (read1)] * frac;

                const auto in = data[sample];
                line[static_cast<size_t> (writePos)] = in + fb * delayed;   // feedback into the line
                data[sample] = (1.0f - mix) * in + mix * delayed;

                writePos = wrapIndex (writePos + 1, bufferLength);
                phase += phaseInc;
                if (phase >= juce::MathConstants<double>::twoPi)
                    phase -= juce::MathConstants<double>::twoPi;
            }

            writePositions[static_cast<size_t> (channel)] = writePos;
        }

        // Advance the shared LFO phase by exactly numSamples for the next block.
        lfoPhase += phaseInc * numSamples;
        lfoPhase = std::fmod (lfoPhase, juce::MathConstants<double>::twoPi);
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-flanger"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return maxDelayMs / 1000.0; }
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
    static int wrapIndex (int index, int length)
    {
        index %= length;
        if (index < 0)
            index += length;
        return index;
    }

    double sampleRate { 44100.0 };
    int bufferLength { 1 };
    double lfoPhase { 0.0 };
    std::vector<std::vector<float>> lines;
    std::vector<int> writePositions;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (FlangerProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new FlangerProcessor();
}
