import asyncio

_llm_semaphore: asyncio.Semaphore | None = None
_yomitoku_semaphore: asyncio.Semaphore | None = None


def get_llm_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(2)
    return _llm_semaphore


def get_yomitoku_semaphore() -> asyncio.Semaphore:
    global _yomitoku_semaphore
    if _yomitoku_semaphore is None:
        _yomitoku_semaphore = asyncio.Semaphore(2)
    return _yomitoku_semaphore
