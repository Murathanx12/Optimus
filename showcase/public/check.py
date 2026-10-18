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
byid={n['id']:n for n in data['nodes']}
for element in svg.iter():
    if element.attrib.get('class')!='edge': continue
    s,t=byid[element.attrib['data-source']],byid[element.attrib['data-target']]
    values=list(map(float,re.findall(r'-?\d+(?:\.\d+)?',element.attrib['d'])))
    sx,sy,cx,cy,tx,ty=values
    # Endpoints terminate outside the membrane, rather than entering a soma.
    for node,x,y in [(s,sx,sy),(t,tx,ty)]:
        assert abs(((x-node['x'])**2+(y-node['y'])**2)**.5-((12 if node['ring'] else 25)+9))<.02,'Unclipped edge terminal'
    for k in range(1,40):
        f=k/40;x=(1-f)**2*sx+2*(1-f)*f*cx+f*f*tx;y=(1-f)**2*sy+2*(1-f)*f*cy+f*f*ty
        for node in data['nodes']:
            if node['id'] in (s['id'],t['id']):continue
            assert ((x-node['x'])**2+(y-node['y'])**2)**.5>((12 if node['ring'] else 25)+7),'Wire crosses unrelated neuron'
for filename in ["index.html","neural-map.html","architecture.json","neural-map.svg"]:
    text=(root/filename).read_text(encoding="utf-8")
    assert not re.search(r'(?:src|href)=["\'](?:brain\.json|pages/)',text),"Legacy export dependency"
    assert not re.search(r'[A-Z]:[/\\]Users[/\\]',text),"Local absolute path in public output"
    assert not re.search(r'https?://(?:localhost|127\.0\.0\.1|192\.168\.)',text),"Local backend in public output"
assert "{{" not in (root/"index.html").read_text(encoding="utf-8"),"Unexpanded template"
print("Public graph/source/route consistency, SVG safety and output boundary checks passed")
