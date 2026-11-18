# The "Hey Monkey" wake word

**"Hey Monkey" works out of the box.** The installer bundles a small open-vocabulary keyword spotter
(sherpa-onnx Zipformer, trained on GigaSpeech, about 5 MB) that listens for whatever phrase is in
Settings, with no training needed. The push-to-talk hotkey (default `Ctrl+Alt+Space`) always works too.

If you get too many false wake-ups or misses, you can train a dedicated
[openWakeWord](https://github.com/dscripka/openWakeWord) model. A trained model is usually more robust,
and Monkey uses it automatically when it's present.

## Optional: train a dedicated model (about 1 hour, free, no audio recording needed)

1. Open openWakeWord's **automatic model training** notebook in Google Colab (linked from the
   openWakeWord README, "Training New Models" → `notebooks/automatic_model_training.ipynb`).
2. Runtime → Change runtime type → **T4 GPU**.
3. Set:
   - `target_word = "hey monkey"`
   - `model_name = "hey_monkey"`
   - Leave the defaults for the number of synthetic examples and training steps.
4. Run all cells. The notebook generates thousands of synthetic "hey monkey" clips with different
   voices, mixes in background noise, trains, and gives you `hey_monkey.onnx` to download.

## Install it

Either:
- **No rebuild:** copy `hey_monkey.onnx` into `%APPDATA%\Monkey\wakeword\` and restart Monkey.
- **Ship it in the installer:** put it in this folder (`wakeword/hey_monkey.onnx`), commit, and tag a release.

## Tune it

Settings → Wake word sensitivity:
- **Lower** (0.3–0.4): wakes more easily, but more false wake-ups.
- **Higher** (0.6–0.7): fewer false wake-ups, but you may need to say it clearly.

Test it: say "Hey Monkey" 20 times from normal distance. Then leave Monkey running for an hour with music or
YouTube playing, and count false wake-ups. Aim for 18/20 or better and fewer than 1 false wake-up per hour.
While Monkey is talking, the threshold is raised automatically so his own voice doesn't wake him.
