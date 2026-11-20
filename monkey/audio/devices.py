"""One lock around every PortAudio open/close/re-initialise.

PortAudio isn't safe to (re)initialise while another thread opens or closes a stream, and Pa_Terminate closes *every*
stream in the process — so when the microphone watchdog refreshes the device list, the speaker's output stream dies
too. Everything that touches PortAudio's lifetime takes PA_LOCK, and a reset notifies the speaker to reopen."""
from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger("monkey.audio")
PA_LOCK = threading.RLock()
_after_reset: list[Callable[[], None]] = []
_before_reset: list[Callable[[], None]] = []


def on_reset(fn: Callable[[], None], before: Callable[[], None] | None = None) -> None:
    """`before` runs under PA_LOCK just before Pa_Terminate (close your stream cleanly); `fn` runs after re-init."""
    if fn not in _after_reset:
        _after_reset.append(fn)
    if before is not None and before not in _before_reset:
        _before_reset.append(before)


def reset_portaudio() -> None:
    """Refresh the device list (new default after plugging in a headset), then reopen whoever registered."""
    import sounddevice as sd

    with PA_LOCK:
        for fn in list(_before_reset):
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.warning("closing a stream before the audio reset failed", exc_info=True)
        sd._terminate()
        sd._initialize()
    for fn in list(_after_reset):
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.warning("reopen after audio reset failed", exc_info=True)
