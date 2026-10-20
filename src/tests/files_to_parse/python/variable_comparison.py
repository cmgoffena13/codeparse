from pkg.flags import BACKFILL


def run():
    if BACKFILL == "true":
        return 1
    if BACKFILL != "true":
        return 0
    return BACKFILL is not None
