// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// irverb.py (convolution reverb — real spaces / plate IRs).
//
// Real-time note: irverb.py FFT-convolves the whole file against an impulse
// response offline. Here the streaming, partitioned juce::dsp::Convolution does
// the same convolution in real time. A generic VST3 editor can't take an IR
// file path, so this port synthesises irverb.py's `synth_ir` plate (decaying,
// HF-damped noise) on demand from a Size control; a Predelay control prepends
// silence to the IR exactly as the source does. Mix crossfades dry/wet.

#include <JuceHeader.h>
#include <cmath>
#include <vector>

#include "ParameterHelpers.h"

namespace
{
constexpr auto sizeId     = "size";        // IR length in seconds
constexpr auto mixId      = "mix";
constexpr auto predelayId = "predelayMs";

constexpr int convBlock = 512;             // fixed slice -> host-block-size agnostic
} // namespace

class IrVerbProcessor final : public juce::AudioProcessor
{
public:
    IrVerbProcessor()
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
            juce::ParameterID { sizeId, 1 }, "Size",
            freefx::dsp::skewedRange (0.2f, 5.0f, 0.01f, 2.0f), 2.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { mixId, 1 }, "Mix",
            Range { 0.0f, 1.0f, 0.001f }, 0.25f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { predelayId, 1 }, "Predelay",
            Range { 0.0f, 200.0f, 0.1f }, 0.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int samplesPerBlock) override
    {
        sampleRate = juce::jmax (newSampleRate, 1.0);

        juce::dsp::ProcessSpec spec;
        spec.sampleRate = sampleRate;
        spec.maximumBlockSize = static_cast<juce::uint32> (convBlock);
        spec.numChannels = 2;
        convolution.prepare (spec);
        convolution.reset();

        wetScratch.setSize (2, juce::jmax (samplesPerBlock, convBlock), false, false, true);
        lastSize = -1.0f;
        lastPredelay = -1.0f;
        loadIrIfNeeded (true);
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

        loadIrIfNeeded (false);

        const auto mix = freefx::dsp::readParameter (parameters, mixId);
        const auto numSamples = buffer.getNumSamples();

        // Wet path = convolution over a copy of the input, in fixed-size slices so
        // any host block size works (Convolution streams state across calls).
        if (wetScratch.getNumSamples() < numSamples)
            wetScratch.setSize (2, numSamples, false, false, true);

        for (int ch = 0; ch < 2; ++ch)
        {
            const auto src = ch < numInputChannels ? ch : 0;
            wetScratch.copyFrom (ch, 0, buffer, src, 0, numSamples);
        }

        juce::dsp::AudioBlock<float> wetBlock (wetScratch.getArrayOfWritePointers(), 2,
                                               static_cast<size_t> (numSamples));
        for (int pos = 0; pos < numSamples; pos += convBlock)
        {
            const auto n = static_cast<size_t> (juce::jmin (convBlock, numSamples - pos));
            auto sub = wetBlock.getSubBlock (static_cast<size_t> (pos), n);
            juce::dsp::ProcessContextReplacing<float> context (sub);
            convolution.process (context);
        }

        for (int ch = 0; ch < numInputChannels; ++ch)
        {
            auto* out = buffer.getWritePointer (ch);
            const auto* wet = wetScratch.getReadPointer (juce::jmin (ch, 1));
            for (int sample = 0; sample < numSamples; ++sample)
                out[sample] = (1.0f - mix) * out[sample] + mix * wet[sample];
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-irverb"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 5.2; }
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
    // Regenerate + load the synthetic plate IR when Size/Predelay change.
    void loadIrIfNeeded (bool force)
    {
        const auto size     = freefx::dsp::readParameter (parameters, sizeId);
        const auto predelay = freefx::dsp::readParameter (parameters, predelayId);
        if (! force && size == lastSize && predelay == lastPredelay)
            return;

        lastSize = size;
        lastPredelay = predelay;

        const auto predelaySamples = static_cast<int> (std::lround (predelay * sampleRate / 1000.0));
        const auto tailSamples = juce::jmax (1, static_cast<int> (std::lround (size * sampleRate)));
        const auto total = predelaySamples + tailSamples;

        juce::AudioBuffer<float> ir (1, total);
        ir.clear();
        auto* data = ir.getWritePointer (0);

        // synth_ir: decaying white noise, time-constant = size/5, then HF damped.
        juce::Random rng (20260705);
        const auto decayTau = sampleRate * size / 5.0;
        // One-pole lowpass ~8 kHz for plate-ish HF loss (matches butter LPF intent).
        const auto lpAlpha = static_cast<float> (1.0 - std::exp (-juce::MathConstants<double>::twoPi
                                                                 * juce::jmin (8000.0, sampleRate * 0.49) / sampleRate));
        float lpState = 0.0f;
        for (int i = 0; i < tailSamples; ++i)
        {
            const auto noise = rng.nextFloat() * 2.0f - 1.0f;
            const auto env = static_cast<float> (std::exp (-static_cast<double> (i) / decayTau));
            lpState += lpAlpha * (noise * env - lpState);
            data[predelaySamples + i] = lpState;
        }

        convolution.loadImpulseResponse (std::move (ir), sampleRate,
                                         juce::dsp::Convolution::Stereo::no,
                                         juce::dsp::Convolution::Trim::no,
                                         juce::dsp::Convolution::Normalise::yes);
    }

    double sampleRate { 44100.0 };
    float lastSize { -1.0f };
    float lastPredelay { -1.0f };
    juce::dsp::Convolution convolution;
    juce::AudioBuffer<float> wetScratch;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (IrVerbProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new IrVerbProcessor();
}
