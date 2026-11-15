import sys
# Qt .qm parser/editor. Safely edits ONLY Translation entries (Tag_Translation=3),
# preserving byte length (right-pad with spaces) so the Hashes index/offsets stay valid.
MAGIC = bytes.fromhex("3cb86418caef9c95cd211cbf60a1bddd")
Tag_End,Tag_SourceText16,Tag_Translation,Tag_Context16,Tag_Obsolete1,Tag_SourceText,Tag_Context,Tag_Comment,Tag_Obsolete2 = range(1,10)

def u32(d,i): return int.from_bytes(d[i:i+4],'big')

def main():
    src, dst, mode = sys.argv[1], sys.argv[2], sys.argv[3]  # mode: scan | write
    d = bytearray(open(src,'rb').read())
    assert d[:16]==MAGIC, "bad magic"
    # walk top-level blocks: tag(1) + len(4) + payload
    i=16; blocks={}
    while i < len(d):
        tag=d[i]; ln=u32(d,i+1); start=i+5
        blocks[tag]=(start,ln)
        i=start+ln
    MSG_TAG=0x69
    assert MSG_TAG in blocks, f"no messages block; blocks={list(blocks)}"
    mstart,mlen=blocks[MSG_TAG]; mend=mstart+mlen
    repls=[("Language Study","Audiobooks"),("language study","audiobooks")]
    changed=0; j=mstart
    while j < mend:
        tag=d[j]; j+=1
        if tag==Tag_End: continue
        if tag in (Tag_Translation,Tag_SourceText16,Tag_Context16):
            ln=u32(d,j); j+=4
            if ln!=0xffffffff:
                raw=bytes(d[j:j+ln])
                if tag==Tag_Translation:
                    try: txt=raw.decode('utf-16-be')
                    except: txt=None
                    if txt is not None and any(a in txt for a in ("Language Study","language study")):
                        new=txt
                        for a,b in repls: new=new.replace(a,b)
                        if len(new)<len(txt): new=new+(" "*(len(txt)-len(new)))
                        nb=new.encode('utf-16-be')
                        assert len(nb)==ln, f"len mismatch {len(nb)} vs {ln} for {txt!r}"
                        if mode=="write": d[j:j+ln]=nb
                        print(f"  edit @0x{j:06x}: {txt!r} -> {new!r}")
                        changed+=1
                j+=ln
        elif tag in (Tag_SourceText,Tag_Context,Tag_Comment):
            ln=u32(d,j); j+=4
            if tag==Tag_SourceText and b"Language Study" in bytes(d[j:j+ln]):
                print(f"  [!] SourceText contains 'Language Study' @0x{j:06x} (8-bit) -> would need hash rebuild")
            j+=ln
        else:
            # unknown tag; stop to be safe
            print(f"  [?] unknown tag 0x{tag:02x} @0x{j-1:06x}, stopping"); break
    print(f"translations edited: {changed}")
    if mode=="write":
        open(dst,'wb').write(d)
        print(f"wrote {dst} ({len(d)} bytes; original {len(open(src,'rb').read())})")

main()
