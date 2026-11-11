"""Keep complementary internally generated candidates through final refinement."""


def choose_records(records,width):
    if width<1:raise ValueError('Positive portfolio width required')
    if not records:return []
    chosen=[];seen=set()
    def add(record):
        if record['signature'] not in seen and len(chosen)<width:
            seen.add(record['signature']);chosen.append(record)
    add(min(records,key=lambda r:(r['entry'][0],r['entry'][1])))
    # The previous objective supplies a complementary champion. It may become
    # better only after its initially awkward routes have been fully polished.
    add(min(records,key=lambda r:(r['legacy_rank'],r['entry'][1])))
    families={r['family'] for r in chosen}
    for r in sorted(records,key=lambda r:(r['family'] in families,r['entry'][0],r['entry'][1])):add(r)
    return chosen
