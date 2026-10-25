"""Backend transition tests. No AstrBot, network, model or production data."""
import asyncio
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.contextaware.coordinator import BackendCoordinator, BackendBusy, BackendUnavailable


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_unvalidated_candidate_unavailable(self):
        c = BackendCoordinator()
        calls = []
        async def activate(name): calls.append(name)
        with self.assertRaises(BackendUnavailable): await c.switch('contextaware', activate)
        self.assertEqual(calls, [])
        self.assertEqual(c.active, 'builtin')

    async def test_inflight_text_or_tool_blocks_switch(self):
        c = BackendCoordinator()
        c.set_readiness('contextaware', ready=True)
        lease = await c.acquire()
        async def activate(name): self.fail('Must not activate while a tool holds a lease')
        with self.assertRaises(BackendBusy): await c.switch('contextaware', activate)
        self.assertEqual(c.assert_owner(lease), 'builtin')
        await c.release(lease)

    async def test_queued_ingress_uses_new_generation_exactly_once(self):
        c = BackendCoordinator()
        c.set_readiness('contextaware', ready=True)
        entered = asyncio.Event()
        finish = asyncio.Event()
        modes = []
        async def activate(name):
            modes.append(name)
            entered.set()
            await finish.wait()
        switch = asyncio.create_task(c.switch('contextaware', activate))
        await entered.wait()
        pending = asyncio.create_task(c.acquire())
        await asyncio.sleep(0)
        self.assertFalse(pending.done())
        self.assertEqual(c.status()['pending_messages'], 1)
        finish.set()
        await switch
        lease = await pending
        self.assertEqual((lease.backend, lease.generation), ('contextaware', 1))
        self.assertEqual(modes, ['contextaware'])
        await c.release(lease)

    async def test_activation_failure_rolls_back_before_dispatch(self):
        c = BackendCoordinator()
        c.set_readiness('contextaware', ready=True)
        calls = []
        async def activate(name):
            calls.append(name)
            if name == 'contextaware': raise RuntimeError('fixture activation error')
        with self.assertRaises(RuntimeError): await c.switch('contextaware', activate)
        self.assertEqual(calls, ['contextaware', 'builtin'])
        lease = await c.acquire()
        self.assertEqual((lease.backend, lease.generation), ('builtin', 0))
        await c.release(lease)

    async def test_failed_rollback_stops_dispatch(self):
        c = BackendCoordinator()
        c.set_readiness('contextaware', ready=True)
        async def activate(name): raise RuntimeError('fixture error')
        with self.assertRaises(RuntimeError): await c.switch('contextaware', activate)
        with self.assertRaises(BackendUnavailable): await c.acquire()
        self.assertTrue(c.status()['failed'])

    async def test_released_lease_cannot_be_used_or_released_again(self):
        c = BackendCoordinator()
        lease = await c.acquire()
        await c.release(lease)
        with self.assertRaises(ValueError): c.assert_owner(lease)
        with self.assertRaises(ValueError): await c.release(lease)

    async def test_cancelled_waiter_does_not_leak_pending_capacity(self):
        c = BackendCoordinator(max_pending=1)
        c.set_readiness('contextaware', ready=True)
        entered, finish = asyncio.Event(), asyncio.Event()
        async def activate(name):
            entered.set()
            await finish.wait()
        switch = asyncio.create_task(c.switch('contextaware', activate))
        await entered.wait()
        pending = asyncio.create_task(c.acquire())
        await asyncio.sleep(0)
        with self.assertRaises(BackendBusy): await c.acquire()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError): await pending
        self.assertEqual(c.status()['pending_messages'], 0)
        finish.set()
        await switch

    async def test_context_manager_releases_on_request_exception(self):
        c = BackendCoordinator()
        with self.assertRaises(RuntimeError):
            async with c.lease():
                self.assertEqual(c.status()['active_requests'], 1)
                raise RuntimeError('fixture request failed')
        self.assertEqual(c.status()['active_requests'], 0)

    async def test_cancelled_transition_restores_before_waiters_resume(self):
        c = BackendCoordinator()
        c.set_readiness('contextaware', ready=True)
        entered = asyncio.Event()
        modes = []
        async def activate(name):
            modes.append(name)
            if name == 'contextaware':
                entered.set()
                await asyncio.Event().wait()
        switch = asyncio.create_task(c.switch('contextaware', activate))
        await entered.wait()
        pending = asyncio.create_task(c.acquire())
        await asyncio.sleep(0)
        switch.cancel()
        with self.assertRaises(asyncio.CancelledError): await switch
        owner = await pending
        self.assertEqual((owner.backend, owner.generation), ('builtin', 0))
        self.assertEqual(modes, ['contextaware', 'builtin'])
        await c.release(owner)


if __name__ == '__main__':
    unittest.main()
