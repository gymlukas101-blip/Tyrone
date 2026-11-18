import sys


def main() -> None:
    from .updater import velopack_startup

    velopack_startup()  # Velopack hooks (install/update/uninstall) must run before anything else
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
