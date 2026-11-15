import pickle, bisect, sys, re
G = pickle.load(open(sys.argv[1], 'rb'))
starts, calls, callers, strs, ptrs = G['starts'], G['calls'], G['callers'], G['strs'], G['ptrs']
def fn_of(a):
    i = bisect.bisect_right(starts, a) - 1
    return starts[i]
def files_of(f):
    return sorted({re.sub(r'^(\.\./)+', '', s) for _, s in strs.get(f, []) if re.search(r'\.(cpp|h|hpp)$', s)})
_file_fns = sorted(f for f in strs if files_of(f))
def src(f, radius=0x600):
    """Source file of f: its own __FILE__ string, else that of the nearest function within radius."""
    own = files_of(f)
    if own: return own[0].split('/')[-1]
    i = bisect.bisect_left(_file_fns, f)
    cands = [x for x in (_file_fns[i-1] if i > 0 else None, _file_fns[i] if i < len(_file_fns) else None) if x is not None and abs(x - f) <= radius]
    if not cands: return '?'
    n = min(cands, key=lambda x: abs(x - f))
    return '~' + files_of(n)[0].split('/')[-1]
def callers_of(t, depth=1, seen=None):
    """Direct callers; thin tail-call wrappers (b-only, tiny) are followed one more level."""
    out = []
    for (f, site, kind) in sorted(callers.get(t, [])):
        out.append((f, site, kind))
    return out
