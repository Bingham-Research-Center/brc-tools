"""Utility functions."""

import datetime

def get_current_datetime(tz="UTC",fmt='datetime',dt_res="seconds",
                            str_fmt="%Y%m%d_%H%M%S"):
    """Get the current date and time.

    Args:
        tz (str): Timezone to use. Defaults to "UTC".
        fmt (str): Format of the output. (datetime v string?)
        dt_res (str): Resolution of the datetime. Defaults to "seconds".
        str_fmt (str): String format for the datetime. Defaults to "%Y%m%d_%H%M%S".
    """
    # We'll need the datetime regardless!
    current_utc = datetime.datetime.now(
                datetime.timezone.utc).replace(microsecond=0)

    # TODO - if tz != "UTC"...
    return current_utc
