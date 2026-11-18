import sys


def main() -> None:
    from .updater import velopack_startup

    velopack_startup()  # Velopack hooks (install/update/uninstall) must run before anything else
    if "--selftest" in sys.argv:
        from .app import selftest

        sys.exit(selftest())
    from .app import run

    run()


if __name__ == "__main__":
    main()
