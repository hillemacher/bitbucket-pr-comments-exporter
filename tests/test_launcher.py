"""Exercise launcher transactions with a fake Docker CLI, never a real daemon."""
import json
import os
from pathlib import Path
import socketserver
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
FAKE = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p=Path(os.environ['FAKE_STATE']); s=json.loads(p.read_text()); a=sys.argv[1:]
def out(v): print(v)
def save(): p.write_text(json.dumps(s))
if a[0]=='version': pass
elif a[0]=='build': pass
elif a[:2]==['image','inspect']:
 out('image-id' if '--format' in a else '[{}]')
elif a[0]=='ps':
 name=next(v[6:-1] for v in a if v.startswith('name=^'))
 if name in s and ('-a' in a or s[name]['running']): out(name)
elif a[0]=='inspect':
 c=s.get(a[-1],{}); fmt=a[a.index('--format')+1]
 if 'RestartPolicy' in fmt: out(c.get('policy','no'))
 elif '.Labels' in fmt:
  key=fmt.split('"')[1]; out(c.get('labels',{}).get(key,''))
elif a[0]=='run':
 if 'image-fingerprint' in a: out('a'*64)
 # preflight and MCP probes succeed without networking
elif a[0]=='create':
 if os.environ.get('FAIL_CREATE'): sys.exit(1)
 name=a[a.index('--name')+1]
 labels=dict(a[i+1].split('=',1) for i,x in enumerate(a) if x=='--label')
 s[name]={'running':False,'labels':labels,'policy':a[a.index('--restart')+1], 'port':a[a.index('-p')+1]};save()
elif a[0]=='start': s[a[1]]['running']=True;save()
elif a[0]=='stop': s[a[1]]['running']=False;save()
elif a[0]=='rename': s[a[2]]=s.pop(a[1]);save()
elif a[0]=='rm': s.pop(a[-1],None);save()
elif a[0]=='port': out(s[a[1]]['port'].rsplit(':',1)[0])
elif a[0]=='update': s[a[-1]]['policy']=a[a.index('--restart')+1];save()
elif a[0] in ('exec','network','logs'): pass
else: sys.exit('unexpected docker operation: '+repr(a))
'''


@unittest.skipIf(os.geteuid() == 0, 'Launcher deliberately refuses root')
class LauncherTests(unittest.TestCase):
    def test_lifecycle_and_failed_replacement_restore_previous_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); config=base/'config'; config.mkdir()
            (config/'config.toml').write_text('[mcp]\nbase_url="https://bitbucket.org"\n')
            (config/'bitbucket.pat').write_text('fixture')
            state=base/'state'; state.write_text('{}')
            harness=base/'launcher.sh'
            harness.write_text((ROOT/'container/bitbucket-pr-mcp.sh').read_text().replace('\nmain \"$@\"', '\nport_open() { container_running; }\nmain \"$@\"'))
            for name, text in [('docker',FAKE), ('uname','#!/bin/sh\necho Darwin\n')]:
                path=base/name;path.write_text(text);path.chmod(0o755)
            class Handler(socketserver.BaseRequestHandler):
                def handle(self): pass
            with socketserver.TCPServer(('127.0.0.1',0),Handler) as listener:
                thread=threading.Thread(target=listener.serve_forever,daemon=True);thread.start()
                env={**os.environ,'PATH':str(base)+os.pathsep+os.environ['PATH'],
                     'FAKE_STATE':str(state),'BB_CONFIG_DIR':str(config),'BB_MCP_PORT':str(listener.server_address[1])}
                def run(*args, **extra):
                    return subprocess.run(['bash',str(harness),*args],env={**env,**extra},capture_output=True,text=True,timeout=20)
                try:
                    result=run('start','--autostart');self.assertEqual(result.returncode,0,result.stderr)
                    s=json.loads(state.read_text());name='bitbucket-pr-mcp'
                    self.assertEqual(s[name]['policy'],'unless-stopped')
                    self.assertTrue(s[name]['port'].startswith('127.0.0.1:'))
                    s[name]['labels']['io.github.hillemacher.bitbucket-pr-mcp.fingerprint']='old';state.write_text(json.dumps(s))
                    result=run('start',FAIL_CREATE='1');self.assertNotEqual(result.returncode,0)
                    s=json.loads(state.read_text());self.assertTrue(s[name]['running'])
                    self.assertEqual(s[name]['policy'],'unless-stopped');self.assertNotIn(name+'-previous',s)
                    # Recover an interrupted replacement before starting a new one.
                    s[name+'-previous']=s.pop(name);s[name+'-previous']['running']=False;state.write_text(json.dumps(s))
                    (config/'.bitbucket-pr-mcp-previous-running').write_text('true\n')
                    result=run('start');self.assertEqual(result.returncode,0,result.stderr)
                    self.assertFalse((config/'.bitbucket-pr-mcp-previous-running').exists())
                    result=run('stop');self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(json.loads(state.read_text()),{})
                    # Refuse an unrelated container even when it has our expected name.
                    state.write_text(json.dumps({name: {'running': True, 'labels': {}}}))
                    result=run('stop');self.assertNotEqual(result.returncode,0)
                    self.assertIn(name,json.loads(state.read_text()))
                finally: listener.shutdown();thread.join()
