"""Public-output boundary and graph consistency checks, without private data."""
import importlib.util
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("public_neural_build",root/"build.py")
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
data=json.loads((root/"architecture.json").read_text(encoding="utf-8"))
assert data==builder.graph(),"Graph drifted from public source table"
ids={n["id"] for n in data["nodes"]}
assert len(ids)==len(data["nodes"]),"Duplicate module IDs"
assert all(e["source"] in ids and e["target"] in ids for e in data["edges"]),"Dangling edge"
edges={(e["source"],e["target"]) for e in data["edges"]}
assert all(pair in edges for pair in zip(data["route"],data["route"][1:])),"Illustrative route invents an edge"
svg=ET.parse(root/"neural-map.svg")
for element in svg.iter():
    assert element.tag.split('}')[-1] not in {"script","foreignObject","use","image"},"Unsafe GitHub SVG element"
    for name,value in element.attrib.items():
        if name.endswith("href"): assert value.startswith('#'),"External SVG dependency"
for filename in ["index.html","neural-map.html","architecture.json","neural-map.svg"]:
    text=(root/filename).read_text(encoding="utf-8")
    assert not re.search(r'(?:src|href)=["\'](?:brain\.json|pages/)',text),"Legacy export dependency"
    assert not re.search(r'[A-Z]:[/\\]Users[/\\]',text),"Local absolute path in public output"
    assert not re.search(r'https?://(?:localhost|127\.0\.0\.1|192\.168\.)',text),"Local backend in public output"
assert "{{" not in (root/"index.html").read_text(encoding="utf-8"),"Unexpanded template"
print("Public graph/source/route consistency, SVG safety and output boundary checks passed")
