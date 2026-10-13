import sys
import scratch_dumpgraph as S

def get1(o, code, d=None):
    for c, v in o['pairs']:
        if c == code:
            return v
    return d

def getall(o, code):
    return [v for c, v in o['pairs'] if c == code]

def analyze(path, block):
    objs, by, br, graph, nodes = S.dump_file(path, block)
    # build node id -> handle from graph
    id2h = {}
    cur_id = None
    for c, v in graph['pairs']:
        if c == '91':
            cur_id = int(v)
        elif c == '360':
            id2h[cur_id] = v.strip()
    # object by handle within nodes
    nby = {o['handle']: o for o in nodes}
    def typ(h):
        o = nby.get(h)
        return o['type'] if o else '?'
    def label(o):
        # 300 label list; 305 param name
        labs = getall(o, '300')
        nm = get1(o, '305')
        return (labs, nm)
    print('\n===== NODE ID MAP for', block, '=====')
    for nid in sorted(id2h):
        h = id2h[nid]
        o = nby.get(h)
        if not o:
            print(f'  id {nid}: handle {h} (not in nodes)')
            continue
        labs, pnm = label(o)
        extra = f' param={pnm}' if pnm else ''
        print(f'  id {nid:3d}: {o["type"]:26s} h={h} labels={labs}{extra}')
    # Parameters
    print('\n===== PARAMETERS =====')
    params = [o for o in nodes if o['type'] == 'BLOCKLINEARPARAMETER']
    for p in params:
        nm = get1(p, '305')
        b = (get1(p,'1010'), get1(p,'1020'))
        e = (get1(p,'1011'), get1(p,'1021'))
        val = get1(p,'141'); cur = get1(p,'140')
        print(f'  {nm}: handle={p["handle"]} base={b} end={e} value(141)={val} dist(140)={cur}')
    # Grips
    print('\n===== GRIPS =====')
    grips = [o for o in nodes if o['type'] == 'BLOCKLINEARGRIP']
    for g in grips:
        labs = getall(g,'300')
        pos = (get1(g,'1010'), get1(g,'1020'))
        vec = (get1(g,'140'), get1(g,'141'))
        # grip node id via 90? actually 90 = eval id? print 90
        print(f'  {labs} handle={g["handle"]} pos={pos} vec(140,141)={vec}')
    # Actions with driving parameter (91) and factor(140), targets(71 count)
    print('\n===== ACTIONS =====')
    acts = [o for o in nodes if o['type'] in ('BLOCKSTRETCHACTION','BLOCKMOVEACTION')]
    for a in acts:
        labs = getall(a,'300')
        pnode = get1(a,'91')
        driven_h = id2h.get(int(pnode)) if pnode is not None else None
        driven_o = nby.get(driven_h)
        driven_name = get1(driven_o,'305') if driven_o else driven_h
        # property that drives: 301/302 labels
        props = getall(a,'301')
        factor = get1(a,'140')
        ntargets = get1(a,'71')
        # target handles = the 330 after 71, count ntargets
        print(f'  {a["type"]:20s} {labs} driven_by_node={pnode}({driven_name}) props={props} factor(140)={factor} ntargets(71)={ntargets}')
    return objs, by, br, graph, nodes, id2h, nby

if __name__ == '__main__':
    analyze(sys.argv[1], sys.argv[2])
