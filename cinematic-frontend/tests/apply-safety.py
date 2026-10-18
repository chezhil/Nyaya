"""Exercise the guarded installer only in temporary local Git repositories. No remote calls."""
from pathlib import Path
import tempfile,subprocess,sys,zipfile,shutil
package=Path(__file__).resolve().parents[2]
installer=package/'APPLY_FRONTEND.py'
if not installer.exists():raise SystemExit('Run this test inside the extracted final package.')
source=Path(sys.argv[1]).resolve()
checks=0

def check(name,ok):
 global checks
 assert ok,name
 checks+=1;print('PASS',name)
with tempfile.TemporaryDirectory(prefix='nyaya-apply-test-') as d:
 repo=Path(d)/'repo';repo.mkdir()
 with zipfile.ZipFile(source) as z:z.extractall(repo)
 def git(*args):
  return subprocess.run(['git','-C',str(repo),'-c','user.name=NYAYA Local Test','-c','user.email=test@example.invalid','-c','commit.gpgsign=false',*args],capture_output=True,text=True,check=True)
 git('init','-b','nightfall-frontend');git('add','.');git('commit','-m','test: supplied baseline')
 def apply(*args):return subprocess.run([sys.executable,str(installer),str(repo),*args],capture_output=True,text=True)
 initial={str(p.relative_to(repo)):p.read_bytes() for p in repo.rglob('*') if p.is_file() and '.git' not in p.parts}
 r=apply();check('Dry run succeeds without file changes',r.returncode==0 and all((repo/n).read_bytes()==v for n,v in initial.items()))
 git('switch','-c','main');r=apply('--apply');check('Installer rejects main',r.returncode!=0 and 'nightfall-frontend' in r.stdout+r.stderr)
 git('switch','nightfall-frontend');(repo/'dashboard/local-note.txt').write_text('local teammate work')
 r=apply('--apply');check('Installer rejects untracked dashboard work',r.returncode!=0);(repo/'dashboard/local-note.txt').unlink()
 r=apply('--apply');check('Approved local apply succeeds',r.returncode==0 and (repo/'dashboard/cinematic.js').is_file())
 check('Apply preserves every backend file',all((repo/n).read_bytes()==v for n,v in initial.items() if not n.startswith('dashboard/')))
 check('Apply retains branch and creates no remote',git('branch','--show-current').stdout.strip()=='nightfall-frontend' and not git('remote').stdout.strip())
 check('Repeated apply refuses overwriting work',apply('--apply').returncode!=0)
 backup_line=next((l for l in r.stdout.splitlines() if 'Original dashboard backup:' in l),None)
 if backup_line:shutil.rmtree(backup_line.split('Original dashboard backup:',1)[1].strip())
print(f'\n{checks} installer safety checks passed. All mutations confined to a disposable local test checkout.')
