#!/usr/bin/env python3
"""Hardlink exact duplicate generated drawable/YTD cache files; preserve every path.
Only regular files under a directory literally named sources inside --root are
eligible. Game archives, symlinks, images and arbitrary user files are excluded.
Default is a read-only plan. Source bytes are revalidated before each replacement.
"""
import argparse,hashlib,json,os,tempfile,time
from pathlib import Path


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()


def dedupe(root,apply=False):
    root=Path(root).resolve();start=time.monotonic();groups={};changes=[];hashed=0;logical=0
    # Do not follow symlink directories or files, including paths into the game.
    for folder,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=[d for d in dirs if not (Path(folder)/d).is_symlink()]
        for name in sorted(files):
            path=Path(folder)/name
            if path.is_symlink() or path.suffix.lower() not in ('.ydr','.ydd','.yft','.ytd') or 'sources' not in path.relative_to(root).parts[:-1]:continue
            st=path.stat()
            if not path.is_file():continue
            sha=digest(path);hashed+=st.st_size;identity=(st.st_size,sha);prior=groups.get(identity)
            if prior is None:groups[identity]=path;continue
            ps=prior.stat()
            if (st.st_dev,st.st_ino)==(ps.st_dev,ps.st_ino):continue
            if st.st_dev!=ps.st_dev:continue
            if apply:
                if prior.is_symlink() or path.is_symlink() or digest(prior)!=sha or digest(path)!=sha:raise ValueError('Cache file changed before deduplication')
                # Link first, then atomic rename: interruption leaves old path valid.
                fd,tmp=tempfile.mkstemp(prefix='.dedupe-',dir=path.parent);os.close(fd);os.unlink(tmp)
                try:
                    os.link(prior,tmp)
                    if digest(Path(tmp))!=sha or digest(path)!=sha:raise ValueError('Cache file changed during deduplication')
                    os.replace(tmp,path)
                finally:
                    if os.path.exists(tmp):os.unlink(tmp)
            logical+=st.st_size;changes.append({'path':str(path),'sameBytesAs':str(prior),'sha256':sha,'bytes':st.st_size})
    return {'applied':apply,'duplicatePaths':len(changes),'logicalDuplicateBytes':logical,'bytesHashed':hashed,'seconds':round(time.monotonic()-start,3),'changes':changes,'scope':'Generated source drawable/YTD only. Every path and byte preserved. Logical duplicate bytes are not a measurement of physical free-space gain.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--apply',action='store_true');p.add_argument('--out',required=True);a=p.parse_args();r=dedupe(a.root,a.apply);Path(a.out).write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({k:v for k,v in r.items() if k!='changes'},indent=2))
if __name__=='__main__':main()
