"""Stream Terraform's documented JSON resource hooks without displaying values."""
import json
import subprocess
from time import monotonic


class ResourceProgress:
    def __init__(self, names, callback):
        self.names = names
        self.callback = callback
        self.active = {}
        self.completed = set()

    def consume(self, event):
        hook = event.get('hook') or {}
        address = (hook.get('resource') or {}).get('addr')
        if address not in self.names:
            return
        kind = event.get('type')
        if kind in {'refresh_start', 'import_start'}:
            self.active.setdefault(address, monotonic())
        elif kind in {'refresh_complete', 'import_complete'}:
            self.active.pop(address, None)
            self.completed.add(address)
        else:
            return
        if self.callback:
            self.callback({'stage': 'Reading Azure resources', 'completed': len(self.completed),
                'total': len(self.names), 'active': [{'name': self.names[a], 'started': start}
                for a, start in self.active.items()]})


def run_terraform(args, progress_tracker=None, **kwargs):
    if args[1] != 'plan':
        return subprocess.run(args, **kwargs)
    kwargs.pop('capture_output', None)
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               bufsize=1, **kwargs)
    lines = []
    diagnostics = []
    try:
        for line in process.stdout:
            lines.append(line)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if progress_tracker:
                progress_tracker.consume(event)
            if event.get('type') == 'diagnostic':
                diagnostic = event.get('diagnostic') or {}
                diagnostics.append(str(diagnostic.get('summary', '')) + '\n' + str(diagnostic.get('detail', '')))
        return subprocess.CompletedProcess(args, process.wait(), ''.join(lines), '\n'.join(diagnostics))
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.terminate()
            process.wait()
