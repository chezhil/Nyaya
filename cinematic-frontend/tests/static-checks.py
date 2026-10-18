"""No dependencies: document structure, local assets, fixture validity and source protection.
Run python dashboard/tests/static-checks.py [optional-original-source.zip]
"""
from pathlib import Path
from html.parser import HTMLParser
import json, re, sys, zipfile, hashlib
root=Path(__file__).resolve().parents[1]
checks=0

def check(name, condition):
 global checks
 assert condition, name
 checks+=1
 print('PASS',name)

class Parser(HTMLParser):
 def __init__(self):
  super().__init__();self.tags=[];self.ids=[]
 def handle_starttag(self,tag,attrs):
  attrs=dict(attrs);self.tags.append((tag,attrs))
  if 'id' in attrs:self.ids.append(attrs['id'])

for name in ['index.html','dashboard.html']:
 p=Parser();p.feed((root/name).read_text())
 check(name+' has unique ids',len(p.ids)==len(set(p.ids)))
 missing=[]
 for tag,a in p.tags:
  for k in ['src','href']:
   url=a.get(k,'')
   if not url or url.startswith(('http:','https:','data:','mailto:')):continue
   if url.startswith('#'):
    if url[1:] not in p.ids:missing.append(url)
   elif not (root/url.split('#')[0]).exists():missing.append(url)
 check(name+' local references resolve',not missing)
 if name=='index.html':
  check('Five cinematic scenes remain in reference order',[a.get('id') for tag,a in p.tags if tag=='section']==['storm','intelligence','people','command','future'])
  check('Dashboard iframe does not load automatically',all('src' not in a for tag,a in p.tags if tag=='iframe'))
  check('Sound is off by default',next(a for _,a in p.tags if a.get('id')=='sound')['aria-pressed']=='false')
  check('All decision cards present',set(a['data-decision'] for _,a in p.tags if 'data-decision' in a)=={'RELEASE','REVIEW','HOLD'})
for f in (root/'fixtures').glob('*.json'):json.loads(f.read_text())
check('All recorded fixtures parse',True)
s=(root/'cinematic.js').read_text()
check('Cinematic script has no banking API endpoint calls','/api/' not in s and "fetch('fixtures/simulate.json')" in s)
check('Reduced motion and visibility handling exist','prefers-reduced-motion' in s and 'visibilitychange' in s)
css=(root/'cinematic.css').read_text()
check('Desktop/mobile rules and scene motion controls present','max-width:600px' in css and '.scene.is-hidden' in css and '.paused' in css)
for url in re.findall(r'url\([\'"]?([^\)\'\"]+)',css):check('CSS asset exists: '+url,(root/url).is_file())
if len(sys.argv)>1:
 z=zipfile.ZipFile(sys.argv[1]);protected=[]
 for name in z.namelist():
  if name.endswith('/'):continue
  if name.startswith('dashboard/fixtures/') or (not name.startswith('dashboard/') and (root.parent/'api').is_dir()):
   dest=root.parent/name
   if not dest.exists() or dest.read_bytes()!=z.read(name):protected.append(name)
 check('All fixtures and any included backend/source files byte-identical',not protected)
 source_image=Path(sys.argv[1]).parent/'image.png'
 if source_image.exists():check('Reference image byte-identical',(root/'assets/reference.png').read_bytes()==source_image.read_bytes())
 check('Original dashboard layout preserved',z.read('dashboard/index.html')==(root/'dashboard.html').read_bytes())
 old=z.read('dashboard/app.js').decode().replace('\r\n','\n')
 new=(root/'app.js').read_text()
 expected=old.replace('  loadScenario(1);\n});',"  await loadScenario(1);\n  window.nyayaDashboardReady = true;\n  const requestedTab = window.location.hash.slice(1);\n  if (['tab-replay', 'tab-xray', 'tab-policy', 'tab-analyst'].includes(requestedTab)) switchTab(requestedTab);\n});",1)
 check('Only app.js change is readiness/hash tab selection',new==expected)
print(f'\n{checks} static/source checks passed. These do not test browser layout.')
