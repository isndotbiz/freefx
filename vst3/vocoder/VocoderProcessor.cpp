// MIT License
//
// Copyright (c) 2026 Jonathan Mallinger
//
// Part of the freefx open-source effects suite; clean-room DSP ported from
// vocoder.py (channel vocoder: split the modulator into N log-spaced bands,
// follow each band's energy, and impose those envelopes on the same bands of a
// built-in saw/noise carrier so the carrier "talks").
//
// Real-time note: vocoder.py reads a whole modulator file, builds the carrier
// offline, then filters/follows/synthesises per band. Here the modulator is the
// (mono-summed) plugin input, the carrier is generated per-sample internally
// (a band-limited-ish saw harmonic stack via a phase accumulator, or seeded
// noise), and every band keeps persistent band-pass states (modulator + carrier)
// plus a one-pole envelope follower carried across processBlock. The synthesised
// mono vocoder output is written to all channels, blended with the dry modulator
// by the mix control.

#include <JuceHeader.h>
#include <array>
#include <cmath>

#include "Biquad.h"
#include "ParameterHelpers.h"

namespace
{
constexpr auto carrierId = "carrier"; // 0 = saw, 1 = noise
constexpr auto bandsId    = "bands";
constexpr auto envMsId    = "envMs";
constexpr auto mixId      = "mix";

constexpr int maxBands = 40;
constexpr double carrierF0 = 110.0;     // saw fundamental (matches vocoder.py f0)
constexpr int    sawHarmonics = 40;     // 1/h saw stack, same as vocoder.py
} // namespace

class VocoderProcessor final : public juce::AudioProcessor
{
public:
    VocoderProcessor()
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

