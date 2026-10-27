import io
import json
from unittest.mock import Mock

from multicloud_ai.core import terraform_progress as module


def event(kind, address='azurerm_managed_disk.disk'):
    return {'type': kind, 'hook': {'resource': {'addr': address}, 'id_value': 'private-value'}}


def test_resource_progress_tracks_reads_without_exposing_provider_values():
    updates = []
    tracker = module.ResourceProgress({'azurerm_managed_disk.disk': 'OS disk'}, updates.append)
    tracker.consume(event('refresh_start'))
    assert updates[-1]['active'][0]['name'] == 'OS disk'
    assert updates[-1]['completed'] == 0
    tracker.consume(event('refresh_complete'))
    tracker.consume(event('refresh_complete'))
    assert updates[-1]['completed'] == 1
    assert updates[-1]['active'] == []
    tracker.consume(event('refresh_start', 'unknown.resource'))
    assert updates[-1]['total'] == 1
    assert 'private-value' not in json.dumps(updates)


def test_plan_streams_events_and_preserves_diagnostics(monkeypatch):
    process = Mock()
    process.stdout = io.StringIO('\n'.join(json.dumps(item) for item in [
        event('refresh_start'), event('refresh_complete'),
        {'type': 'diagnostic', 'diagnostic': {'summary': 'Provider error', 'detail': 'Read failed'}}]) + '\n')
    process.wait.return_value = 1
    process.poll.return_value = 1
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *args, **kwargs: process)
    updates = []
    tracker = module.ResourceProgress({'azurerm_managed_disk.disk': 'OS disk'}, updates.append)
    result = module.run_terraform(['terraform', 'plan', '-json'], progress_tracker=tracker,
                                  capture_output=True, text=True)
    assert result.returncode == 1
    assert result.stderr == 'Provider error\nRead failed'
    assert updates[-1]['completed'] == 1
    assert process.stdout.closed
