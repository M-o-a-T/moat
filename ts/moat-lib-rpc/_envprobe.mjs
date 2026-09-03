import { spawnSync } from 'node:child_process';
const code = `
import sys, os
print("EXEC", sys.executable)
print("PWD", os.getcwd())
print("HAS_PATH", "PATH" in os.environ, os.environ.get("PATH","")[:160])
try:
    import moat
    print("MOAT", moat.__file__)
except Exception as e:
    print("MOAT_ERR", repr(e))
`;
const r = spawnSync('python3', ['-c', code], { cwd: '/src/moat', stdio: 'pipe', env: process.env, timeout: 5000 });
console.log('rc', r.status);
console.log(r.stdout.toString());
console.error(r.stderr.toString());
