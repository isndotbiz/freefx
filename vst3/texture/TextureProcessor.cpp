// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// texture.py (lo-fi patina: sparse vinyl crackle + tape hiss + slow wow drift).
//
// Real-time note: texture.py builds the whole noise bed offline. Here the
// crackle impulses are generated per-sample with a seeded RNG at the same
// average rate (~80 pops/sec at full), band-passed by a persistent biquad
// pair; hiss is high-passed seeded noise; and wow is a continuous LFO sweeping
// a short fractional delay (a per-channel circular line). All filter, RNG, LFO
// and delay state is carried across processBlock.

#include <JuceHeader.h>
#include <cmath>
#include <vector>

#include "Biquad.h"
#include "ParameterHelpers.h"

namespace
{
constexpr auto crackleId = "crackle"; // vinyl crackle amount 0..1
constexpr auto hissId    = "hiss";    // tape hiss amount 0..1
constexpr auto wowId     = "wow";     // slow pitch drift, cents (0 = off)
constexpr auto seedId    = "seed";

// Wow needs a small delay line to read a drifting tap. texture.py's wow depth is
// (2^(cents/1200)-1)*0.02*sr samples around a 0.7 Hz LFO; at extreme cents this
// stays well under ~12ms, so 32ms of line is ample headroom.
constexpr double maxWowMs = 32.0;
} // namespace

