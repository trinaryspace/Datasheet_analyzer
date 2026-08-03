# 4.12.1 TX Typical Characteristics 800 MHz

<!-- source: SBASAN1A p.27-35 -->

Typical values at TA = +25°C with nominal supplies. Default conditions: TX input data rate = 491.52 MSPS, fDAC = 11796.48 MSPS (24x interpolation), interleave mode, 1st Nyquist zone output, PLL clock mode with fREF = 491.52 MHz, AOUT = –1 dBFS, DSA = 0 dB, Sin(x)/x enabled, DSA calibrated, TX Clock Dither Enabled

## Figures

- **Figure 4-1 TX Output Fullscale vs Output Frequency** — including PCB and cable losses, Aout = -0.5 dFBS, DSA = 0, 0.8 GHz matching
- **Figure 4-3 TX Output Power vs DSA Setting and Channel at 0.85 GHz** — fDAC = 11796.48 MSPS, interleave mode, Aout = -0.5dFBS, matching 0.8 GHz
- **Figure 4-5 TX Calibrated Differential Gain Error vs DSA Setting and Channel at 0.85 GHz** — fDAC = 5898.24 MSPS, interleave mode, matching at 0.8 GHz Differential Gain Error = POUT(DSA Setting – 1) – POUT(DSA Setting) + 1
- **Figure 4-7 TX Calibrated Integrated Gain Error vs DSA Setting and Channel at 0.85 GHz** — fDAC =5898.24 MSPS, interleave mode, matching at 0.8 GHz Integrated Gain Error = POUT(DSA Setting ) – POUT(DSA Setting = 0) + DSA Setting
- **Figure 4-9 TX Calibrated Differential Gain Error vs DSA Setting and Temperature at 0.85 GHz** — fDAC = 5898.24 MSPS, interleave mode, matching at 0.8 GHz Differential Gain Error = POUT(DSA Setting – 1) – POUT(DSA Setting) + 1
- **Figure 4-11 TX Calibrated Integrated Gain Error vs DSA Setting and Temperature at 0.85 GHz** — fDAC = 5898.24MSPS, interleave mode, matching at 0.8 GHz Integrated Gain Error = POUT(DSA Setting ) – POUT(DSA Setting = 0) + DSA Setting
- **Figure 4-13 TX Calibrated Differential Phase Error vs DSA Setting and Channel at 0.85 GHz** — fDAC = 5898.24 MSPS, interleave mode, matching at 0.8 GHz Differential Phase Error = PhaseOUT(DSA Setting – 1) – PhaseOUT(DSA Setting) Phase DNL spike may occur at any DSA setting.
- **Figure 4-15 TX Calibrated Integrated Phase Error vs DSA Setting and Channel at 0.85 GHz** — fDAC = 5898.24 MSPS, interleave mode, matching at 0.8 GHz Integrated Phase Error = PhaseOUT(DSA Setting) – PhaseOUT(DSA Setting = 0)
- **Figure 4-17 TX Calibrated Integrated Phase Error vs DSA Setting and Temperature at 0.85 GHz** — fDAC = 5898.24 MSPS, interleave mode, matching at 0.8 GHz Integrated Phase Error = PhaseOUT(DSA Setting) – PhaseOUT(DSA Setting = 0)
- **Figure 4-19 TX IMD3 vs DSA Setting at 0.85 GHz** — fDAC = 11796.48 MSPS, interleave mode, fCENTER = 0.85 GHz, matching at 0.8 GHz, –13 dBFS each tone
- **Figure 4-21 TX IMD3 vs Tone Spacing and Channel at 0.85 GHz** — fDAC = 8847.36 MSPS, straight mode, fCENTER = 0.85 GHz, matching at 0.8 GHz, –13 dBFS each tone
- **Figure 4-23 TX IMD3 vs Tone Spacing and Temperature at 0.85 GHz** — fDAC = 5898.24 MSPS, straight mode, fCENTER =0.85 GHz, matching at 0.8 GHz, –13 dBFS each tone, worst channel
- **Figure 4-25 TX IMD3 vs Tone Spacing and Temperature at 0.85 GHz** — fDAC = 11796.48 MSPS, straight mode, fCENTER =0.85 GHz, matching at 0.8 GHz, –13 dBFS each tone, worst channel
- **Figure 4-27 TX IMD3 vs Digital Level at 0.85 GHz** — fDAC = 8847.36 MSPS, straight mode, fCENTER = 0.85 GHz, fSPACING = 20 MHz, matching at 0.8 GHz
- **Figure 4-29 TX Single Tone Output Noise vs Frequency and Amplitude at 0.85 GHz** — Matching at 2.6 GHz, Single tone, fDAC = 11.79648 GSPS, interleave mode, 40-MHz offset, DSA = 0dB
- **Figure 4-31 TX 20-MHz LTE ACPR vs Digital Level at 0.85 GHz** — Matching at 0.8 GHz, single carrier 20-MHz BW TM1.1 LTE
- **Figure 4-33 TX 20-MHz LTE ACPR vs DSA at 0.85 GHz** — Matching at 0.8 GHz, single carrier 20-MHz BW TM1.1 LTE
- **Figure 4-35 TX HD2 vs Digital Amplitude and Output Frequency at 0.85 GHz** — Matching at 0.8 GHz, fDAC = 5898.24G SPS, straight mode
- **Figure 4-37 TX HD3 vs Digital Amplitude and Output Frequency at 0.85 GHz** — Matching at 0.8 GHz, fDAC = 5898.24 MSPS, straight mode, normalized to output power at harmonic frequency
- **Figure 4-39 TX Single Tone (–12 dBFS) Output Spectrum at 0.85 GHz (0-fDAC)** — fDAC = 5898.24 MSPS, interleave mode, 0.8 GHz matching, includes PCB and cable losses. ILn = fS/n ± fOUT.
- **Figure 4-41 TX Single Tone (–1 dBFS) Output Spectrum at 0.85 GHz (0-fDAC)** — fDAC = 5898.24 MSPS, interleave mode, 0.8 GHz matching, includes PCB and cable losses. ILn = fS/n ± fOUT.
- **Figure 4-2 TX Output Fullscale vs Temperature** — including PCB and cable losses, Aout = -0.5 dFBS, DSA = 0, 0.8 GHz matching
- **Figure 4-4 TX Uncalibrated Differential Gain Error vs DSA Setting and Channel at 0.85 GHz** — fDAC=5898.24MSPS, interleave mode, matching at 0.8 GHz Differential Gain Error = POUT(DSA Setting – 1) – POUT(DSA Setting) + 1
- **Figure 4-6 TX Uncalibrated Integrated Gain Error vs DSA Setting and Channel at 0.85 GHz** — fDAC = 5898.24 MSPS, interleave mode, matching at 0.8 GHz Integrated Gain Error = POUT(DSA Setting ) – POUT(DSA Setting = 0) + DSA Settings
- **Figure 4-8 TX Uncalibrated Differential Gain Error vs DSA Setting and Temperature at 0.85 GHz** — fDAC = 5898.24 MSPS, interleave mode, matching at 0.8 GHz Differential Gain Error = POUT(DSA Setting – 1) – POUT(DSA Setting) + 1
- **Figure 4-10 TX Uncalibrated Integrated Gain Error vs DSA Setting and Temperature at 0.85 GHz** — fDAC = 5898.24 MSPS, interleave mode, matching at 0.8 GHz Integrated Gain Error = POUT(DSA Setting ) – POUT(DSA Setting = 0) + DSA Setting
- **Figure 4-12 TX Uncalibrated Differential Phase Error vs DSA Setting and Channel at 0.85 GHz** — fDAC = 5898.24MSPS, interleave mode, matching at 0.8 GHz Differential Phase Error = PhaseOUT(DSA Setting – 1) – PhaseOUT(DSA Setting)
- **Figure 4-14 TX Uncalibrated Integrated Phase Error vs DSA Setting and Channel at 0.85 GHz** — fDAC = 5898.24 MSPS, interleave mode, matching at 0.8 GHz Integrated Phase Error = PhaseOUT(DSA Setting) – PhaseOUT(DSA Setting = 0)
- **Figure 4-16 TX Uncalibrated Integrated Phase Error vs DSA Setting and Temperature at 0.85 GHz** — fDAC = 5898.24 MSPS, interleave mode, matching at 0.8 GHz Integrated Phase Error = PhaseOUT(DSA Setting) – PhaseOUT(DSA Setting = 0)
- **Figure 4-18 TX Output Noise vs Channel and Attenuation at 0.85 GHz** — fDAC = 5898.24 MSPS, interleave mode, matching at 0.8 GHz, POUT = –13 dBFS
- **Figure 4-20 TX IMD3 vs Tone Spacing and Channel at 0.85 GHz** — fDAC = 5898.24 MSPS, straight mode, fCENTER = 0.85 GHz, matching at 0.8 GHz, –13 dBFS each tone
- **Figure 4-22 TX IMD3 vs Tone Spacing and Channel at 0.85 GHz** — fDAC = 11796.48 MSPS, interleave mode, fCENTER = 0.85 GHz, matching at 0.8 GHz, –13 dBFS each tone
- **Figure 4-24 TX IMD3 vs Tone Spacing and Temperature at 0.85 GHz** — fDAC = 8847.36 MSPS, straight mode, fCENTER =0.85 GHz, matching at 0.8 GHz, –13 dBFS each tone, worst channel
- **Figure 4-26 TX IMD3 vs Digital Level at 0.85 GHz** — fDAC = 5898.24 MSPS, straight mode, fCENTER = 0.85 GHz, fSPACING = 20 MHz, matching at 0.8 GHz
- **Figure 4-28 TX IMD3 vs Digital Level at 0.85 GHz** — fDAC = 11796.48 MSPS, interleave mode, fCENTER = 0.85 GHz, fSPACING = 20 MHz, matching at 0.8 GHz
- **Figure 4-30 TX 20-MHz LTE Output Spectrum at 0.85 GHz** — TM1.1, POUT_RMS = –13 dBFS
- **Figure 4-32 TX 20-MHz LTE alt-ACPR vs Digital Level at 0.85 GHz** — Matching at 0.8 GHz, single carrier 20-MHz BW TM1.1 LTE
- **Figure 4-34 TX 20-MHz LTE alt-ACPR vs DSA at 0.85 GHz** — Matching at 0.8 GHz, single carrier 20-MHz BW TM1.1 LTE
- **Figure 4-36 TX HD2 vs Digital Amplitude and Output Frequency at 0.85 GHz** — Matching at 0.8 GHz, fDAC = 8847.36 GSPS, straight mode
- **Figure 4-38 TX HD3 vs Digital Amplitude and Output Frequency at 0.85 GHz** — Matching at 0.8 GHz, fDAC = 8847.36 MSPS, straight mode, normalized to output power at harmonic frequency
- **Figure 4-40 TX Single Tone (–6 dBFS) Output Spectrum at 0.85 GHz (0-fDAC)** — fDAC = 5898.24MSPS, interleave mode, 0.8 GHz matching, includes PCB and cable losses. ILn = fS/n ± fOUT.
