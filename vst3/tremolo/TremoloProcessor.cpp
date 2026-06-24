// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// tremolo.py (amplitude-LFO tremolo + constant-power auto-pan, sine/square).
//
// Real-time note: the Python version computes the LFO from an absolute sample
// index (np.arange(n)/sr). Here the LFO phase is carried across processBlock
// calls in `lfoPhase` so the modulation is continuous and never resets per block.

#include <JuceHeader.h>

#include "ParameterHelpers.h"

namespace
{
constexpr auto rateId  = "rate";
constexpr auto depthId = "depth";
constexpr auto shapeId = "shape"; // 0 = sine, 1 = square
constexpr auto panId   = "pan";   // bool: auto-pan instead of tremolo
} // namespace

class TremoloProcessor final : public juce::AudioProcessor
{
public:
    TremoloProcessor()
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
            freefx::dsp::skewedRange (0.05f, 20.0f, 0.001f, 3.0f), 5.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { depthId, 1 }, "Depth",
            Range { 0.0f, 1.0f, 0.001f }, 0.6f));
        params.push_back (std::make_unique<juce::AudioParameterChoice> (
            juce::ParameterID { shapeId, 1 }, "Shape",
            juce::StringArray { "Sine", "Square" }, 0));
        params.push_back (std::make_unique<juce::AudioParameterBool> (
            juce::ParameterID { panId, 1 }, "Auto-Pan", false));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int) override
    {
        sampleRate = juce::jmax (newSampleRate, 1.0);
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

        const auto rate    = freefx::dsp::readParameter (parameters, rateId);
        const auto depth   = freefx::dsp::readParameter (parameters, depthId);
        const auto square  = freefx::dsp::readParameter (parameters, shapeId) >= 0.5f;
        const auto autoPan = freefx::dsp::readParameter (parameters, panId) >= 0.5f;

        const auto numSamples = buffer.getNumSamples();
        const auto phaseInc = juce::MathConstants<double>::twoPi * rate / sampleRate;

        // Auto-pan needs two channels; if mono input, duplicate channel 0 into the
        // cleared channel 1 first (mirrors np.repeat(x, 2) in tremolo.py).
        const bool canPan = autoPan && numOutputChannels >= 2;
        if (canPan && numInputChannels < 2)
            buffer.copyFrom (1, 0, buffer, 0, 0, numSamples);

        for (int sample = 0; sample < numSamples; ++sample)
        {
            auto lfo = std::sin (lfoPhase);
            if (square)
                lfo = lfo >= 0.0 ? 1.0 : -1.0;

            if (canPan)
            {
                const auto pan = depth * lfo;                 // -depth..+depth
                const auto gl = static_cast<float> (std::sqrt (0.5 * (1.0 - pan)));
                const auto gr = static_cast<float> (std::sqrt (0.5 * (1.0 + pan)));
                buffer.getWritePointer (0)[sample] *= gl;
                buffer.getWritePointer (1)[sample] *= gr;
            }
            else
            {
                const auto g = static_cast<float> (1.0 - depth * 0.5 * (1.0 + lfo));
                for (int channel = 0; channel < numOutputChannels; ++channel)
                    buffer.getWritePointer (channel)[sample] *= g;
            }

            lfoPhase += phaseInc;
            if (lfoPhase >= juce::MathConstants<double>::twoPi)
                lfoPhase -= juce::MathConstants<double>::twoPi;
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-tremolo"; }
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
    double lfoPhase { 0.0 };
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TremoloProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new TremoloProcessor();
}
