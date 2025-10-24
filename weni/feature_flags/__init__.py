import importlib
import sys

_real_pkg = importlib.import_module("weni_feature_flags")

sys.modules[__name__] = _real_pkg
