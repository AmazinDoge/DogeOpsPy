# demo_pool_run.py
import asyncio
from DogeOpsPy.asyn.pool import LeasePoolV1  # 按你的包路径导入

class Company:
    def __init__(self):
        self.worker_status = {}
        self.status_change_lock = asyncio.Lock()

    async def Worker(self, worker_id, lease_pool):
        while True:
            self.worker_status[worker_id] = "Wait Queue"
            async with lease_pool.lease() as lease:
                self.worker_status[worker_id] = f"Has {lease}"
                await asyncio.sleep(2)
                self.worker_status[worker_id] = f"Returning {lease}"
            self.worker_status[worker_id] = f"Sleeping"
            await asyncio.sleep(3)

async def printer(company, lease_pool):
    while True:
        print("=" * 60)
        for key, value in (await lease_pool.pool_status()).items():
            print(f"{key}: {value}")
        for key, value in company.worker_status.items():
            print(f"{key}: {value}")
        await asyncio.sleep(1)

async def main():
    lease_pool = LeasePoolV1(
        resource_list=list(range(10)),
        pool_size=0,  # Unlimited Pool Size
        lease_max=3,  # Maximum lease to 3 clients concurrently
        timeout_sec=None,  # Default Timeout, you can set None and later in method set timeout
    )

    company = Company()
    for i in range(7): # Creates 7 Workers but coro limit is 3.
        asyncio.create_task(company.Worker(f"Worker{i}", lease_pool))
    asyncio.create_task(printer(company, lease_pool))

    await asyncio.sleep(2)
    await lease_pool.put("666")  # Insert during pools in work
    await asyncio.sleep(50)

asyncio.run(main())