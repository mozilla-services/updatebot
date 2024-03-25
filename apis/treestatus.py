import requests

_is_try_open = None


def is_try_open() -> bool:
    global _is_try_open
    if _is_try_open:
        return _is_try_open
    try:
        response = requests.get(
            "https://treestatus.mozilla-releng.net/trees/try"
        ).json()
        _is_try_open = response["result"]["status"] == "open"
    except Exception:
        _is_try_open = False
    return _is_try_open
