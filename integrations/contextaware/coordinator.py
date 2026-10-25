"""Exclusive context backend lifecycle, independent of AstrBot's global hooks.

This controller is tested in isolation, not connected to production hooks yet.
Adapters must activate/deactivate ALL their hooks/tools through the supplied
callback. Readiness is explicit; no silent substitution of an unavailable mode.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass


class BackendBusy(RuntimeError):
    pass


class BackendUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class BackendLease:
    backend: str
    generation: int
    token: int


class BackendCoordinator:
    def __init__(self, active='builtin', *, max_pending=128):
        if active != 'builtin':
            raise ValueError('Start from a verified builtin baseline')
        self.active = active
        self.generation = 0
        self.max_pending = max_pending
        self.readiness = {'builtin': '', 'contextaware': 'Candidate integration has not passed all deployment gates'}
        self._condition = asyncio.Condition()
        self._switching = False
        self._failed = False
        self._serial = 0
        self._active = {}
        self._pending = 0

    def status(self):
        return {'backend': self.active, 'generation': self.generation,
                'active_requests': len(self._active), 'pending_messages': self._pending,
                'switching': self._switching, 'failed': self._failed,
                'choices': [{'value': name, 'available': not bool(reason), 'reason': reason}
                            for name, reason in self.readiness.items()]}

    def set_readiness(self, backend, *, ready, reason=''):
        if backend not in self.readiness:
            raise ValueError('Unknown backend')
        if backend == self.active and not ready:
            raise BackendBusy('Cannot invalidate the active backend in place')
        self.readiness[backend] = '' if ready else reason or 'Backend unavailable'

    async def acquire(self):
        async with self._condition:
            if self._failed:
                raise BackendUnavailable('Backend transition failed; operator recovery required')
            if self._pending >= self.max_pending:
                raise BackendBusy('Pending message capacity reached')
            self._pending += 1
            try:
                await self._condition.wait_for(lambda: not self._switching or self._failed)
                if self._failed:
                    raise BackendUnavailable('Backend transition failed; request was not dispatched')
                self._serial += 1
                lease = BackendLease(self.active, self.generation, self._serial)
                self._active[lease.token] = lease
                return lease
            finally:
                self._pending -= 1

    async def release(self, lease):
        async with self._condition:
            if self._active.get(lease.token) != lease:
                raise ValueError('Invalid or already released backend lease')
            self._active.pop(lease.token)

    @asynccontextmanager
    async def lease(self):
        owner = await self.acquire()
        try:
            yield owner
        finally:
            await self.release(owner)

    def assert_owner(self, lease):
        if self._active.get(lease.token) != lease:
            raise ValueError('Request no longer owns this backend generation')
        return lease.backend

    async def switch(self, target, activate):
        """Switch only when idle. activate(mode) must replace hooks atomically.

        Ingress during transition waits without losing its message. If target
        activation fails, explicitly restore the old backend. Failed restoration
        stops dispatch, rather than secretly running two or the wrong backend.
        """
        async with self._condition:
            if target not in self.readiness:
                raise ValueError('Unknown backend')
            if self._failed:
                raise BackendUnavailable('Previous transition requires recovery')
            if self.readiness[target]:
                raise BackendUnavailable(self.readiness[target])
            if self._switching or self._active:
                raise BackendBusy('Wait for in-flight requests and tools to finish')
            if target == self.active:
                return self.status()
            self._switching = True
            previous = self.active
        try:
            await activate(target)
        except BaseException:
            try:
                # Cleanup is shielded against caller cancellation; a failed
                # restoration leaves the coordinator closed, never dual-active.
                task = asyncio.create_task(activate(previous))
                await asyncio.shield(task)
            except BaseException:
                self._failed = True
            raise
        else:
            self.active = target
            self.generation += 1
        finally:
            async with self._condition:
                self._switching = False
                self._condition.notify_all()
        return self.status()
