"""Run focused checks. Optional argument: path to the original source ZIP."""
from pathlib import Path
import subprocess,sys
here=Path(__file__).resolve().parent
commands=[['node','--check',str(here.parent/n)] for n in ['app.js','cinematic.js','audio-engine.js']]
commands += [['node',str(here/n)] for n in ['dashboard-contracts.cjs','audio-contracts.cjs','cinematic-contracts.cjs']]
commands += [[sys.executable,str(here/'static-checks.py'),*sys.argv[1:2]]]
if len(sys.argv)>1 and (here.parents[1]/'APPLY_FRONTEND.py').exists():commands += [[sys.executable,str(here/'apply-safety.py'),sys.argv[1]]]
for command in commands:
 print('\nRUN '+' '.join(command),flush=True)
 subprocess.run(command,check=True)
print('\nAll requested checks passed. DOM/HTTP/Web Audio are mocked; browser/live integration is NOT verified.')