class TextureProcessor final : public juce::AudioProcessor
{
public:
    TextureProcessor()
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
            juce::ParameterID { crackleId, 1 }, "Crackle",
            Range { 0.0f, 1.0f, 0.001f }, 0.4f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { hissId, 1 }, "Hiss",
            Range { 0.0f, 1.0f, 0.001f }, 0.2f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { wowId, 1 }, "Wow",
            Range { 0.0f, 50.0f, 0.01f }, 0.0f));
        params.push_back (std::make_unique<juce::AudioParameterInt> (
            juce::ParameterID { seedId, 1 }, "Seed", 0, 9999, 0));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int) override
    {
        sampleRate = juce::jmax (newSampleRate, 1.0);
        const auto channels = juce::jmax (getTotalNumInputChannels(), getTotalNumOutputChannels(), 1);

        // Band-pass for crackle (~800-6000 Hz) realised as HPF -> LPF (mono detector path).
        crackleHpf.prepare (1);
        crackleLpf.prepare (1);
        crackleHpf.reset();
        crackleLpf.reset();
        crackleHpf.setCoefficients (freefx::dsp::makeBiquad (
            freefx::dsp::BiquadKind::hpf, 800.0f, 0.0f, 0.707f, sampleRate));
        crackleLpf.setCoefficients (freefx::dsp::makeBiquad (
            freefx::dsp::BiquadKind::lpf, 6000.0f, 0.0f, 0.707f, sampleRate));

        // High-pass for hiss (~2000 Hz).
        hissHpf.prepare (1);
        hissHpf.reset();
        hissHpf.setCoefficients (freefx::dsp::makeBiquad (
            freefx::dsp::BiquadKind::hpf, 2000.0f, 0.0f, 0.707f, sampleRate));

        wowLines.assign (static_cast<size_t> (channels), std::vector<float> (
            static_cast<size_t> (std::ceil (maxWowMs * sampleRate / 1000.0)) + 4, 0.0f));
        wowWritePositions.assign (static_cast<size_t> (channels), 0);
        wowBufferLength = static_cast<int> (wowLines.empty() ? 1 : wowLines.front().size());
        wowPhase = 0.0;

        lastSeed = -1;
        seedRng (static_cast<int> (std::lround (freefx::dsp::readParameter (parameters, seedId))));
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

        const auto crackle = freefx::dsp::readParameter (parameters, crackleId);
        const auto hiss    = freefx::dsp::readParameter (parameters, hissId);
        const auto wowCents = freefx::dsp::readParameter (parameters, wowId);
        const auto seed = static_cast<int> (std::lround (freefx::dsp::readParameter (parameters, seedId)));
        if (seed != lastSeed)
            seedRng (seed);

        const auto numSamples = buffer.getNumSamples();

        // ---- 1) Wow: drift each channel through a short modulated delay ----
        if (wowCents > 0.0f)
        {
            const auto wowDepthSamples = (std::pow (2.0, wowCents / 1200.0) - 1.0) * 0.02 * sampleRate;
            const auto wowPhaseInc = juce::MathConstants<double>::twoPi * 0.7 / sampleRate;

            for (int channel = 0; channel < numInputChannels; ++channel)
            {
                auto& line = wowLines[static_cast<size_t> (channel)];
                auto writePos = wowWritePositions[static_cast<size_t> (channel)];
                auto phase = wowPhase;
                auto* data = buffer.getWritePointer (channel);

                for (int sample = 0; sample < numSamples; ++sample)
                {
                    // md in texture.py drifts 0..wowDepth around a 0.7Hz LFO.
                    const auto md = wowDepthSamples * (0.5 + 0.5 * std::sin (phase));
                    line[static_cast<size_t> (writePos)] = data[sample];

                    const auto delaySamplesF = juce::jlimit (0.0, static_cast<double> (wowBufferLength - 2), md);
                    const auto di = static_cast<int> (delaySamplesF);
                    const auto frac = static_cast<float> (delaySamplesF - di);
                    const auto read0 = wrapIndex (writePos - di, wowBufferLength);
                    const auto read1 = wrapIndex (writePos - di - 1, wowBufferLength);
                    data[sample] = line[static_cast<size_t> (read0)] * (1.0f - frac)
                                 + line[static_cast<size_t> (read1)] * frac;

                    writePos = wrapIndex (writePos + 1, wowBufferLength);
                    phase += wowPhaseInc;
                    if (phase >= juce::MathConstants<double>::twoPi)
                        phase -= juce::MathConstants<double>::twoPi;
                }

                wowWritePositions[static_cast<size_t> (channel)] = writePos;
            }

            wowPhase += juce::MathConstants<double>::twoPi * 0.7 / sampleRate * numSamples;
            wowPhase = std::fmod (wowPhase, juce::MathConstants<double>::twoPi);
        }

        // ---- 2 & 3) Crackle + hiss: one mono noise bed added to all channels ----
        // Average pops/sec at full crackle = 80 (texture.py npops = n/sr*80*crackle).
        const auto popProb = 80.0 * static_cast<double> (crackle) / sampleRate;
        const auto crackleScale = 0.15f * crackle; // texture.py: 0.15*crackle*crk
        const auto hissScale = 0.02f * hiss;       // texture.py: 0.02*hiss high-passed noise

        for (int sample = 0; sample < numSamples; ++sample)
        {
            // Sparse impulse: with probability popProb, a random-magnitude spike.
            float impulse = 0.0f;
            if (popProb > 0.0 && rng.nextDouble() < popProb)
                impulse = static_cast<float> (rng.nextDouble() * 2.0 - 1.0)
                        * static_cast<float> (rng.nextDouble()); // standard_normal-ish * uniform magnitude
            auto crk = crackleHpf.processSample (0, impulse);
            crk = crackleLpf.processSample (0, crk);

            const auto whiteHiss = static_cast<float> (rng.nextDouble() * 2.0 - 1.0);
            const auto hissBand = hissHpf.processSample (0, whiteHiss);

            const auto noise = crackleScale * crk + hissScale * hissBand;

            for (int channel = 0; channel < numInputChannels; ++channel)
                buffer.getWritePointer (channel)[sample] += noise;
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-texture"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return maxWowMs / 1000.0; }
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

    void seedRng (int seed)
    {
        rng.setSeed (static_cast<juce::int64> (seed) * 2654435761LL + 1);
        lastSeed = seed;
    }

    double sampleRate { 44100.0 };
    int lastSeed { -1 };
    juce::Random rng;

    freefx::dsp::BiquadFilter crackleHpf;
    freefx::dsp::BiquadFilter crackleLpf;
    freefx::dsp::BiquadFilter hissHpf;

    std::vector<std::vector<float>> wowLines;
    std::vector<int> wowWritePositions;
    int wowBufferLength { 1 };
    double wowPhase { 0.0 };

    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TextureProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new TextureProcessor();
}
