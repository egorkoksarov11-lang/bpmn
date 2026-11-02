from bpmn_v23.render import lane_caption


def test_long_role_name_fits_without_spilling_into_the_diagram_body():
    name='Работник, уполномоченный на передачу документов адресату'
    lines,size,overflow=lane_caption(name,152)
    assert not overflow and 10<=size<=14 and len(lines)*(size+1)<=44
    assert ''.join(''.join(lines).split())==''.join(name.split())
