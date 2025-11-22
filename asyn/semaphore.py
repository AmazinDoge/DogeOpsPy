class InfiniteSemaphore:
    """A semaphore that never blocks — supports 'async with' syntax."""

    async def __aenter__(self):
        # nothing to wait for
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # nothing to release
        return False  # don't suppress exceptions

    async def acquire(self):
        # immediately return, never blocks
        return True

    def release(self):
        # no-op
        pass
