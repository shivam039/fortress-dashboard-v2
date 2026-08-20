# engine/pandas_ta.py
# Compatibility shim to map pandas_ta to pandas_ta_classic for Python 3.9
try:
    import pandas_ta_classic as _ta  # noqa: F401
    from pandas_ta_classic import *  # noqa: F401,F403
    from pandas_ta_classic import __version__  # noqa: F401

    # Ensure the .ta accessor works on dataframes if possible
    # pandas_ta_classic should already handle this on import
except ImportError:
    pass
