"""Stub FlightRadar24 client.

FR24 has no free tier — the lowest paid plan is ~$9/mo with a credit
budget. Methods raise `NotImplementedError` until a subscription is in
place; revisit when there is a concrete use case to justify the spend.
"""

from brc_tools.api._auth import load_api_key


class FR24Client:
    """Skeleton FR24 client. Auth via `FR24_API_KEY` (when wired up)."""

    BASE_URL = "https://fr24api.flightradar24.com/api"

    def __init__(self):
        self.api_key = load_api_key("FR24_API_KEY")

    def get_live_flight_positions(self, *_, **__) -> dict:
        raise NotImplementedError(
            "FR24 requires a paid subscription; client not wired up yet."
        )
