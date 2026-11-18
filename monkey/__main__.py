import sys


def main() -> None:
    if "--selftest" in sys.argv:
        from .app import selftest

        sys.exit(selftest())
    from .app import run

    run()


if __name__ == "__main__":
    main()
