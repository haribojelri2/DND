# -*- coding: utf-8 -*-
# BASE 그립(신축3, 좌측 확장) 시 throat 바 좌측단 호가 안 따라오는 문제:
#   throat 좌측단(x≈throat_min) 호를 신축3 선택셋+spec(74=2 이동)에 추가.
#   (신축2엔 이미 있고 프레임이 걸러줌. 신축3엔 없어서 추가.)
import ezdxf, math
SRC=r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_frameseam.dxf'
OUT=r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_v3.dxf'

doc=ezdxf.readfile(SRC)
# 블록별 throat x범위 + 호 handle(center)
blk_throat={}; arc_info={}   # arc_info[h]=(blk, cx, cy)
h2blk={}; throat=set()
for b in doc.blocks:
    if not b.name.startswith('rail34_'):continue
    xs=[]
    for e in b:
        h2blk[e.dxf.handle]=b.name
        if e.dxftype()=='LINE':
            s,en=e.dxf.start,e.dxf.end
            if abs(s.y-en.y)<1 and abs(s.x-en.x)<600: xs+=[s.x,en.x];throat.add(e.dxf.handle)
        elif e.dxftype()=='ARC':
            arc_info[e.dxf.handle]=(b.name,e.dxf.center.x,e.dxf.center.y)
    if xs: blk_throat[b.name]=(min(xs),max(xs))

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

def lead_of(pair):
    v=pair[1];return v[:len(v)-len(v.lstrip())], ('\r' if v.endswith('\r') else '')

added_total=0
for T in ents:
    if cs(T[0][1])!='BLOCKSTRETCHACTION':continue
    if (([cs(v) for c,v in T if cs(c)=='301'] or [''])[0])!='BaseXDelta':continue  # 신축3(좌측)만
    tgts=[cs(v) for c,v in T if cs(c)=='331']
    hit=[x for x in tgts if x in throat]
    if not hit:continue
    blk=h2blk[hit[0]]; tmin,tmax=blk_throat[blk]
    have=set(tgts)
    # 이 블록 호 중 center x≈throat 좌측단(tmin), 아직 없는 것
    add=[h for h,(bb,cx,cy) in arc_info.items() if bb==blk and abs(cx-tmin)<120 and h not in have]
    if not add:continue
    # 선택셋(71+330)와 spec(73) 위치
    def find(pred,st=0):
        for i in range(st,len(T)):
            if pred(T[i]):return i
        return -1
    i_act=find(lambda t:cs(t[0])=='100' and cs(t[1])=='AcDbBlockAction')
    i71=find(lambda t:cs(t[0])=='71',i_act)
    j=i71+1
    while j<len(T) and cs(T[j][0])=='330':j+=1   # 선택셋 끝
    sel_end=j
    i_str=find(lambda t:cs(t[0])=='100' and cs(t[1])=='AcDbBlockStretchAction')
    i73=find(lambda t:cs(t[0])=='73',i_str)
    k=i73+1
    while k<len(T) and cs(T[k][0])=='331':
        k+=1;n=int(cs(T[k][1]));k+=1
        for _ in range(n):k+=1
    spec_end=k
    # 코드/값 들여쓰기 샘플
    cl330,tl330=lead_of(T[i71+1]) if cs(T[i71+1][0])=='330' else (' ','')
    ccode=T[i71+1][0] if cs(T[i71+1][0])=='330' else '330'
    # 헬퍼: 들여쓴 pair 생성 (기존 라인 포맷 모방)
    def mk(code,val):
        # code 라인 들여쓰기 = 기존 330 코드라인, 값 들여쓰기 = 기존 330 값라인
        return (ccode.replace('330',code) if code!=ccode else ccode, tl330 and (cl330+val+'\r') or (cl330+val))
    # 실제로는 code 라인도 동일 들여쓰기 필요 — 기존 라인에서 복제
    code_lead=T[i71+1][0][:len(T[i71+1][0])-len(T[i71+1][0].lstrip())]
    val_lead=cl330
    cr = '\r' if T[i71+1][0].endswith('\r') else ''
    def P(code,val):
        return (code_lead+code+cr, val_lead+val+(('\r') if tl330 else ''))
    new_sel=[P('330',h) for h in add]
    new_spec=[]
    for h in add: new_spec += [P('331',h),P('74','2'),P('94','0'),P('94','1')]
    # 71,73 증가
    def bump(i,by):
        v=T[i][1];lead=v[:len(v)-len(v.lstrip())];cr2='\r' if v.endswith('\r') else '';T[i]=(T[i][0],lead+str(int(cs(v))+by)+cr2)
    # 삽입 (뒤에서부터: spec_end 먼저, 그 다음 sel_end)
    T[spec_end:spec_end]=new_spec
    bump(i73,len(add))
    T[sel_end:sel_end]=new_sel
    bump(i71,len(add))
    added_total+=len(add)

out=[]
for T in ents:
    for c,v in T:out.append(c);out.append(v)
open(OUT,'w',encoding='utf-8').write('\n'.join(out)+('\n' if not out[-1].endswith('\n') else ''))
print('신축3에 throat 좌측 호 총 %d개 추가'%added_total)
a=ezdxf.readfile(OUT).audit();print('AUDIT errors=%d fixes=%d'%(len(a.errors),len(a.fixes)))
print('출력:',OUT)
