"""Hush - anonymous confessions for Discord.

The version lives in :mod:`app.__version__` and is re-exported here so
``app.__version__`` works as an attribute too. It is never written twice.
"""

from app.__version__ import __author__, __tagline__, __title__, __version__

__all__ = ["__version__", "__title__", "__tagline__", "__author__"]
