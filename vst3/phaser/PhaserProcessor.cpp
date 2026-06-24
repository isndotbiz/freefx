// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// phaser.py (LFO log-swept first-order all-pass cascade + feedback = moving
// notches / swirly sweep).
//
// Real-time note: each channel keeps its own all-pass state vector (zs[]) and
// feedback memory (last), and the LFO break-frequency sweep is driven by a
// continuous phase carried across processBlock. Stage count is fixed at the
// processor's max so the state vector never reallocates on the audio thread;
// the active stage count is read from the parameter each block.

#include <JuceHeader.h>
#include <array>
#include <vector>

#include "ParameterHelpers.h"

namespace
{
constexpr auto stagesId   = "stages";
constexpr auto rateId     = "rate";
constexpr auto fminId     = "fmin";
constexpr auto fmaxId     = "fmax";
constexpr auto feedbackId = "feedback";
constexpr auto mixId      = "mix";

constexpr int maxStages = 12;
} // namespace

class PhaserProcessor final : public juce::AudioProcessor
{
public:
    PhaserProcessor()
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
            juce::ParameterID { stagesId, 1 }, "Stages", 2, maxStages, 6));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { rateId, 1 }, "Rate",
            freefx::dsp::skewedRange (0.05f, 10.0f, 0.001f, 0.5f), 0.4f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { fminId, 1 }, "Freq Min",
            freefx::dsp::skewedRange (50.0f, 4000.0f, 0.1f, 400.0f), 300.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { fmaxId, 1 }, "Freq Max",
            freefx::dsp::skewedRange (500.0f, 12000.0f, 0.1f, 2500.0f), 2000.0f));
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
        channelStates.assign (static_cast<size_t> (channels), {});
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

        const auto stages = juce::jlimit (1, maxStages,
            static_cast<int> (std::lround (freefx::dsp::readParameter (parameters, stagesId))));
        const auto rate = freefx::dsp::readParameter (parameters, rateId);
        auto fmin = freefx::dsp::readParameter (parameters, fminId);
        auto fmax = freefx::dsp::readParameter (parameters, fmaxId);
        const auto fb  = juce::jlimit (-0.95f, 0.95f, freefx::dsp::readParameter (parameters, feedbackId));
        const auto mix = freefx::dsp::readParameter (parameters, mixId);

        // Guard the log-sweep bounds (matches the spirit of phaser.py's ranges).
        fmin = juce::jlimit (1.0f, static_cast<float> (sampleRate * 0.49), fmin);
        fmax = juce::jlimit (fmin + 1.0f, static_cast<float> (sampleRate * 0.49), fmax);
        const auto logMin = std::log (static_cast<double> (fmin));
        const auto logMax = std::log (static_cast<double> (fmax));

        const auto numSamples = buffer.getNumSamples();
        const auto phaseInc = juce::MathConstants<double>::twoPi * rate / sampleRate;

        for (int channel = 0; channel < numInputChannels; ++channel)
        {
            auto& state = channelStates[static_cast<size_t> (channel)];
            auto phase = lfoPhase;
            auto* data = buffer.getWritePointer (channel);

            for (int sample = 0; sample < numSamples; ++sample)
            {
                const auto f = std::exp (logMin + (logMax - logMin) * 0.5 * (1.0 + std::sin (phase)));
                const auto tn = std::tan (juce::MathConstants<double>::pi * f / sampleRate);
                const auto a1 = static_cast<float> ((tn - 1.0) / (tn + 1.0));

                const auto in = data[sample];
                auto s = in + fb * state.last;
                for (int k = 0; k < stages; ++k)
                {
                    const auto ap = a1 * s + state.zs[static_cast<size_t> (k)];
                    state.zs[static_cast<size_t> (k)] = s - a1 * ap;
                    s = ap;
                }
                state.last = s;
                data[sample] = (1.0f - mix) * in + mix * s;

                phase += phaseInc;
                if (phase >= juce::MathConstants<double>::twoPi)
                    phase -= juce::MathConstants<double>::twoPi;
            }
        }

        lfoPhase += phaseInc * numSamples;
        lfoPhase = std::fmod (lfoPhase, juce::MathConstants<double>::twoPi);
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-phaser"; }
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
    struct ChannelState
    {
        std::array<float, maxStages> zs { {} }; // one-pole all-pass states
        float last { 0.0f };                    // feedback memory
    };

    double sampleRate { 44100.0 };
    double lfoPhase { 0.0 };
    std::vector<ChannelState> channelStates;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PhaserProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new PhaserProcessor();
}
