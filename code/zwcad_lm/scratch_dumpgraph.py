import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def load_objects(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        raw = f.read().split('\n')
    lines = [l.rstrip('\r') for l in raw]
    pairs = []
    i = 0
    while i + 1 < len(lines):
        code = lines[i].strip()
        val = lines[i+1]
        pairs.append((code, val))
        i += 2
    # split into entities at code '0'
    objs = []
    cur = None
    for code, val in pairs:
        if code == '0':
            if cur is not None:
                objs.append(cur)
            cur = {'type': val, 'pairs': []}
        else:
            if cur is not None:
                cur['pairs'].append((code, val))
    if cur is not None:
        objs.append(cur)
    # index by handle (group 5) — but some have 105 (dimstyle). use 5.
    by_handle = {}
    for o in objs:
        h = None
        for code, val in o['pairs']:
            if code == '5':
                h = val.strip()
                break
        o['handle'] = h
        if h:
            by_handle[h] = o
    return objs, by_handle

def get(o, code):
    return [v for c, v in o['pairs'] if c == code]

def get1(o, code, default=None):
    vs = get(o, code)
    return vs[0] if vs else default

def owner(o):
    # 330 typically first
    for c, v in o['pairs']:
        if c == '330':
            return v.strip()
    return None

def dump_file(path, target_block):
    objs, by = load_objects(path)
    print('#' * 70)
    print('FILE:', path, ' TARGET BLOCK:', target_block)
    # find block record for target
    br = None
    for o in objs:
        if o['type'] == 'BLOCK_RECORD':
            if get1(o, '2') == target_block:
                br = o
                break
    print('block_record handle:', br['handle'] if br else None)
    # extension dict: 360 in block record
    extdict = get(br, '360')
    print('block_record 360 (ext dict):', extdict)
    # Find the eval graph. Graph owner chain: eval graph is owned by a dict owned by ext dict.
    # Approach: find ACAD_EVALUATION_GRAPH whose ownership traces to br handle.
    def traces_to_br(o):
        seen = set()
        cur = o
        for _ in range(8):
            ow = owner(cur)
            if ow is None:
                return False
            if ow == br['handle']:
                return True
            if ow in seen:
                return False
            seen.add(ow)
            cur = by.get(ow)
            if cur is None:
                return False
        return False
    graph = None
    for o in objs:
        if o['type'] == 'ACAD_EVALUATION_GRAPH' and traces_to_br(o):
            graph = o
            break
    print('eval graph handle:', graph['handle'] if graph else None)
    # The graph lists node handles. Nodes reference via 360. Parse graph edges.
    # Group codes in ACAD_EVALUATION_GRAPH: 96 flag, 97 numedges?, then 91 node ids,
    # 93, 360 node handle for each node; edges 92,94,95,98
    if graph:
        print('--- graph raw pairs ---')
        for c, v in graph['pairs']:
            print(f'   {c}: {v}')
    # Now collect all dynamic-block objects owned by graph
    gh = graph['handle'] if graph else None
    node_objs = [o for o in objs if owner(o) == gh]
    print(f'--- {len(node_objs)} objects owned by graph ---')
    return objs, by, br, graph, node_objs

if __name__ == '__main__':
    path = sys.argv[1]
    blk = sys.argv[2]
    dump_file(path, blk)
