"""Single source of truth for the Hush version.

Nothing else in the project hard-codes a version number. ``/about``, the
startup log, the About embed and packaging all read from here.
"""

from __future__ import annotations

__version__ = "1.0.0"
__title__ = "Hush"
__tagline__ = "Anonymous confessions made simple."
__author__ = "Hush Development"

#: Shown wherever a full identifier is useful, e.g. logs and status embeds.
VERSION_STRING = f"{__title__} v{__version__}"
