# Modified for dependency-free TaskViews imports; see UPSTREAM.md.
__version__ = "0.1.0"

__all__ = ["Kobe", "__version__"]


def __getattr__(name):
    # The projection-only installation must not import device/VLM dependencies.
    if name == "Kobe":
        from ui_kobe.kobe import Kobe
        return Kobe
    raise AttributeError(name)
