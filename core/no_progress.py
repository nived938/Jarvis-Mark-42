"""Hard guard against repeated identical tool calls making no progress."""
from __future__ import annotations
import json,hashlib
class NoProgressGuard:
    def __init__(self,repeat_limit=3):
        self.repeat_limit=int(repeat_limit)
        self._calls={}
    def reset(self):
        self._calls.clear()
    def check(self,name,args):
        key=json.dumps([name,args],sort_keys=True,default=str).encode()
        digest=hashlib.sha256(key).hexdigest()
        n=self._calls.get(digest,0)+1
        self._calls[digest]=n
        if n>self.repeat_limit:
            return False,n
        return True,n
    def counts(self):
        return dict(self._calls)
