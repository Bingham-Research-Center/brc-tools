"""External API client wrappers.

Thin per-service clients (one subpackage each) sharing a common auth
helper. Import the client you need:

    from brc_tools.api.flightaware import FlightAwareClient
    from brc_tools.api.perplexity import PerplexityClient

See `docs/API-CLIENTS.md` for setup, env vars, and cost notes.
"""
