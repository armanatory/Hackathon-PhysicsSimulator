---
name: allsolve-postprocessing
description: >-
  FFT post-processing for Allsolve transient simulations: windowing, zero-padding,
  impedance, transmit/receive sensitivity, fractional bandwidth, KPI extraction,
  and plotting. Use when computing impedance, Tx/Rx sensitivity, FFT, spectrum,
  bandwidth, centre frequency, or frequency-domain quantities from transient data.
---

# Allsolve post-processing

Primarily for extracting frequency-domain quantities (impedance, sensitivity, bandwidth) from transient simulation data. Most applicable to acoustic/piezoelectric device workflows — for S-parameter extraction see `allsolve-domain-rf`, for general output handling see `allsolve-simulation`.

## Where to compute the FFT

| Scenario | Method | Pros | Cons |
|---|---|---|---|
| One-off analysis / plotting | Local Python | Fast iteration, full matplotlib | Requires CSV download roundtrip |
| KPIs needed in sweep outputs | In-simulation (custom code section) | KPIs in output data, no roundtrip | More complex setup, harder to debug |
| Frequency-domain spectra in output data | In-simulation + CSV file write | Spectra downloadable via SDK | Large output for dense spectra |

Use local Python for exploratory work. Switch to in-simulation for production sweeps where KPIs drive parameter selection.

## Right-hand Hanning window

Apply to time-domain signals before FFT to suppress spectral leakage from incomplete ringdown. Preserves excitation onset, tapers the tail to zero.

```python
def apply_right_hanning(signal):
    n = len(signal)
    window = np.ones(n)
    n_taper = n - n // 2
    window[n // 2:] = 0.5 * (1 + np.cos(np.pi * np.arange(n_taper) / n_taper))
    return signal * window
```

**When to use:** Always for transient wavelet-driven simulations (piezocomposite, PMUT, pulse-echo). Not needed for CW harmonic analysis.

## Zero-padding

Standard: **20x zero-padding** (`n_pad = n * 20`). Interpolates FFT spectrum to finer frequency bins without adding new spectral information.

```python
n_pad = len(signal) * 20
freqs = np.fft.rfftfreq(n_pad, d=dt)
spectrum = np.fft.rfft(windowed_signal, n=n_pad)
```

20x is a good default for smooth spectral curves; 10x acceptable for coarse sweeps.

## Standard frequency-domain quantities

### Electrical impedance

```python
I_safe = np.where(np.abs(I_fft) > 1e-30, I_fft, 1e-30)
Z = V_fft / I_safe
Z_mag = np.abs(Z)
Z_phase = np.angle(Z, deg=True)
```

### Transmit sensitivity (Tx)

```python
V_safe = np.where(np.abs(V_fft) > 1e-30, V_fft, 1e-30)
tx = np.abs(P_fft / V_safe)  # Pa/V
```

Where `P_fft = FFT(pressure_on_front_face)`, `V_fft = FFT(drive_voltage)`.

### Receive sensitivity (Rx)

```python
rx = np.abs(V_oc_fft / P_inc_fft)  # V/Pa
```

Requires a receive simulation with incident pressure excitation and open-circuit voltage measurement.

## KPI extraction

### Centre frequency (fc)

Peak of the Tx sensitivity spectrum in the valid frequency range:

```python
mask = (freqs > f_min) & (freqs < f_max)
idx_peak = np.argmax(tx_mag[mask])
fc = freqs[mask][idx_peak]
```

### Fractional bandwidth (-6 dB)

```python
threshold = max_tx / 2.0  # -6 dB in linear
below = tx_masked[:idx_peak]
cl = np.where(below < threshold)[0]
f_lower = freqs_masked[cl[-1]] if len(cl) > 0 else freqs_masked[0]
above = tx_masked[idx_peak:]
ch = np.where(above < threshold)[0]
f_upper = freqs_masked[idx_peak + ch[0]] if len(ch) > 0 else freqs_masked[-1]
fbw = (f_upper - f_lower) / fc
```

### Impedance at centre frequency

```python
z_idx = np.argmin(np.abs(freqs - fc))
Z_at_fc = Z_mag[z_idx]
```

## In-simulation FFT (custom script section — solver-side only)

Use `AFTER_FORMULATIONS_CREATED` with disabled `SOLVE` section (see `allsolve-simulation-scripts`). The custom code creates the timestepper, runs the time loop with data capture, then computes FFT and outputs KPIs.

These calls use the **solver script API** (`import quanscient as qs`) — they run inside the cloud solver, not in local SDK code:

```python
qs.setoutputvalue("fc_Hz", fc)
qs.setoutputvalue("max_tx_sensitivity_PaV", max_tx)
qs.setoutputvalue("Z_mag_at_fc_Ohm", z_fc)
qs.setoutputvalue("fractional_bandwidth", fbw)

# Frequency-domain array outputs (frequency as the step coordinate):
for k in range(len(f_out)):
    qs.setoutputvalue("Z_mag_spectrum", float(z_out[k]), float(f_out[k]))
    qs.setoutputvalue("tx_sensitivity_spectrum", float(tx_out[k]), float(f_out[k]))
```

## Plotting conventions

- **Log y-axis** for all magnitude spectra (impedance, sensitivity, PSD)
- **x-axis floor** above DC to hide artefacts (e.g. 100 kHz for MHz-range devices)
- **Clip magnitudes** before log: `np.maximum(Z_mag, 1e-30)`
- **Mark KPIs on plots**: vertical lines for fc, f_lower, f_upper; horizontal line for -6 dB threshold
- **4-panel standard**: time signals | |Z| | Z phase | Tx sensitivity

## Gotchas

- **Guard division by zero** — always use `np.where(np.abs(x) > 1e-30, x, 1e-30)` before dividing by FFT results.
- **`numpy` and `scipy` are available** in solver custom script sections — use freely for in-simulation FFT.
- **`qs.setoutputvalue(name, value, step)` for array outputs** — the third arg acts as the x-coordinate (time or frequency).
- **For harmonic analysis (FBAR), impedance is computed directly** from port V and I — no FFT needed. FFT is only for transient simulations.
