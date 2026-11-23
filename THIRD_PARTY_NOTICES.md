# Third-party notices

Monkey is built on other people's work. This file covers the models, data and web libraries that ship in (or are
downloaded by) the app. Python packages are listed automatically in `THIRD_PARTY_LICENSES.txt`, which the build
generates from each package's own metadata (`tools/notices.py`). Both files ship next to `Monkey.exe`.

If a license below disagrees with the upstream project, the upstream license wins; please report the mistake.

## Bundled in the installer

| Component | Used for | License | Source |
|---|---|---|---|
| sherpa-onnx | "Hey Monkey" keyword spotting runtime | Apache-2.0 | github.com/k2-fsa/sherpa-onnx |
| sherpa-onnx KWS Zipformer (GigaSpeech, 3.3M) | the keyword-spotting model | Apache-2.0 (k2-fsa releases) | github.com/k2-fsa/sherpa-onnx/releases (kws-models) |
| Silero VAD | voice activity detection | MIT | github.com/snakers4/silero-vad |
| openWakeWord (code) | fallback wake word | Apache-2.0 | github.com/dscripka/openWakeWord |
| openWakeWord pre-trained models (`hey_jarvis` and its feature models) | fallback wake word | **CC BY-NC-SA 4.0** (non-commercial, share-alike) | same repository |
| faster-whisper, CTranslate2 | speech to text | MIT | github.com/SYSTRAN/faster-whisper, github.com/OpenNMT/CTranslate2 |
| Playwright for Python and its Node driver | computer tasks in a browser | Apache-2.0 | github.com/microsoft/playwright-python |
| Playwright MCP extension relay (adapted, see `monkey/automation/chrome_bridge.py`) | Monkey for Chrome bridge | Apache-2.0 | github.com/microsoft/playwright-mcp |
| Velopack | installer and auto-update | MIT | github.com/velopack/velopack |
| Python runtime (via PyInstaller) | the app itself | PSF License | python.org |
| PyInstaller bootloader | the app's launcher | GPL-2.0 with the bootloader exception (allows distributing apps built with it) | pyinstaller.org |

The openWakeWord models are only a fallback; the default wake word uses the sherpa-onnx model. Monkey is a personal,
non-commercial assistant, which the CC BY-NC-SA terms allow. Anyone redistributing Monkey commercially must remove or
replace those models.

## Web UI (bundled into `ui/dist`)

| Library | License |
|---|---|
| three.js | MIT |
| marked | MIT |
| DOMPurify | MPL-2.0 OR Apache-2.0 |
| qrcode-generator (phone setup QR code, drawn locally) | MIT |
| Lilita One font (@fontsource/lilita-one) | SIL Open Font License 1.1 |
| Titan One font (Rodrigo Fuenzalida; unmodified file from @fontsource/titan-one 5.3.0, `ui/src/fonts/`) | SIL Open Font License 1.1, Reserved Font Name "Titan One"; text in `ui/src/fonts/OFL-TitanOne.txt` |
| Nunito variable font (The Nunito Project Authors; from @fontsource-variable/nunito 5.3.0, `ui/src/fonts/`) | SIL Open Font License 1.1; text in `ui/src/fonts/OFL-Nunito.txt` |

## Downloaded on your PC when you turn them on (not in the installer)

| Component | Used for | License / terms | Source |
|---|---|---|---|
| Whisper model weights (CTranslate2 conversions) | speech to text | MIT (OpenAI Whisper) | huggingface.co/Systran |
| Pocket TTS model | offline voice | as published by Kyutai on the model card; check it before redistributing | huggingface.co/kyutai |

## Services (not shipped; used through your own accounts)

Claude (Anthropic), Fish Audio, Google (Gmail, Calendar), Canvas, Garmin Connect and Outlook are used through your own
accounts and API keys, under each service's terms. Sound effects in `ui/public/sfx` were generated with ElevenLabs on the
owner's account, under ElevenLabs' terms for generated audio.
