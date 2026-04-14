"""NWP data access via Herbie, driven by a TOML alias registry."""

from brc_tools.nwp.source import NWPSource

__all__ = ["NWPSource"]

# Submodules available via brc_tools.nwp.derived, brc_tools.nwp.alignment, etc.
