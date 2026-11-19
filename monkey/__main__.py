import sys


def _finish_transfer() -> None:
    """A "Move to a new PC" import is staged; swap it in before settings or the database are opened."""
    try:
        from .config import default_data_dir
        from .memory.export import apply_pending_transfer

        apply_pending_transfer(default_data_dir())
    except Exception:  # noqa: BLE001 - never block startup; the staged files stay put for the next try
        import logging

        logging.getLogger(__name__).exception("couldn't finish the PC transfer")


def main() -> None:
    from .updater import velopack_startup

    velopack_startup()  # Velopack hooks (install/update/uninstall) must run before anything else
    _finish_transfer()
    if "--routine" in sys.argv:
        from .app import run_routine

        i = sys.argv.index("--routine")
        sys.exit(run_routine(sys.argv[i + 1] if i + 1 < len(sys.argv) else ""))
    if "--selftest" in sys.argv:
        from .app import selftest

        sys.exit(selftest())
    from .app import run

    run()


if __name__ == "__main__":
    main()
