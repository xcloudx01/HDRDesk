# HDRDesk

**Live display and RTX Video HDR controls for Windows.**

Adjust desktop brightness, contrast, gamma, Windows SDR content brightness, and NVIDIA RTX Video HDR from one compact, keyboard-friendly window. Keep the controls on top of the content you're watching and tune the image without navigating three separate settings interfaces.

![HDRDesk with its RTX Video HDR panel expanded](docs/screenshot.png)

## Features

- **Desktop colour:** GPU gamma-ramp brightness, contrast and gamma, with a one-click neutral reset.
- **Windows HDR:** adjust SDR content brightness from 0–100, with the corresponding nominal SDR white level shown in nits (80–480).
- **RTX Video HDR:** enable or disable SDR-to-HDR video conversion and adjust peak brightness, middle grey, contrast and saturation live.
- **Always-on-top window:** tune against the content itself; collapse the RTX panel when not needed.
- **Keyboard control:** select and adjust sliders without repeatedly reaching for the mouse.
- **State synchronization:** follow external changes to SDR white level and RTX Video HDR settings; reapply the configured GPU gamma ramp when it is lost.
- **Lightweight:** Python standard library only for the main application; no administrator elevation needed for the live RTX Video HDR control path on the tested configuration.

## Quick start

### Portable Windows executable (x64)

**[Download HDRDesk.exe from the latest release](../../releases/latest/download/HDRDesk.exe)** (Windows x64). See [Releases](../../releases) for versioned downloads. The [Windows build workflow](../../actions/workflows/build-windows.yml) packages the current source into a single, windowed executable; stable downloads are published separately through the release workflow. No Python installation is required for the executable. Place it in a writable folder; `settings.json` is saved alongside it. The executable is unsigned, so Windows may display a SmartScreen warning.

### Run from source

1. Download or clone the repository and keep its Python files together.
2. Install Python 3 for Windows with Tcl/Tk support (included in the standard Python installer).
3. Double-click `HDRDesk.pyw`, or run:

   ```powershell
   pythonw HDRDesk.pyw
   ```

For RTX Video HDR, enable Windows HDR on a compatible display, use a supported NVIDIA RTX GPU and driver, and open **NVIDIA App → System → Video** once if the driver registry settings have not been initialized. Use a compatible browser or video player for RTX Video HDR playback.

### Controls

| Setting | Range / behavior |
| --- | --- |
| Desktop brightness | −100 to +100 |
| Desktop contrast | −100 to +100 |
| Desktop gamma | 0.30–2.80 |
| SDR content brightness | 0–100 (nominal 80–480 nits) |
| RTX Video HDR | On / off |
| RTX peak brightness | 400–1000 nits |
| RTX middle grey | 10–100 nits |
| RTX contrast | −100% to +100% |
| RTX saturation | −100% to +100% |

Desktop brightness and contrast here are software GPU LUT adjustments, not physical monitor brightness or OSD settings. The nit values are requested/reference levels, not measurements of physical panel luminance.

**Reset colour** restores neutral brightness, contrast and gamma. **Reset RTX HDR** restores the application's 400 / 50 / 0 / 0 baseline without changing the RTX Video HDR enable state.

### Keyboard

| Input | Action |
| --- | --- |
| Up / Down | Select previous / next slider; wraps through visible, enabled controls |
| Left / Right | Adjust by 1% of slider range |
| Shift + Left / Right | Fine adjustment of one internal unit |
| Ctrl + Left / Right | Coarse adjustment of 5% of range |
| Hold Left / Right | Repeat after 350 ms |
| Delete or double-click | Reset selected slider where a default is defined |

## Compatibility and limitations

Developed and reported tested on:

- Windows 11 with HDR enabled
- Alienware AW3423DWF
- NVIDIA GeForce RTX 3090
- NVIDIA display driver version `32.0.16.3020`

Other configurations have not been established by the supplied testing. The UI targets the primary display; independent multi-monitor control has not been implemented. Windows HDR must be enabled separately. RTX Video HDR is NVIDIA's **video** conversion feature, not RTX HDR for games.

The Windows SDR-white setter and NVIDIA driver-private calls are undocumented. Driver or Windows updates may change their behavior. GPU gamma-ramp effects in HDR mode also depend on the display path; this is an interactive adjustment tool, not a colorimeter calibration application.

HDRDesk applies its saved desktop colour settings at launch and maintains the gamma ramp while running. This can conflict with other LUT loaders or calibration software. Closing the application does not automatically restore the original display settings.

If you need to restore a neutral desktop gamma ramp, close HDRDesk and run:

```powershell
python reset.py
```

This resets the primary display's GPU gamma ramp only; it does not restore SDR brightness, RTX Video HDR or a previous custom calibration.

## How it works

| Control | Mechanism |
| --- | --- |
| Desktop brightness / contrast / gamma | GDI `SetDeviceGammaRamp` |
| Windows SDR content brightness | Undocumented `DisplayConfigSetDeviceInfo` request, type `0xFFFFFFEE` |
| RTX Video HDR | Driver-private `D3DKMTEscape` requests, reconstructed from NVIDIA App traffic |

Unlike tools that only modify RTX Video HDR registry values and depend on the driver reloading them, HDRDesk sends the driver commands directly. The driver response is checked, and the persisted registry state is read to synchronize the UI.

### RTX Video HDR internals

The driver stores settings under its NVIDIA adapter class key:

```text
HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\00xx
```

Global values use `_User_Global_VAL_TrueHDR` and the `_P`, `_M`, `_C`, `_S` suffixes, with per-display copies such as `_User_SUB0_DFP1_*`. Contrast and saturation are encoded as UI value + 100. Direct registry edits did not apply live on the tested configuration.

The live path replays a captured 112-byte driver-private escape:

```text
D3DKMTEscape(type=DRIVERPRIVATE, flags=0x8)
+00 'ADVN' 0x00010002 0x70 'NV**'
+10 command 0x0100003B
+30 0x00010040
+34 setting ID
+38/+3C/+40 scope
+44 value

IDs: 0x1E enable, 0x1F contrast, 0x20 saturation,
     0x21 middle grey, 0x22 peak, 0x23 commit (257)
Scopes: (2,0,0) global, (0,1,1) per-display
Response: +14 == 1 indicates driver acceptance
```

The per-display scope is the captured scope, not a general multi-monitor targeting implementation. See `nvescape.py` and the reverse-engineering tools for details.

## Repository layout

| Path | Purpose |
| --- | --- |
| `HDRDesk.pyw` | Tkinter application |
| `displaycore.py` | Windows DisplayConfig and GPU gamma ramp |
| `nvescape.py` | Live RTX Video HDR driver requests |
| `nvhdr.py` | NVIDIA settings discovery, registry read and persistence-only helper |
| `reset.py` | Emergency neutral gamma-ramp reset |
| `selftest.py` | Interactive Windows system-state checks |
| `tools/` | Driver tracing, registry diagnostics and display-control probes |

The self-test changes live settings and attempts to restore SDR and RTX values and a neutral gamma ramp; run it only when such changes are acceptable.

The optional Frida tracing tools require a separate Frida installation and elevation; neither is needed to run HDRDesk. The screenshot shows the original window title.

## Project status

Experimental Windows utility. When reporting compatibility problems, include your Windows build, NVIDIA driver version, GPU, monitor, HDR mode and which control failed.
