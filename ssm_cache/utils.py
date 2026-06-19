from datetime import datetime, timezone


def utcnow():
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def batch(iterable, num):
    """Turn iterable into batches of size num."""
    length = len(iterable)

    for ndx in range(0, length, num):
        yield iterable[ndx : min(ndx + num, length)]
