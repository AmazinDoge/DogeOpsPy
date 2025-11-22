import asyncio
from contextlib import asynccontextmanager

from DogeOpsPy.asyn.semaphore import InfiniteSemaphore
from DogeOpsPy.verification.type import is_hashable

# =============================================================================
# ResPoolV1 — Simple Async Resource Pool (user guide)
# =============================================================================
# It's async pool, coro safe, you put and get objects with it
#
# -----------------------------------------------------------------------------
# Init Options:
#   resource_list.   # Fill pool with list()
#   timeout_sec.     # Overall timeout, you can leave this and use method timeout
#   pool_size.       # Max pool size, if full, then put() hang and awaits
#
# -----------------------------------------------------------------------------
# Methods:
# instance.get(timeout=None).            # Get 1 object from pool
# instance.put(resource, timeout=None).  # Put 1 object to pool
# instance.trash(resource).              # Blacklist an object, no more I\O
# instance.pool_count().                 # Pool current size
# await instance.pool_status().          # Debug snapshot: {"Pool":[...], "Trash":[...]}.
#
# -----------------------------------------------------------------------------
# QuickStart:
# res_pool = ResPoolV1(resource_list=[1, 2, 3]):
# result = await res_pool.get()
# await res_pool.put(result)
# await res_pool.trash(4)
#
# -----------------------------------------------------------------------------
# WARNINGS:
# 1. pool_count() is not async and not that accurate when you see it

class ResPoolV1:
    def __init__(self,
                 resource_list: list = None,
                 timeout_sec: int = None,
                 pool_size: int = 0):
        # INPUT
        self.timeout_sec = timeout_sec

        # DataStructures
        self._q = asyncio.Queue(maxsize=pool_size)
        self._trash_bin = set()
        self._trash_bin_lock = asyncio.Lock()

        # First put in
        if isinstance(resource_list, list):
            for r in resource_list:
                self.hashable_check(r)
                self._q.put_nowait(r)

    async def get(self, timeout=None):
        if timeout is None:
            timeout = self.timeout_sec
        while True:
            r = await asyncio.wait_for(self._q.get(), timeout)
            async with self._trash_bin_lock:
                if r not in self._trash_bin:
                    break
        return r

    async def put(self, resource, timeout=None):
        if timeout is None:
            timeout = self.timeout_sec
        if resource is None:
            return False
        async with self._trash_bin_lock:
            if resource in self._trash_bin:
                return False
        self.hashable_check(resource)
        await asyncio.wait_for(self._q.put(resource), timeout)
        return True

    async def trash(self, resource):
        if resource is None:
            return False
        async with self._trash_bin_lock:
            if resource in self._trash_bin:
                return False
            self.hashable_check(resource)
            self._trash_bin.add(resource)
        return True

    def pool_count(self):
        return self._q.qsize()

    async def pool_status(self):
        async with self._trash_bin_lock:
            return {
                "Pool": list(self._q._queue),
                "Trash": list(self._trash_bin),
            }

    @staticmethod
    def hashable_check(resource):
        if not is_hashable(resource):
            raise TypeError(f"Resource must be a hashable type, found [{type(resource)}] {resource}")

