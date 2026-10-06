"""Per-client observations committed only after an HTTP response is sent.

The boundary is server transport handoff, not proof of human/model receipt.
Unsupported transports have no inferred baseline and still return full state.
"""
from __future__ import annotations

from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass
import json
import threading


@dataclass
class Delivery:
    session: str | None
    candidate: dict | None = None
    request_id: object = None


current_delivery: ContextVar[Delivery | None] = ContextVar('state_delivery', default=None)


def _rect(value):
    if value is None:
        return None
    return tuple(getattr(value, part, None) for part in ('left', 'top', 'right', 'bottom'))


def observation(state, scope):
    """Detach only comparable observed facts; never retain screenshots/UIA objects."""
    tree = state.tree_state
    windows = {}
    for window in state.windows:
        key = (window.handle, window.process_id)
        windows[key] = (window.name, str(window.status), _rect(window.bounding_box))
    active = state.active_window
    nodes = []
    for category in ('interactive_nodes', 'scrollable_nodes'):
        for node in getattr(tree, category, []):
            nodes.append((node.window_name, node.control_type, _rect(node.bounding_box),
                          node.name, json.dumps(node.metadata, sort_keys=True, default=str)))
    return {
        'scope': tuple(scope), 'windows': windows,
        'active': (active.handle, active.process_id) if active else None,
        'cursor': state.cursor_position,
        'nodes': sorted(nodes, key=repr),
        'semantic': tree.semantic_tree_to_string() if tree else '',
        'browser_text': tuple(node.text for node in getattr(tree, 'dom_informative_nodes', [])),
        'complete': tree is not None and getattr(tree, 'status', False)
                    and not getattr(tree, 'truncated', True),
    }


class Baselines:
    def __init__(self, capacity=64):
        self.capacity = capacity
        self._latest = OrderedDict()
        self._lock = threading.Lock()

    def describe(self, session, current):
        if not session:
            return 'Changes: unavailable (no confirmed stateful HTTP delivery session).'
        with self._lock:
            previous = self._latest.get(session)
        if not current['complete']:
            return 'Changes: unavailable (observation incomplete; missing elements are not deletions).'
        if previous is None:
            return 'Changes: no delivered baseline for this session.'
        if previous['scope'] != current['scope']:
            return 'Changes: not compared because observation scope or browser target changed.'
        changes = []
        before, after = previous['windows'], current['windows']
        for key in sorted(after.keys() - before.keys()):
            changes.append(f'Window observed: {after[key][0]!r}.')
        for key in sorted(before.keys() - after.keys()):
            changes.append(f'Window no longer observed: {before[key][0]!r}.')
        for key in sorted(before.keys() & after.keys()):
            if before[key] != after[key]:
                fields = [label for i, label in enumerate(('title', 'state', 'bounds'))
                          if before[key][i] != after[key][i]]
                changes.append(f'Window {after[key][0]!r}: {", ".join(fields)} changed.')
        if previous['active'] != current['active']:
            title = after.get(current['active'], ('none',))[0]
            changes.append(f'Focused window changed to {title!r}.')
        if previous['cursor'] != current['cursor']:
            changes.append(f'Cursor moved to {current["cursor"]}.')
        if previous['nodes'] != current['nodes']:
            old = set(previous['nodes']); new = set(current['nodes'])
            affected = sorted({node[0] for node in old ^ new})
            changes.append('Observed UI text, values, state or geometry changed in: '
                           + ', '.join(repr(name) for name in affected)
                           + f' ({len(new-old)} new observations, {len(old-new)} no longer observed; '
                           'element identity/deletion is not inferred).')
        elif previous['semantic'] != current['semantic']:
            changes.append('UI hierarchy or container text changed within the observed scope.')
        if previous['browser_text'] != current['browser_text']:
            changes.append('Browser text changed within the observed browser target.')
        return 'Changes since last delivered observation:\n' + ('\n'.join(changes) or 'No observed changes.')

    def commit(self, session, current):
        if not session or not current['complete']:
            return
        with self._lock:
            self._latest[session] = current
            self._latest.move_to_end(session)
            while len(self._latest) > self.capacity:
                self._latest.popitem(last=False)


baselines = Baselines()


def describe_and_stage(state, scope):
    # SDK session dispatch may run in a task created during initialization,
    # outside this POST's ContextVar context. Follow its public HTTP request.
    try:
        from fastmcp.server.dependencies import get_http_request
        request = get_http_request()
    except (ImportError, RuntimeError):
        frame = current_delivery.get()
    else:
        frame = request.scope.get('windows_mcp.delivery')
    current = observation(state, scope)
    summary = baselines.describe(frame.session if frame else None, current)
    if frame is not None and current['complete']:
        frame.candidate = current
    return summary


class StateDeliveryMiddleware:
    """Commit a staged observation after the final successful ASGI body send.

    An error result, cancelled/failed send, disconnected stream, or absent
    session header cannot advance a baseline. No result bodies are retained.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') != 'POST':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        try:
            session = headers.get(b'mcp-session-id', b'').decode('ascii') or None
        except UnicodeError:
            session = None
        frame = Delivery(session)
        scope = dict(scope, **{'windows_mcp.delivery': frame})
        token = current_delivery.set(frame)
        status = None
        response = bytearray()
        request = bytearray()
        request_overflow = False

        async def incoming():
            nonlocal request_overflow
            message = await receive()
            if message['type'] == 'http.request' and not request_overflow:
                request.extend(message.get('body', b''))
                if len(request) > 1048576:
                    request_overflow = True
                    request.clear()
                    frame.session = None
                elif not message.get('more_body', False):
                    try:
                        body = json.loads(request)
                        if body.get('method') == 'tools/call':
                            frame.request_id = body.get('id')
                    except (ValueError, AttributeError):
                        frame.session = None
                    request.clear()
            return message

        async def outgoing(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            if message['type'] == 'http.response.body' and frame.candidate is not None:
                response.extend(message.get('body', b''))
            await send(message)
            if (message['type'] == 'http.response.body'
                    and not message.get('more_body', False)
                    and status == 200 and frame.candidate is not None
                    and frame.session and frame.request_id is not None):
                # The result must be an actual successful JSON-RPC response,
                # including SSE framing; tool errors never update the baseline.
                try:
                    bodies = [json.loads(response)]
                except (ValueError, UnicodeError):
                    bodies = []
                    for line in bytes(response).splitlines():
                        if line.startswith(b'data:'):
                            try:
                                bodies.append(json.loads(line[5:].strip()))
                            except (ValueError, UnicodeError):
                                pass
                for body in bodies:
                    result = body.get('result') if isinstance(body, dict) else None
                    if (isinstance(result, dict) and isinstance(result.get('content'), list)
                            and body.get('id') == frame.request_id
                            and not result.get('isError', False)):
                        baselines.commit(frame.session, frame.candidate)
                        break
        try:
            await self.app(scope, incoming, outgoing)
        finally:
            current_delivery.reset(token)
