# Test patterns (optional)

Three grey test videos for seeing what HDRDesk's controls, especially the **highlight cap**, actually do on your screen. You don't need them to use HDRDesk; they just make the effect easy to see and fine-tune.

| File | What it shows |
| --- | --- |
| `grey-steps-17.mp4` | 17 labelled grey bars from black (0) to white (255) |
| `grey-steps-34.mp4` | 34 narrower bars for finer steps |
| `grey-gradient.mp4` | A smooth black-to-white ramp with code markers every 16 |

Each is a 10-minute still image (standard SDR video, BT.709, 3440×1440), so it stays on screen while you adjust sliders. The lit strip covers only about a tenth of the screen, which keeps the monitor's own brightness limiting out of the way.

## Why use them

- **See where the cap kicks in.** Tick **Highlight cap** and drag the cap and knee: the bars below the knee stay as they are, and the brighter bars start to bunch together as they approach the cap. Untick it to compare.
- **Check RTX Video HDR.** RTX Video HDR brightens the top of the range most. Watch how far apart the brightest bars spread with it on, and how the cap pulls them back in.
- **Tune by eye.** Use the gradient to check the roll-off looks smooth, with no visible step where the knee is.

Screenshots won't show any of this: the gamma ramp is applied after the screen is captured. Look at the monitor itself, or take a photo of it.

## How to use

1. Turn on Windows HDR and open HDRDesk.
2. Open a video:
   - **To test RTX Video HDR:** turn it on (HDRDesk's **RTX HDR ▸** panel or the NVIDIA App), then drag the file onto a browser window that supports it (Chrome, Edge or Firefox) and make it fullscreen. NVIDIA shows an "RTX HDR" badge when the conversion is active.
   - **Otherwise:** open it in your favourite video player. This shows how SDR content looks in HDR mode, the same as your desktop.
3. Adjust HDRDesk's sliders while watching the bars. The labels under the bars are the 0–255 grey level of each one.
