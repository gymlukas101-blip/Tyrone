try:  # stamped by CI at build time
    from ._version import __version__  # type: ignore
except ImportError:  # dev checkout
    __version__ = "0.3.0-dev"
