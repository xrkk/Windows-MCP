"""ASGI handoff and deterministic, session-isolated observation comparisons."""
import asyncio
import json
import types
import unittest
import test_input_receipts as helpers

state_delivery = helpers.load('tested_state_delivery', 'src/windows_mcp/tools/state_delivery.py')


def state(text='one', *, truncated=False):
    tree = types.SimpleNamespace(
        status=True, truncated=truncated, interactive_nodes=[], scrollable_nodes=[],
        dom_informative_nodes=[types.SimpleNamespace(text=text)],
        semantic_tree_to_string=lambda: text)
    return types.SimpleNamespace(tree_state=tree, windows=[], active_window=None,
                                 cursor_position=(0, 0))


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        state_delivery.baselines = state_delivery.Baselines(capacity=2)

    async def deliver(self, text='one', *, session='A', fail=False, error=False,
                      truncated=False, scope=('all',), sse=False, wrong_id=False):
        summary=[]
        async def app(asgi_scope, receive, send):
            await receive()
            summary.append(state_delivery.describe_and_stage(state(text, truncated=truncated),scope))
            await send({'type':'http.response.start','status':200})
            result={'jsonrpc':'2.0','id':99 if wrong_id else 1,
                    'result':{'content':[{'type':'text','text':text}], 'isError':error}}
            body=json.dumps(result).encode()
            if sse:
                body=b'event: message\ndata: '+body+b'\n\n'
            cut=len(body)//2
            await send({'type':'http.response.body','body':body[:cut],'more_body':True})
            await send({'type':'http.response.body','body':body[cut:],'more_body':False})
        async def receive():
            return {'type':'http.request','body':b'{"jsonrpc":"2.0","id":1,"method":"tools/call"}'}
        async def send(message):
            if fail and message['type']=='http.response.body':
                raise ConnectionError('disconnected')
        headers=[] if session is None else [(b'mcp-session-id',session.encode())]
        middleware=state_delivery.StateDeliveryMiddleware(app)
        await middleware({'type':'http','method':'POST','headers':headers},receive,send)
        return summary[0]

    async def test_handoff_then_compare_without_cross_session_leak(self):
        self.assertIn('no delivered baseline',await self.deliver())
        self.assertIn('No observed changes',await self.deliver())
        self.assertIn('no delivered baseline',await self.deliver(session='B'))
        self.assertIn('Browser text changed',await self.deliver('two'))

    async def test_failed_send_does_not_advance(self):
        await self.deliver()
        with self.assertRaises(ConnectionError):await self.deliver('lost',fail=True)
        self.assertIn('No observed changes',await self.deliver())

    async def test_error_and_incomplete_do_not_advance(self):
        await self.deliver()
        await self.deliver('error',error=True)
        self.assertIn('No observed changes',await self.deliver())
        self.assertIn('missing elements are not deletions',await self.deliver('partial',truncated=True))
        self.assertIn('No observed changes',await self.deliver())

    async def test_scope_switch_replaces_only_after_handoff(self):
        await self.deliver()
        self.assertIn('not compared',await self.deliver('two',scope=('region',)))
        self.assertIn('No observed changes',await self.deliver('two',scope=('region',)))

    async def test_sse_and_response_identity(self):
        await self.deliver(sse=True)
        await self.deliver('wrong request',wrong_id=True)
        self.assertIn('No observed changes',await self.deliver())

    async def test_no_session_and_eviction_are_explicit(self):
        self.assertIn('unavailable',await self.deliver(session=None))
        await self.deliver(session='A');await self.deliver(session='B');await self.deliver(session='C')
        self.assertIn('no delivered baseline',await self.deliver(session='A'))

    def test_polling_without_delivery_context_has_no_baseline(self):
        self.assertIn('unavailable',state_delivery.describe_and_stage(state(),('all',)))
        self.assertFalse(state_delivery.baselines._latest)


    async def test_delayed_app_cleanup_cannot_overwrite_newer_delivery(self):
        sent = asyncio.Event()
        finish = asyncio.Event()
        async def app(scope, receive, send):
            await receive()
            state_delivery.describe_and_stage(state('older'), ('all',))
            await send({'type': 'http.response.start', 'status': 200})
            await send({'type': 'http.response.body', 'body': json.dumps(
                {'id': 1, 'result': {'content': []}}).encode()})
            sent.set()
            await finish.wait()
        async def receive():
            return {'type': 'http.request', 'body': b'{"id":1,"method":"tools/call"}'}
        async def send(message):
            pass
        task = asyncio.create_task(state_delivery.StateDeliveryMiddleware(app)(
            {'type': 'http', 'method': 'POST', 'headers': [(b'mcp-session-id', b'A')]},
            receive, send))
        await sent.wait()
        await self.deliver('newer')
        finish.set()
        await task
        self.assertIn('No observed changes', await self.deliver('newer'))

    def test_sdk_request_scope_wins_over_stale_dispatch_context(self):
        from unittest.mock import patch
        frame = state_delivery.Delivery('actual')
        dependencies = types.ModuleType('fastmcp.server.dependencies')
        dependencies.get_http_request = lambda: types.SimpleNamespace(
            scope={'windows_mcp.delivery': frame})
        token = state_delivery.current_delivery.set(state_delivery.Delivery('stale'))
        try:
            with patch.dict('sys.modules', {'fastmcp.server.dependencies': dependencies}):
                state_delivery.describe_and_stage(state(), ('all',))
            self.assertIsNotNone(frame.candidate)
            self.assertIsNone(state_delivery.current_delivery.get().candidate)
        finally:
            state_delivery.current_delivery.reset(token)