        params.push_back (std::make_unique<juce::AudioParameterChoice> (
            juce::ParameterID { carrierId, 1 }, "Carrier",
            juce::StringArray { "Saw", "Noise" }, 0));
        params.push_back (std::make_unique<juce::AudioParameterInt> (
            juce::ParameterID { bandsId, 1 }, "Bands", 4, maxBands, 24));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { envMsId, 1 }, "Env",
            freefx::dsp::skewedRange (1.0f, 100.0f, 0.01f, 15.0f), 15.0f));
        params.push_back (std::make_unique<juce::AudioParameterFloat> (
            juce::ParameterID { mixId, 1 }, "Mix",
            Range { 0.0f, 1.0f, 0.001f }, 1.0f));

        return { params.begin(), params.end() };
    }

    void prepareToPlay (double newSampleRate, int) override
    {
        sampleRate = juce::jmax (newSampleRate, 1.0);
        for (auto& band : bands)
        {
            band.modHpf.prepare (1);
            band.modLpf.prepare (1);
            band.carHpf.prepare (1);
            band.carLpf.prepare (1);
            band.modHpf.reset();
            band.modLpf.reset();
            band.carHpf.reset();
            band.carLpf.reset();
            band.env = 0.0f;
        }
        lastBands = -1;
        sawPhase = 0.0;
        noiseRng.setSeed (1);
        updateBandCoefficients (static_cast<int> (std::lround (freefx::dsp::readParameter (parameters, bandsId))));
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

        const auto carrierNoise = freefx::dsp::readParameter (parameters, carrierId) >= 0.5f;
        const auto numBands = juce::jlimit (1, maxBands,
            static_cast<int> (std::lround (freefx::dsp::readParameter (parameters, bandsId))));
        const auto envMs = freefx::dsp::readParameter (parameters, envMsId);
        const auto mix   = freefx::dsp::readParameter (parameters, mixId);

        if (numBands != lastBands)
            updateBandCoefficients (numBands);

        const auto envC = static_cast<float> (std::exp (-1.0 / (sampleRate * envMs / 1000.0)));
        const auto sawPhaseInc = juce::MathConstants<double>::twoPi * carrierF0 / sampleRate;

        const auto numSamples = buffer.getNumSamples();
        const auto invInputChannels = numInputChannels > 0 ? 1.0f / static_cast<float> (numInputChannels) : 1.0f;

        for (int sample = 0; sample < numSamples; ++sample)
        {
            // Modulator = mono sum of the input (vocoder.py mean across channels).
            float modulator = 0.0f;
            for (int channel = 0; channel < numInputChannels; ++channel)
                modulator += buffer.getReadPointer (channel)[sample];
            modulator *= invInputChannels;

            // Carrier generated internally.
            float carrier;
            if (carrierNoise)
            {
                carrier = static_cast<float> (noiseRng.nextDouble() * 2.0 - 1.0) * 0.3f;
            }
            else
            {
                double saw = 0.0;
                for (int h = 1; h <= sawHarmonics; ++h)
                    saw += (1.0 / h) * std::sin (sawPhase * h);
                carrier = static_cast<float> (0.3 * saw / sawNorm);
            }

            float out = 0.0f;
            for (int b = 0; b < numBands; ++b)
            {
                auto& band = bands[static_cast<size_t> (b)];

                auto mb = band.modHpf.processSample (0, modulator);
                mb = band.modLpf.processSample (0, mb);
                auto cb = band.carHpf.processSample (0, carrier);
                cb = band.carLpf.processSample (0, cb);

                // One-pole smooth |modulator band| (vocoder.py lfilter one-pole).
                const auto rect = std::abs (mb);
                band.env = envC * band.env + (1.0f - envC) * rect;

                out += cb * band.env;
            }
            out *= 3.0f; // filterbank loses level; restore (matches vocoder.py *3.0)

            const auto wet = mix * out + (1.0f - mix) * modulator;
            for (int channel = 0; channel < numOutputChannels; ++channel)
                buffer.getWritePointer (channel)[sample] = wet;

            sawPhase += sawPhaseInc;
            if (sawPhase >= juce::MathConstants<double>::twoPi)
                sawPhase -= juce::MathConstants<double>::twoPi;
        }
    }

    juce::AudioProcessorEditor* createEditor() override
    {
        return new juce::GenericAudioProcessorEditor (*this);
    }

    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "freefx-vocoder"; }
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
        freefx::dsp::BiquadFilter modHpf, modLpf;
        freefx::dsp::BiquadFilter carHpf, carLpf;
        float env { 0.0f };
    };

    void updateBandCoefficients (int numBands)
    {
        numBands = juce::jlimit (1, maxBands, numBands);
        // Log-spaced edges 120 Hz .. min(8000, nyquist-200), as in vocoder.py.
        const auto nyquist = sampleRate * 0.5;
        const auto top = juce::jmin (8000.0, nyquist - 200.0);
        const auto logLo = std::log10 (120.0);
        const auto logHi = std::log10 (juce::jmax (top, 200.0));

        for (int b = 0; b < numBands; ++b)
        {
            const auto loEdge = std::pow (10.0, logLo + (logHi - logLo) * b / numBands);
            const auto hiEdge = std::pow (10.0, logLo + (logHi - logLo) * (b + 1) / numBands);
            const auto loHz = static_cast<float> (juce::jlimit (1.0, nyquist * 0.98, loEdge));
            const auto hiHz = static_cast<float> (juce::jlimit (static_cast<double> (loHz) + 1.0, nyquist * 0.98, hiEdge));

            auto& band = bands[static_cast<size_t> (b)];
            const auto hpf = freefx::dsp::makeBiquad (freefx::dsp::BiquadKind::hpf, loHz, 0.0f, 0.707f, sampleRate);
            const auto lpf = freefx::dsp::makeBiquad (freefx::dsp::BiquadKind::lpf, hiHz, 0.0f, 0.707f, sampleRate);
            band.modHpf.setCoefficients (hpf);
            band.modLpf.setCoefficients (lpf);
            band.carHpf.setCoefficients (hpf);
            band.carLpf.setCoefficients (lpf);
        }
        lastBands = numBands;
    }

    static double computeSawNorm()
    {
        // Peak of the 1/h saw stack over one cycle (for the 0.3*sig/max(|sig|) scale).
        double maxAbs = 1.0e-9;
        const int steps = 2048;
        for (int i = 0; i < steps; ++i)
        {
            const auto phase = juce::MathConstants<double>::twoPi * i / steps;
            double s = 0.0;
            for (int h = 1; h <= sawHarmonics; ++h)
                s += (1.0 / h) * std::sin (phase * h);
            maxAbs = std::max (maxAbs, std::abs (s));
        }
        return maxAbs;
    }

    double sampleRate { 44100.0 };
    int lastBands { -1 };
    double sawPhase { 0.0 };
    const double sawNorm { computeSawNorm() };
    juce::Random noiseRng;
    std::array<Band, maxBands> bands;
    juce::AudioProcessorValueTreeState parameters;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (VocoderProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new VocoderProcessor();
}
