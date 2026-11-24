"""Replace credential literals with inputs without masking resource metadata."""
import re


def sanitize_terraform(text, secret_values=()):
    import hcl2
    try:
        tree = hcl2.parses(text)
        tree = tree.to_lark() if hasattr(tree, 'to_lark') else tree
    except Exception:
        return None
    existing = set(re.findall(r'variable\s+"([^"]+)"', text))
    edits, declarations = [], []
    sensitive = re.compile(r'(?:^|_)(?:password(?:_wo)?|secret|secret_key|access_key|session_token|api_key|client_secret|private_key|connection_string|authorization)$', re.I)
    for attribute in tree.find_data('attribute'):
        name = str(attribute.children[0].children[0])
        code = text[attribute.meta.start_pos:attribute.meta.end_pos]
        expression = code.split('=', 1)[1].strip()
        known_secret = any(str(s) in expression for s in secret_values if s)
        if not sensitive.search(name) and not known_secret:
            continue
        # Keep references and absent optional settings; they contain no literal credential.
        if not known_secret and (expression == 'null' or re.fullmatch(r'(?:var|local|data)\.[\w.\[\]"-]+', expression)):
            continue
        variable = 'required_' + name + '_' + str(attribute.meta.start_pos)
        while variable in existing:
            variable += '_input'
        existing.add(variable)
        edits.append((attribute.meta.start_pos, attribute.meta.end_pos, name + ' = var.' + variable))
        declarations.append('variable "' + variable + '" {\n  type = any\n  sensitive = true\n'
                            '  description = "Supply this credential privately; its literal value was removed."\n}\n')
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    for secret in sorted({str(s) for s in secret_values if s}, key=len, reverse=True):
        text = text.replace(secret, '[REDACTED]')
    return text + ('\n' + '\n'.join(declarations) if declarations else '')
