// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// chorus.py (80s Juno/Oberheim modulated-delay chorus).
//
// Real-time note: chorus.py builds each voice by interpolating a whole-buffer
// index array (np.interp), non-causal. Here each voice is a fractional read of a
// persistent mono delay line, and every voice carries its own LFO phase across
// processBlock so the shimmer is continuous. The source sums the input to mono
// before feeding the voices; we do the same for the wet source but keep the dry
// signal at its original (possibly stereo) form so stereo material is preserved.

#include <JuceHeader.h>
#include <cmath>
#include <vector>

#include "ParameterHelpers.h"

namespace
{
constexpr auto voicesId = "voices";
constexpr auto rateId   = "rate";
constexpr auto depthId  = "depth";
constexpr auto baseMsId = "baseMs";
constexpr auto mixId    = "mix";

constexpr int    maxVoices  = 8;
constexpr double maxDelayMs = 48.0;   // base(<=30) + depth(<=12) + headroom
} // namespace

class ChorusProcessor final : public juce::AudioProcessor
{
public:
    ChorusProcessor()
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

        params.push_back (std::make_unique<juce::AudioParameterInt> (
            juce::ParameterID { voicesId, 1 }, "Voices", 1, maxVoices, 3));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { rateId, 1 }, "Rate",
            freefx::dsp::skewedRange (0.05f, 8.0f, 0.001f, 0.6f), 0.6f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { depthId, 1 }, "Depth",
            Range { 0.0f, 12.0f, 0.001f }, 4.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { baseMsId, 1 }, "Base",
            Range { 1.0f, 30.0f, 0.001f }, 18.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { mixId, 1 }, "Mix",
            Range { 0.0f, 1.0f, 0.001f }, 0.5f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int) override
    {
        sampleRate = juce::jmax (newSampleRate, 1.0);
        bufferLength = static_cast<int> (std::ceil (maxDelayMs * sampleRate / 1000.0)) + 4;
        line.assign (static_cast<size_t> (bufferLength), 0.0f);
        writePos = 0;
        voicePhases.assign (maxVoices, 0.0);
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

        const auto voices = juce::jlimit (1, maxVoices,
                                          static_cast<int> (std::lround (freefx::dsp::readParameter (parameters, voicesId))));
        const auto rate   = freefx::dsp::readParameter (parameters, rateId);
        const auto depth  = freefx::dsp::readParameter (parameters, depthId);
        const auto baseMs = freefx::dsp::readParameter (parameters, baseMsId);
        const auto mix    = freefx::dsp::readParameter (parameters, mixId);

        const auto numSamples = buffer.getNumSamples();
        const auto msToSamples = sampleRate / 1000.0;
        const bool stereo = numInputChannels >= 2;

        auto* left  = buffer.getWritePointer (0);
        auto* right = stereo ? buffer.getWritePointer (1) : nullptr;

        // Precompute per-voice pan gains + phase increments (constant over block).
        double phaseInc[maxVoices];
        float  gainL[maxVoices];
        float  gainR[maxVoices];
        for (int v = 0; v < voices; ++v)
        {
            const auto rateV = rate * (1.0 + 0.1 * v);
            phaseInc[v] = juce::MathConstants<double>::twoPi * rateV / sampleRate;
            const auto pan = -1.0 + 2.0 * v / juce::jmax (voices - 1, 1);   // spread across field
            gainL[v] = static_cast<float> (std::sqrt (0.5 * (1.0 - pan)));
            gainR[v] = static_cast<float> (std::sqrt (0.5 * (1.0 + pan)));
        }

        // Snapshot starting phases; the persistent 2*pi*v/voices offset is added
        // per-voice each sample so voices stay evenly staggered like chorus.py.
        double phase[maxVoices];
        for (int v = 0; v < voices; ++v)
            phase[v] = voicePhases[static_cast<size_t> (v)];

        for (int sample = 0; sample < numSamples; ++sample)
        {
            const auto inL = left[sample];
            const auto inR = stereo ? right[sample] : inL;
            const auto mono = 0.5f * (inL + inR);

            // Wet source feeds the shared mono line.
            line[static_cast<size_t> (writePos)] = mono;

            float wetL = 0.0f;
            float wetR = 0.0f;
            for (int v = 0; v < voices; ++v)
            {
                const auto ph = phase[v] + juce::MathConstants<double>::twoPi * v / voices;
                const auto delayMs = baseMs + depth * (0.5 + 0.5 * std::sin (ph));
                const auto delaySamplesF = delayMs * msToSamples;
                const auto w = readFractional (delaySamplesF);
                wetL += gainL[v] * w;
                wetR += gainR[v] * w;
                phase[v] += phaseInc[v];
            }

            left[sample] = inL + mix * wetL;
            if (stereo)
                right[sample] = inR + mix * wetR;

            writePos = wrapIndex (writePos + 1, bufferLength);
        }

        // Persist wrapped phases for the next block.
        for (int v = 0; v < voices; ++v)
            voicePhases[static_cast<size_t> (v)] = std::fmod (phase[v], juce::MathConstants<double>::twoPi);
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-chorus"; }
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

    float readFractional (double delaySamplesF) const
    {
        const auto di = static_cast<int> (delaySamplesF);
        const auto frac = static_cast<float> (delaySamplesF - di);
        const auto read0 = wrapIndex (writePos - di, bufferLength);
        const auto read1 = wrapIndex (writePos - di - 1, bufferLength);
        return line[static_cast<size_t> (read0)] * (1.0f - frac)
             + line[static_cast<size_t> (read1)] * frac;
    }

    double sampleRate { 44100.0 };
    int bufferLength { 1 };
    int writePos { 0 };
    std::vector<float> line;
    std::vector<double> voicePhases;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ChorusProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new ChorusProcessor();
}