# =============================================================================
# LeasePoolV1 — Async Resource Pool with Concurrency Limit
# =============================================================================
# It's an rental pool, you rent one, that is easy
#
# -----------------------------------------------------------------------------
# Init Options:
#   lease_max.          # Max concurrent leases; 0 = unlimited (no cap).
#   lease_ret_timeout.  # Timeout (sec) when auto-returning on context exit.
#   resource_list.      # Fill pool with list() (hashable items).
#   timeout_sec.        # Overall timeout, should leave with None and in methods override instead.
#   pool_size.          # DANGEROUS, should not limit, use lease_max instead.
#
# -----------------------------------------------------------------------------
# Core Method:
# async with instance.lease(timeout=None) as resource:
#   # Acquire a lease slot (respecting lease_max) AND get a resource.
#   # Use the resource inside this block; it auto-returns on exit.
#
# -----------------------------------------------------------------------------
# Helpful Methods:
# instance.lease_count().                # How many resources are currently leased (approx).
# await instance.pool_status().          # Debug snapshot includes:
#                                        #   {"Pool":[...], "Trash":[...],
#                                        #    "InLease":[...], "InReturn":[...], "Orphans":[...]}
#
# -----------------------------------------------------------------------------
# QuickStart:
# pool = LeasePoolV1(
#     lease_max=2,
#     resource_list=[1, 2, 3],
# )
#
# async with pool.lease() as r:
#     print(r)
#
# # Leasing with a custom timeout for both the slot and the resource:
# try:
#     async with pool.lease(timeout=3) as r:
#         # ... work ...
# except asyncio.TimeoutError:
#     # No slot or no resource in time, or return stuck because pool was full.
#     ...
#
# # Check status / diagnostics:
# status = await pool.pool_status()
# status["Orphans"]  # resources that failed to auto-return (timeout/cancel)
#
# -----------------------------------------------------------------------------
# NOTES:
# 1) If you limit pool_size and add objects to pool interactively, pool full, lease return will FAIL
# 2) If the task is cancelled during auto-return, you may see that resource in Orphans.
# 3) Use pool_status() for debugging only; values are snapshots and not perfectly "live".


class LeasePoolV1(ResPoolV1):
    def __init__(self, lease_max: int=0, lease_ret_timeout=1, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # INPUT
        self.lease_max = lease_max
        self.lease_ret_timeout = lease_ret_timeout

        # DATA STRUCTURES
        self._lease_sem = asyncio.BoundedSemaphore(self.lease_max) if self.lease_max else InfiniteSemaphore()
        self._lease_change_lock = asyncio.Lock()
        self._in_lease = set()  # under leasing
        self._ret_lease = set()  # on returning
        self._orphans = set()  # failed returning: DUE to cancel or pool_full timeout

    @asynccontextmanager
    async def lease(self, timeout=None):
        if timeout is None:
            timeout = self.timeout_sec

        lease_target = None
        sem_acquired = False

        try:
            try:
                await asyncio.wait_for(self._lease_sem.acquire(), timeout)
                sem_acquired = True
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError(f"LeasePoolV1::No lease quota in {timeout}s.")
            try:
                lease_target = await self.get(timeout)
                async with self._lease_change_lock:
                    self._in_lease.add(lease_target)
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError(f"LeasePoolV1::No resource in pool for {timeout}s.")
            yield lease_target
        finally:
            if sem_acquired:  # Once user exits async with, concurrent limit immediately release
                self._lease_sem.release()
            is_orphan = True
            try:
                await self._start_return(lease_target, self.lease_ret_timeout)
                is_orphan = False  # If return pool finish, it shouldn't be in orphanage
            except asyncio.TimeoutError:
                error_str = f"LeasePoolV1::Pool FULL, can't return resource!! Check self._orphans"
                raise asyncio.TimeoutError(error_str)
            except asyncio.CancelledError:
                error_str = f"LeasePoolV1::Pool CANCELLED, can't return resource!! Check self._orphans"
                raise asyncio.CancelledError(error_str)
            finally:
                # After all, finish returns, only difference is orphan or not
                await asyncio.shield(self._finish_return(lease_target, is_orphan=is_orphan))

    async def _start_return(self, resource, timeout=None):
        if resource is not None:
            async with self._lease_change_lock:
                self._in_lease.discard(resource)
                self._ret_lease.add(resource)
            await asyncio.shield(self.put(resource, timeout))

    async def _finish_return(self, resource, is_orphan=False):
        if resource is not None:
            async with self._lease_change_lock:
                self._ret_lease.discard(resource)
                if is_orphan:
                    self._orphans.add(resource)

    def lease_count(self):
        return len(self._in_lease)

    async def pool_status(self):
        parent_status = await super(LeasePoolV1, self).pool_status()
        async with self._lease_change_lock:
            parent_status.update(
                {
                    "InLease": list(self._in_lease),
                    "InReturn": list(self._ret_lease),
                    "Orphans": list(self._orphans),
                }
            )
        return parent_status
