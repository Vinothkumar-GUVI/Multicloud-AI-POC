"""Lossless Terraform configuration splitting and downloadable project archives."""
from io import BytesIO
import re
from zipfile import ZipFile, ZIP_DEFLATED
import hcl2


def compact_blank_lines(text):
    """Collapse blank separators without changing attribute values or heredocs."""
    tree = hcl2.parses(text)
    tree = tree.to_lark() if hasattr(tree, 'to_lark') else tree
    spans = sorted((node.meta.start_pos, node.meta.end_pos) for node in tree.find_data('attribute'))
    chunks, offset = [], 0
    def clean(fragment):
        return re.sub(r'(?m)(?:^[ \t]*\r?\n){2,}', '\n', fragment)
    for start, end in spans:
        if start < offset:
            continue
        chunks.extend([clean(text[offset:start]), text[start:end]])
        offset = end
    chunks.append(clean(text[offset:]))
    return ''.join(chunks).strip() + '\n'


def split_terraform(text):
    tree = hcl2.parses(text)
    tree = tree.to_lark() if hasattr(tree, 'to_lark') else tree
    variables, spans, values = [], [], []
    for block in tree.children[0].children:
        if getattr(block, 'data', None) != 'block':
            continue
        start, end = block.meta.start_pos, block.meta.end_pos
        code = text[start:end]
        match = re.match(r'variable\s+"([^"]+)"', code)
        if not match:
            continue
        variables.append(code)
        spans.append((start, end))
        # Copy defaults verbatim, including expressions, maps and heredocs.
        body = next(child for child in block.children if getattr(child, 'data', None) == 'body')
        default = next((a for a in body.children if getattr(a, 'data', None) == 'attribute'
                        and str(a.children[0].children[0]) == 'default'), None)
        if default is None:
            values.append(f'# REQUIRED: replace null with your value for {match[1]}.\n{match[1]} = null')
        else:
            assignment = text[default.meta.start_pos:default.meta.end_pos]
            values.append(re.sub(r'^default\b', match[1], assignment))
    main, offset = [], 0
    for start, end in spans:
        main.append(text[offset:start])
        offset = end
    main.append(text[offset:])
    files = {'main.tf': ''.join(main).strip() + '\n',
            'variables.tf': '\n\n'.join(variables) + '\n',
            'terraform.tfvars': '# Fill every REQUIRED value before plan/apply. Keep this file private.\n'
                                + '\n\n'.join(values) + '\n'}
    return {name: compact_blank_lines(content) for name, content in files.items()}


def bundle_zip(files):
    buffer = BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()
