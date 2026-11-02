from lxml import etree as ET
from tools.package_benchmark import inline_svg


def test_gallery_deduplicates_font_and_renames_markers_without_changing_geometry(tmp_path):
    p=tmp_path/'preview.svg'
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200"><defs><style>@font-face{font-family:test;src:url(data:font/ttf;base64,AAAA)}</style><marker id="arrow"/></defs><polyline points="10,20 100,20" marker-end="url(#arrow)"/></svg>')
    root=ET.fromstring(inline_svg(p,'after').encode());ns={'s':'http://www.w3.org/2000/svg'}
    assert not root.xpath('.//s:style',namespaces=ns)
    line=root.xpath('.//s:polyline',namespaces=ns)[0]
    assert line.get('points')=='10,20 100,20' and line.get('marker-end')=='url(#after-arrow)'
    assert root.xpath('.//s:marker',namespaces=ns)[0].get('id')=='after-arrow'
