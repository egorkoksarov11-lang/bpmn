from tools.collect_scratch_results import correspondence,physical_bends


def scene():
    nodes={n:{'kind':'task'} for n in 'abc'};seq=[('f','a','b',''),('g','b','c','')]
    boxes={'a':(0,0,100,60),'b':(200,0,100,60),'c':(400,0,100,60)};paths={'f':[(100,30),(200,30)],'g':[(300,30),(400,30)]}
    return nodes,seq,boxes,paths


def test_reference_correspondence_is_translation_and_scale_invariant():
    nodes,seq,boxes,paths=scene();scaled={n:(x*3-200,y*3+170,w*3,h*3) for n,(x,y,w,h) in boxes.items()};routes={i:[(x*3-200,y*3+170) for x,y in ps] for i,ps in paths.items()}
    result=correspondence(nodes,seq,boxes,paths,scaled,routes)
    assert result['axis_direction_agreement']==result['reference_straight_recall']==1


def test_axis_alignment_does_not_hide_a_dogleg_between_consecutive_steps():
    nodes,seq,boxes,paths=scene();bent={**paths,'f':[(100,30),(130,30),(130,80),(170,80),(170,30),(200,30)]}
    result=correspondence(nodes,seq,boxes,paths,boxes,bent)
    assert result['axis_direction_agreement']==1 and result['reference_straight_recall']==.5
    assert physical_bends(bent['f'])==4


def test_subdivided_straight_segments_do_not_inflate_bends_but_reversal_counts():
    assert physical_bends([(0,0),(0,0),(10,0),(20,0)])==0
    assert physical_bends([(0,0),(10,0),(5,0)])==1
    assert physical_bends([(0,0),(10,10),(20,20)])==0
