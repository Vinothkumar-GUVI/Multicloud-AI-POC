"""Distinguish confirmed AWS access failures from unsupported mappings."""
import re
from .agents import redact


def annotate_permission_issues(text, resources):
    notes = []
    for resource in resources:
        if str(resource.cloud).upper() != 'AWS':
            continue
        configuration = resource.configuration or {}
        issue = configuration.get('permission_issue') or {}
        warning = str(configuration.get('discovery_warning', ''))
        if not issue and not re.search(r'AccessDenied|UnauthorizedOperation|not authorized|Forbidden', warning, re.I):
            continue
        operation = str(issue.get('operation') or 'service configuration read')
        code = str(issue.get('code') or 'AccessDenied')
        notes.append('\n'.join([
            '# PERMISSION ISSUE: ' + resource.name,
            '# Source ID: ' + resource.resource_id,
            '# Permission issue: AWS denied ' + operation + ' (' + code + ').',
            '# CONFIGURATION INPUTS REQUIRED: fill declared inputs for unavailable settings; if no resource block exists, mapping is also incomplete.',
            '# Source settings could not be verified. A permission note does not establish resource coverage.',
        ]))
    if not notes:
        return text
    return ('# SOURCE PLAN PENDING: AWS permission-limited configuration remains unverified.\n'
            + str(redact('\n\n'.join(notes))) + '\n\n' + text)
