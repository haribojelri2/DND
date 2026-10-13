# -*- coding: utf-8 -*-
# SAFE34 폭 신축 프레임 seam을 throat 바를 관통하도록 이동(rail2_final 패턴).
#   EndXDelta 신축 = 좌변(작은 1011)을 바 중앙으로 / BaseXDelta 신축 = 우변(큰 1011)을 바 중앙으로.
#   → 프레임 재평가 시 바 한끝만 신축, 이동단 호는 프레임 안에 통째로 들어가 translate.
import ezdxf
SRC=r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_2LANE_BASE_FOLLOW.dxf'
OUT=r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_frameseam.dxf'

doc=ezdxf.readfile(SRC)
# 각 블록 throat 바의 x범위
blk_throat={}
for b in doc.blocks:
    if not b.name.startswith('rail34_'):continue
    xs=[]
    for e in b:
        if e.dxftype()=='LINE':
            s,en=e.dxf.start,e.dxf.end
            if abs(s.y-en.y)<1 and abs(s.x-en.x)<600: xs+=[s.x,en.x]
    if xs: blk_throat[b.name]=(min(xs),max(xs))
# 지오 handle -> throat 바 여부 + 소속블록
h2blk={}; throat=set()
for b in doc.blocks:
    if not b.name.startswith('rail34_'):continue
    for e in b:
        h2blk[e.dxf.handle]=b.name
        if e.dxftype()=='LINE':
            s,en=e.dxf.start,e.dxf.end
            if abs(s.y-en.y)<1 and abs(s.x-en.x)<600: throat.add(e.dxf.handle)

raw=open(SRC,encoding='utf-8',errors='ignore').read().split('\n')
pairs=[(raw[j],raw[j+1]) for j in range(0,len(raw)-1,2)]
def cs(x):return x.strip()
ents=[];cur=None
for c,v in pairs:
    if cs(c)=='0':
        if cur:ents.append(cur)
        cur=[(c,v)]
    else:
        if cur is None:cur=[(c,v)]
        else:cur.append((c,v))
if cur:ents.append(cur)

changed=0
for T in ents:
    if cs(T[0][1])!='BLOCKSTRETCHACTION':continue
    tgts=[cs(v) for c,v in T if cs(c)=='331']
    hit=[x for x in tgts if x in throat]
    if not hit:continue
    blk=h2blk[hit[0]]; tmin,tmax=blk_throat[blk]; center=(tmin+tmax)/2
    # 방향
    dxpr=[cs(v) for c,v in T if cs(c)=='301']
    is_end = dxpr and dxpr[0]=='EndXDelta'
    # StretchAction 헤더 뒤 72 다음 두 1011 위치 찾기
    k=0
    while k<len(T) and not(cs(T[k][0])=='100' and cs(T[k][1])=='AcDbBlockStretchAction'):k+=1
    while k<len(T) and cs(T[k][0])!='72':k+=1
    # 72 뒤: 1011,1021,1011,1021
    idx1011=[i for i in range(k,min(k+8,len(T))) if cs(T[i][0])=='1011']
    if len(idx1011)<2:continue
    vals=[(i,float(cs(T[i][1]))) for i in idx1011[:2]]
    if is_end:   # 좌변=작은 x
        ti=min(vals,key=lambda t:t[1])[0]
    else:        # base=우변=큰 x
        ti=max(vals,key=lambda t:t[1])[0]
    orig=T[ti][1]; lead=orig[:len(orig)-len(orig.lstrip())]; tail='\r' if orig.endswith('\r') else ''
    T[ti]=(T[ti][0], lead+repr(center)+tail)
    changed+=1

out=[]
for T in ents:
    for c,v in T:out.append(c);out.append(v)
open(OUT,'w',encoding='utf-8').write('\n'.join(out)+('\n' if not out[-1].endswith('\n') else ''))
print('폭 신축 %d개 프레임 seam 이동'%changed)
a=ezdxf.readfile(OUT).audit();print('AUDIT errors=%d fixes=%d'%(len(a.errors),len(a.fixes)))
print('출력:',OUT)
