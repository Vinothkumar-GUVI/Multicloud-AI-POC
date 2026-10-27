import re
from typing import List
from .models import NormalizedResource, Dependency

ID_KEYS = re.compile(r"(id|ids|selflink|self_link|resource|resourceid|resource_id|subnet|network|disk|nic|interface|address|securitygroup|target|backend|attachment)", re.I)

AWS_SHORT_ID = re.compile(r"(?:vpc|subnet|sg|sgr|eni|vol|i|igw|nat|rtb|eipalloc|vpce|acl)-[0-9a-f]+", re.I)


def _aws_scope(arn):
    parts = str(arn).split(":", 5)
    return tuple(parts[1:5]) if len(parts) == 6 and parts[0] == "arn" else None


def _collect(v, out, path):
    if isinstance(v, str) and ("/" in v or v.startswith("arn:") or AWS_SHORT_ID.fullmatch(v)):
        out.append((v, path))
    elif isinstance(v, list):
        for i,x in enumerate(v): _collect(x, out, f"{path}[{i}]")
    elif isinstance(v, dict):
        for k,x in v.items(): _collect(x, out, f"{path}.{k}" if path else str(k))

def _walk(v, out, path=""):
    if isinstance(v, dict):
        for k,x in v.items():
            p=f"{path}.{k}" if path else str(k)
            if ID_KEYS.search(str(k)): _collect(x, out, p)
            _walk(x, out, p)
    elif isinstance(v, list):
        for i,x in enumerate(v): _walk(x, out, f"{path}[{i}]")

def _key(value): return str(value or "").rstrip("/").lower()

def build(resources: List[NormalizedResource]) -> List[Dependency]:
    by_id={_key(r.resource_id):r for r in resources}; edges=[]
    aws_ids = {}
    for item in resources:
        if str(item.cloud).upper() != "AWS":
            continue
        scope = _aws_scope(item.resource_id)
        short = str(item.resource_id).rsplit("/", 1)[-1]
        if scope and AWS_SHORT_ID.fullmatch(short):
            aws_ids.setdefault((scope, short.lower()), []).append(item)
    for r in resources:
        refs=[]; _walk(r.configuration, refs)
        seen=set()
        for ref,path in refs:
            k=_key(ref)
            if k in seen: continue
            seen.add(k)
            target=by_id.get(k)
            if target is None and str(r.cloud).upper() == "AWS" and AWS_SHORT_ID.fullmatch(ref):
                scope = _aws_scope(r.resource_id)
                # Short network IDs belong to EC2, even when referenced by RDS/Lambda.
                if scope:
                    ec2_scope = (scope[0], "ec2", scope[2], scope[3])
                    candidates = aws_ids.get((ec2_scope, k), [])
                    if len(candidates) == 1:
                        target = candidates[0]
            if target and _key(target.resource_id) != _key(r.resource_id):
                source_text=str(r.configuration_source or "live configuration")
                evidence=f"Explicit resource ID reference at configuration path '{path}' ({source_text})"
                confidence="High"
                edges.append(Dependency(r.resource_id,target.resource_id,"references",evidence,confidence))
    unique={}
    for e in edges: unique[(_key(e.source_id),_key(e.target_id),e.relationship)]=e
    return list(unique.values())
