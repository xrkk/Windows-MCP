"""Fail-stop batch execution with input-free progress receipts."""
import json


def run_batch(items, *, checkpoint, action, setup=None, cleanup=None):
    """Indices are zero-based; an action that raises may already have side effects."""
    completed = []
    uncertain = []
    failed = []
    phase = 'setup'
    error = None
    cleanup_error = None
    index = None
    try:
        checkpoint()
        if setup:
            setup()
        for index, item in enumerate(items):
            phase = 'checkpoint'
            checkpoint()
            phase = 'action'
            action(item)
            completed.append(index)
        phase = 'complete'
    except Exception as exc:
        error = exc
        if index is not None:
            if phase == 'action':
                uncertain.append(index)
            else:
                failed.append(index)
    finally:
        if cleanup:
            try:
                cleanup()
            except Exception as exc:
                cleanup_error = exc
    if error is None and cleanup_error is None:
        return
    progress = {
        'completed': completed,
        'failed_before_action': failed,
        'uncertain': uncertain,
        'unexecuted': [i for i in range(len(items)) if i not in completed and i not in uncertain],
        'phase': phase if error else 'cleanup',
        'cleanup_error': type(cleanup_error).__name__ if cleanup_error else None,
        'application_acceptance_verified': False,
        'retry': 'Inspect uncertain results before any retry; do not replay the whole batch.',
    }
    exc = error if error is not None else cleanup_error
    # Preserve ownership exception types/codes while sanitizing possible text
    # payloads in lower-level exception messages.
    exc.batch_progress = progress
    if isinstance(getattr(exc, 'status', None), dict):
        exc.status = dict(exc.status, batch_progress=progress)
    exc.args = ('Batch interrupted: ' + json.dumps(progress, ensure_ascii=False),)
    raise exc from None
