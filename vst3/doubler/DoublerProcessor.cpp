// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// doubler.py (vocal doubler / ADT / stereo widener).
//
// Real-time note: doubler.py fakes a second take with a delayed + resampled
// (pitch-detuned) copy per voice, panned +/- around the dry centre. Whole-buffer
// resampling is non-causal, so here the "detune" is produced the real-time way:
// a slow LFO modulating each voice's fractional delay. A sinusoidal delay
// modulation of peak depth D at rate f yields a peak pitch deviation of
// 2*pi*f*D/fs; we invert that to hit the requested cents, so the perceived
// detune matches while the algorithm stays causal and block-persistent.

#include <JuceHeader.h>
#include <cmath>
#include <vector>

#include "ParameterHelpers.h"

namespace
{
constexpr auto voicesId  = "voices";
constexpr auto delayMsId = "delayMs";
constexpr auto detuneId  = "detune";   // max detune in cents
constexpr auto spreadId  = "spread";
constexpr auto mixId     = "mix";

constexpr int    maxVoices  = 8;
constexpr double modRateHz  = 0.30;    // slow drift, like a real double take
constexpr double maxDelayMs = 80.0;    // delay(<=40) * voice-scale + mod headroom
} // namespace

class DoublerProcessor final : public juce::AudioProcessor
{
public:
    DoublerProcessor()
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
            juce::ParameterID { voicesId, 1 }, "Voices", 1, maxVoices, 2));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { delayMsId, 1 }, "Delay",
            Range { 1.0f, 40.0f, 0.001f }, 22.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { detuneId, 1 }, "Detune",
            Range { 0.0f, 50.0f, 0.001f }, 12.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { spreadId, 1 }, "Spread",
            Range { 0.0f, 1.0f, 0.001f }, 1.0f));
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
        const auto delayMs = freefx::dsp::readParameter (parameters, delayMsId);
        const auto detune  = freefx::dsp::readParameter (parameters, detuneId);
        const auto spread  = freefx::dsp::readParameter (parameters, spreadId);
        const auto mix     = freefx::dsp::readParameter (parameters, mixId);

        const auto numSamples = buffer.getNumSamples();
        const auto msToSamples = sampleRate / 1000.0;
        const auto modPhaseInc = juce::MathConstants<double>::twoPi * modRateHz / sampleRate;
        const bool stereo = numInputChannels >= 2;

        auto* left  = buffer.getWritePointer (0);
        auto* right = stereo ? buffer.getWritePointer (1) : nullptr;

        // Per-voice constants: centre delay, modulation depth (from cents), pan gains.
        double baseDelay[maxVoices];
        double modDepth[maxVoices];
        float  gainL[maxVoices];
        float  gainR[maxVoices];
        for (int v = 0; v < voices; ++v)
        {
            const auto sign = (v % 2 == 0) ? 1.0 : -1.0;
            const auto cents = sign * detune * (1.0 + 0.3 * v);
            baseDelay[v] = delayMs * (1.0 + 0.25 * v) * msToSamples;

            // Invert 2*pi*f*D/fs = |ratio-1| to hit the requested cents in samples.
            const auto ratioDev = std::abs (std::pow (2.0, cents / 1200.0) - 1.0);
            modDepth[v] = ratioDev * sampleRate / (juce::MathConstants<double>::twoPi * modRateHz);

            const auto pan = sign * spread;   // even voices right-ish, odd left-ish
            gainL[v] = static_cast<float> (std::sqrt (0.5 * (1.0 - pan)));
            gainR[v] = static_cast<float> (std::sqrt (0.5 * (1.0 + pan)));
        }

        double phase[maxVoices];
        for (int v = 0; v < voices; ++v)
            phase[v] = voicePhases[static_cast<size_t> (v)];

        for (int sample = 0; sample < numSamples; ++sample)
        {
            const auto inL = left[sample];
            const auto inR = stereo ? right[sample] : inL;
            const auto mono = 0.5f * (inL + inR);

            line[static_cast<size_t> (writePos)] = mono;

            float wetL = 0.0f;
            float wetR = 0.0f;
            for (int v = 0; v < voices; ++v)
            {
                auto delaySamplesF = baseDelay[v] + modDepth[v] * (0.5 * (1.0 + std::sin (phase[v])));
                delaySamplesF = juce::jlimit (1.0, static_cast<double> (bufferLength - 2), delaySamplesF);
                const auto w = readFractional (delaySamplesF);
                wetL += gainL[v] * w;
                wetR += gainR[v] * w;
                phase[v] += modPhaseInc;
            }

            left[sample] = inL + mix * wetL;
            if (stereo)
                right[sample] = inR + mix * wetR;

            writePos = wrapIndex (writePos + 1, bufferLength);
        }

        for (int v = 0; v < voices; ++v)
            voicePhases[static_cast<size_t> (v)] = std::fmod (phase[v], juce::MathConstants<double>::twoPi);
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-doubler"; }
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

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (DoublerProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new DoublerProcessor();
}
