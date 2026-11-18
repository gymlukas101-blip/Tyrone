# Training the "Yo Tyrone" wake word

Tyrone uses [openWakeWord](https://github.com/dscripka/openWakeWord) (free, open source, runs offline).
Until `yo_tyrone.onnx` exists, Tyrone listens for the built-in **"Hey Jarvis"** model instead, and the
push-to-talk hotkey (default `Ctrl+Alt+Space`) always works.

## Train it (about 1 hour, free, no audio recording needed)

1. Open openWakeWord's **automatic model training** notebook in Google Colab (linked from the
   openWakeWord README, "Training New Models" → `notebooks/automatic_model_training.ipynb`).
2. Runtime → Change runtime type → **T4 GPU**.
3. Set:
   - `target_word = "yo tyrone"`
   - `model_name = "yo_tyrone"`
   - Leave the defaults for the number of synthetic examples and training steps.
4. Run all cells. The notebook generates thousands of synthetic "yo tyrone" clips with different
   voices, mixes in background noise, trains, and gives you `yo_tyrone.onnx` to download.

## Install it

Either:
- **No rebuild:** copy `yo_tyrone.onnx` into `%APPDATA%\Tyrone\wakeword\` and restart Tyrone.
- **Ship it in the installer:** put it in this folder (`wakeword/yo_tyrone.onnx`), commit, and tag a release.

## Tune it

Settings → Wake word sensitivity:
- **Lower** (0.3–0.4): wakes more easily, but more false wake-ups.
- **Higher** (0.6–0.7): fewer false wake-ups, but you may need to say it clearly.

Test it: say "Yo Tyrone" 20 times from normal distance. Then leave Tyrone running for an hour with music or
YouTube playing, and count false wake-ups. Aim for 18/20 or better and fewer than 1 false wake-up per hour.
While Tyrone is talking, the threshold is raised automatically so his own voice doesn't wake him.
