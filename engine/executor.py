import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from engine.errors import JobError, EngineRuntimeError


class WorkerPool:
    def __init__(self, max_workers=4):
        self.max_workers = max_workers
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._active = 0
        self._completed = 0
        self._failed = 0

    def submit_sync(self, fn, *args, **kwargs):
        future = self._executor.submit(fn, *args, **kwargs)
        return future

    async def submit_async(self, fn, *args, **kwargs):
        loop = asyncio.get_event_loop()
        self._active += 1
        try:
            result = await loop.run_in_executor(None, fn, *args, **kwargs)
            self._completed += 1
            return result
        except Exception as e:
            self._failed += 1
            raise
        finally:
            self._active -= 1

    def stats(self):
        return {
            "max_workers": self.max_workers,
            "active": self._active,
            "completed": self._completed,
            "failed": self._failed,
        }

    def shutdown(self, wait=True):
        self._executor.shutdown(wait=wait)


class Executor:
    def __init__(self, pool=None):
        self.pool = pool or WorkerPool()
        self._queue = []

    def submit(self, job, model_client, on_complete=None, on_error=None):
        self._queue.append({
            "job": job,
            "model_client": model_client,
            "on_complete": on_complete,
            "on_error": on_error,
        })

    def execute_queued(self, pipeline):
        results = []
        while self._queue:
            item = self._queue.pop(0)
            job = item["job"]
            model_client = item["model_client"]

            try:
                result = pipeline.execute(job, model_client)
                results.append(result)
                if item["on_complete"]:
                    try:
                        item["on_complete"](result)
                    except Exception:
                        pass
            except Exception as e:
                if item["on_error"]:
                    try:
                        item["on_error"](e)
                    except Exception:
                        pass
                results.append(None)

        return results

    async def execute_async(self, job, model_client, pipeline):
        try:
            result = await self.pool.submit_async(pipeline.execute, job, model_client)
            return result
        except Exception as e:
            raise JobError(f"async execution failed: {e}", job_id=job.id)

    def execute_parallel(self, jobs, model_client, pipeline):
        futures = []
        for job in jobs:
            future = self.pool.submit_sync(pipeline.execute, job, model_client)
            futures.append(future)

        results = []
        for future in futures:
            try:
                results.append(future.result())
            except Exception as e:
                results.append(None)

        return results

    def stats(self):
        return {
            "queue_size": len(self._queue),
            "pool": self.pool.stats(),
        }
