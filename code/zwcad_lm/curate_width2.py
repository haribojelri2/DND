# -*- coding: utf-8 -*-
# SAFE34 폭 신축 수정(원인1): 각 폭 신축에서 "바의 고정단쪽 cap 호"만 제외.
#   → 바 이동단 호는 남아 따라가고(호 follow), 고정단 호는 정지 → 찢어짐 제거. (rail2_final 패턴)
import ezdxf, math
SRC=r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_2LANE_BASE_FOLLOW.dxf'
OUT=r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_barwidth2.dxf'

doc=ezdxf.readfile(SRC)
# 지오: handle -> 정보
geo={}
for b in doc.blocks:
    if not b.name.startswith('rail34_'): continue
    for e in b:
        h=e.dxf.handle
        if e.dxftype()=='LINE':
            s,en=e.dxf.start,e.dxf.end
            geo[h]=('LINE',(s.x,s.y),(en.x,en.y),abs(s.y-en.y)<1 and abs(s.x-en.x)<600)  # 4th=throat바
        elif e.dxftype()=='ARC':
            geo[h]=('ARC',(e.dxf.center.x,e.dxf.center.y),None,False)

# raw 파싱 (들여쓰기 보존)
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

def parse_specs(T):
    """신축 spec: {handle:[point idx]} 반환"""
    k=0
    while k<len(T) and not(cs(T[k][0])=='100' and cs(T[k][1])=='AcDbBlockStretchAction'):k+=1
    while k<len(T) and cs(T[k][0])!='73':k+=1
    if k>=len(T):return {}
    k+=1; sp={}
    while k<len(T) and cs(T[k][0])=='331':
        h=cs(T[k][1]);k+=1;n=int(cs(T[k][1]));k+=1;idx=[]
        for _ in range(n):idx.append(int(cs(T[k][1])));k+=1
        sp[h]=idx
    return sp

def curate(T, keep):
    def find(pred,start=0):
        for i in range(start,len(T)):
            if pred(T[i]):return i
        return -1
    i_act=find(lambda t:cs(t[0])=='100' and cs(t[1])=='AcDbBlockAction')
    i71=find(lambda t:cs(t[0])=='71',i_act)
    j=i71+1;sel=[]
    while j<len(T) and cs(T[j][0])=='330':sel.append(T[j]);j+=1
    sel_end=j
    kept_sel=[t for t in sel if cs(t[1]) in keep]
    i_str=find(lambda t:cs(t[0])=='100' and cs(t[1])=='AcDbBlockStretchAction')
    i73=find(lambda t:cs(t[0])=='73',i_str)
    k=i73+1;specs=[]
    while k<len(T) and cs(T[k][0])=='331':
        grp=[T[k]];h=cs(T[k][1]);k+=1;n=int(cs(T[k][1]));grp.append(T[k]);k+=1
        for _ in range(n):grp.append(T[k]);k+=1
        specs.append((h,grp))
    spec_end=k
    kept_spec=[g for h,g in specs if h in keep]
    def repl(o,num):
        v=o[1];lead=v[:len(v)-len(v.lstrip())];return(o[0],lead+str(num)+('\r' if v.endswith('\r') else ''))
    new=T[:i71]+[repl(T[i71],len(kept_sel))]+kept_sel+T[sel_end:i73]+[repl(T[i73],len(kept_spec))]
    for g in kept_spec:new+=g
    new+=T[spec_end:]
    return new

throat=set(h for h,g in geo.items() if g[0]=='LINE' and g[3])
changed=0; removed_total=0
for idx,T in enumerate(ents):
    if cs(T[0][1])!='BLOCKSTRETCHACTION':continue
    tgts=set(cs(v) for c,v in T if cs(c)=='331')
    if not (tgts & throat):continue   # throat 바 없으면 폭 신축 아님
    specs=parse_specs(T)
    # 바(수평선)들의 고정단 좌표 수집
    fixed_pts=[]
    for h,idxs in specs.items():
        g=geo.get(h)
        if not g or g[0]!='LINE':continue
        if abs(g[1][1]-g[2][1])>1:continue  # 수평 아니면 skip
        pts=[g[1],g[2]]
        for i in (0,1):
            if i not in idxs: fixed_pts.append(pts[i])   # 안움직이는 끝 = 고정단
    # 제거대상: 고정단 근처(<=550) 중심의 호
    remove=set()
    for h in specs:
        g=geo.get(h)
        if not g or g[0]!='ARC':continue
        cx,cy=g[1]
        if any(math.hypot(cx-fx,cy-fy)<=550 for fx,fy in fixed_pts):
            remove.add(h)
    if not remove:continue
    keep=tgts - remove
    ents[idx]=curate(T, keep)
    changed+=1; removed_total+=len(remove)

out=[]
for T in ents:
    for c,v in T:out.append(c);out.append(v)
open(OUT,'w',encoding='utf-8').write('\n'.join(out)+('\n' if not out[-1].endswith('\n') else ''))
print('폭 신축 %d개에서 고정단 호 총 %d개 제외'%(changed,removed_total))
a=ezdxf.readfile(OUT).audit();print('AUDIT errors=%d fixes=%d'%(len(a.errors),len(a.fixes)))
print('출력:',OUT)
