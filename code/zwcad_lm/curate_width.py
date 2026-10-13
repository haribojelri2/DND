# -*- coding: utf-8 -*-
# SAFE34: 거리2(폭) 신축을 "throat/조인트 바(짧은 수평선)만" 남기도록 편집.
#   폭 신축 = throat 바를 타깃하는 BLOCKSTRETCHACTION. 거기서 바 외(edge/호/대각) 대상 전부 제거.
#   길이(거리1) 신축·비율 신축은 throat 바 안 건드리므로 그대로 유지됨.
import ezdxf, pathlib
SRC=r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_2LANE_BASE_FOLLOW.dxf'
OUT=r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_barwidth.dxf'

# throat/조인트 바 핸들 수집 (rail34 블록의 수평 LINE, 길이<600 = 캡1020 제외)
doc=ezdxf.readfile(SRC)
throat=set()
for b in doc.blocks:
    if not b.name.startswith('rail34_'): continue
    for e in b:
        if e.dxftype()=='LINE':
            s,en=e.dxf.start,e.dxf.end
            if abs(s.y-en.y)<1 and abs(s.x-en.x)<600:  # 짧은 수평 = throat/조인트
                throat.add(e.dxf.handle)
print('throat/조인트 바 핸들 %d개'%len(throat))

# raw 파싱
raw=open(SRC,encoding='utf-8',errors='ignore').read().split('\n')
# (code,value) 보존 — 원래 들여쓰기/공백 그대로 두려고 strip 안 함
pairs=[(raw[j],raw[j+1]) for j in range(0,len(raw)-1,2)]
def cs(x): return x.strip()
ents=[];cur=None
for c,v in pairs:
    if cs(c)=='0':
        if cur:ents.append(cur)
        cur=[(c,v)]
    else:
        if cur is None: cur=[(c,v)]
        else: cur.append((c,v))
if cur:ents.append(cur)

def curate(T, keep):
    """폭 신축 T에서 keep(throat 핸들)만 남김."""
    # 인덱스 찾기
    def find(pred,start=0):
        for i in range(start,len(T)):
            if pred(T[i]): return i
        return -1
    i_act=find(lambda t: cs(t[0])=='100' and cs(t[1])=='AcDbBlockAction')
    i71=find(lambda t: cs(t[0])=='71', i_act)
    # 선택셋 330들
    j=i71+1; sel=[]
    while j<len(T) and cs(T[j][0])=='330': sel.append(T[j]); j+=1
    sel_end=j
    kept_sel=[t for t in sel if cs(t[1]) in keep]
    i_str=find(lambda t: cs(t[0])=='100' and cs(t[1])=='AcDbBlockStretchAction')
    i73=find(lambda t: cs(t[0])=='73', i_str)
    # spec 그룹 파싱
    k=i73+1; specs=[]  # (handle, [tags])
    while k<len(T) and cs(T[k][0])=='331':
        grp=[T[k]]; h=cs(T[k][1]); k+=1
        # 74=n
        n=int(cs(T[k][1])); grp.append(T[k]); k+=1
        for _ in range(n): grp.append(T[k]); k+=1
        specs.append((h,grp))
    spec_end=k
    kept_spec=[g for h,g in specs if h in keep]
    # 71,73 값 형식(들여쓰기) 유지
    def repl(orig, num):
        v=orig[1]; lead=v[:len(v)-len(v.lstrip())]; return (orig[0], lead+str(num)+('\r' if v.endswith('\r') else ''))
    new=[]
    new+=T[:i71]
    new.append(repl(T[i71], len(kept_sel)))
    new+=kept_sel
    new+=T[sel_end:i73]
    new.append(repl(T[i73], len(kept_spec)))
    for g in kept_spec: new+=g
    new+=T[spec_end:]
    return new, len(sel), len(kept_sel)

changed=0
for idx,T in enumerate(ents):
    if cs(T[0][1])!='BLOCKSTRETCHACTION': continue
    tgts=set(cs(v) for c,v in T if cs(c)=='331')
    hit=tgts & throat
    if not hit: continue   # throat 바 안 건드리면 폭 신축 아님 → 유지
    ents[idx],n0,n1=curate(T, throat)
    changed+=1

# 재조립
out=[]
for T in ents:
    for c,v in T: out.append(c); out.append(v)
open(OUT,'w',encoding='utf-8').write('\n'.join(out)+('\n' if not out[-1].endswith('\n') else ''))
print('폭 신축 %d개 편집'%changed)
d=ezdxf.readfile(OUT); a=d.audit()
print('AUDIT errors=%d fixes=%d'%(len(a.errors),len(a.fixes)))
print('출력:',OUT)
