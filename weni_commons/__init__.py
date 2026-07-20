"""
weni-commons — shared utilities for Weni Python backends.

``FeatureFlagsService`` is re-exported lazily so that importing lightweight
submodules (e.g. ``weni_commons.kong``) does not pull in the feature-flags
stack, which requires extra Django settings and an installed app. The heavy
import only happens when ``weni_commons.FeatureFlagsService`` is actually
accessed.
"""

__all__ = ["FeatureFlagsService"]


def __getattr__(name):
    if name == "FeatureFlagsService":
        from weni.feature_flags.services import FeatureFlagsService

        return FeatureFlagsService

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals().keys()) + __all__)
