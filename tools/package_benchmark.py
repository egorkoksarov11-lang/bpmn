"""Portable result bundle: all BPMNs and an offline vector comparison gallery.

The gallery embeds the shared font once and exports standalone SVGs on demand,
avoiding dozens of duplicate font payloads without changing diagram geometry.
"""
from pathlib import Path
from lxml import etree as ET
import argparse,base64,html,json,sys,zipfile
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src/v23'),str(Path(__file__).resolve().parents[1]/'src/v22')]
from bpmn_v23.typography import FONT


def inline_svg(path,prefix):
    root=ET.fromstring(path.read_bytes(),ET.XMLParser(resolve_entities=False,no_network=True))
    for e in list(root.iter()):
        if ET.QName(e).localname=='style':e.getparent().remove(e)
    ids={e.get('id'):prefix+'-'+e.get('id') for e in root.iter() if e.get('id')}
    for e in root.iter():
        if e.get('id'):e.set('id',ids[e.get('id')])
        for k,v in list(e.attrib.items()):
            for old,new in ids.items():v=v.replace('url(#'+old+')','url(#'+new+')')
            e.set(k,v)
    return ET.tostring(root,encoding='unicode')


def main():
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);p.add_argument('--baseline-dir',type=Path,required=True);p.add_argument('--candidate-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--extras-dir',type=Path);a=p.parse_args()
    if a.output.resolve()==a.report.resolve():p.error('Separate output required')
    report=json.loads(a.report.read_text());manifest={r['id']:r for r in report['manifest']};results={(r['engine'],r['id']):r for r in report['results']};font=base64.b64encode(FONT.read_bytes()).decode()
    fontcss="@font-face{font-family:'Open Sans';src:url(data:font/ttf;base64,"+font+")}text{font-family:'Open Sans',sans-serif}"
    header='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BPMN — испытания на референсах r8</title><style id="font-style">'''+fontcss+'''</style><style>body{font:15px/1.5 'Open Sans',sans-serif;margin:24px;color:#23364b;background:#f7f9fc}h1{font-size:24px}details{background:white;padding:12px;margin:12px 0;border:1px solid #d8e1ec;border-radius:8px}summary{cursor:pointer;font-weight:600}.pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}.diagram svg{width:100%;height:auto;display:block}.diagram.full svg{width:auto;height:auto}.diagram{overflow:auto;min-width:0;border-top:1px solid #ddd;margin-top:10px}button,a{margin-right:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}input{padding:8px;width:min(600px,90%)}@media(max-width:900px){.pair{grid-template-columns:1fr}}</style><h1>Автоматическая перекомпоновка ручных референсов — r8</h1><p>Слева контрольный human-режим, справа новый adaptive-режим. Все показанные результаты прошли проверку семантики, структуры DI, текста и геометрии. Неудачные и неподдерживаемые модели сохранены в отчёте. Это регрессионный набор разработки, не независимая оценка визуального сходства человеком.</p><p>Откройте нужный процесс, сравните схемы и скачайте BPMN или отдельный SVG. Шрифт встроен; интернет не требуется.</p><input id="filter" placeholder="Поиск по названию процесса"><p><a href="benchmark_report.json">Полный JSON-отчёт</a></p>'''
    cards=[];entries={}
    for identifier in sorted(manifest):
        model=manifest[identifier];parts=[]
        for engine,folder,title in [('human',a.baseline_dir,'Контроль'),('adaptive',a.candidate_dir,'Новый алгоритм')]:
            r=results.get((engine,identifier),{'status':'not_run'});prefix=engine+'-'+identifier
            if r['status']=='success':
                dest=folder/identifier;rel=f'models/{engine}/{identifier}.bpmn';entries[rel]=(dest/'process_08_v23.bpmn').read_bytes()
                for filename in ('geometry_report.json','semantic_diff.json','run_report.json','reference_conformity.json'):
                    f=dest/filename
                    if f.exists():entries[f'reports/{engine}/{identifier}/{filename}']=f.read_bytes()
                m=r['measurements'];scene=inline_svg(dest/'process_08_v23.svg',prefix)
                metrics=f"контакты {m['contacts']}, изгибы {m['sequence_bends']} (sequenceFlow), длина {m['sequence_length']:.1f}"
                parts.append(f'<section><h3>{title}</h3><p>{metrics}</p><a download href="{rel}">BPMN</a><button data-zoom="{prefix}">Масштаб 1:1</button><button data-export="{prefix}">Скачать SVG</button><div class="diagram" id="{prefix}">{scene}</div></section>')
            else:
                reason=r.get('reason') or r.get('error') or model.get('validation_error') or r['status']
                parts.append(f'<section><h3>{title}: {html.escape(r["status"])}</h3><pre>{html.escape(str(reason))}</pre></section>')
        name=identifier+' — '+model['file']
        cards.append(f'<details data-name="{html.escape(name.lower(),quote=True)}"><summary>{html.escape(name)}</summary><div class="pair">'+''.join(parts)+'</div></details>')
    script=r'''<script>document.querySelectorAll('[data-zoom]').forEach(b=>b.addEventListener('click',()=>{const d=document.getElementById(b.dataset.zoom);d.classList.toggle('full');b.textContent=d.classList.contains('full')?'Вписать':'Масштаб 1:1'}));document.getElementById('filter').addEventListener('input',e=>{const q=e.target.value.toLowerCase();document.querySelectorAll('details').forEach(d=>d.hidden=!d.dataset.name.includes(q))});document.querySelectorAll('[data-export]').forEach(b=>b.addEventListener('click',()=>{const svg=document.getElementById(b.dataset.export).querySelector('svg').cloneNode(true);const style=document.createElementNS('http://www.w3.org/2000/svg','style');style.textContent=document.getElementById('font-style').textContent;svg.prepend(style);const xml='<?xml version="1.0" encoding="UTF-8"?>\n'+new XMLSerializer().serializeToString(svg);const url=URL.createObjectURL(new Blob([xml],{type:'image/svg+xml;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=b.dataset.export+'.svg';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}));</script></html>'''
    if a.extras_dir:
        for path in sorted(a.extras_dir.rglob('*')):
            if path.is_file() and (path.suffix in {'.bpmn','.svg'} or path.name in {'geometry_report.json','semantic_diff.json','run_report.json'}):
                entries['extras/'+str(path.relative_to(a.extras_dir))]=path.read_bytes()
    entries['comparison.html']=(header+''.join(cards)+script).encode();entries['benchmark_report.json']=a.report.read_bytes()
    entries['FONT-LICENSE.txt']=(FONT.parent/'FONT-LICENSE.txt').read_bytes()
    entries['README.txt']='Откройте comparison.html в браузере. В нём все схемы до/после и экспорт полноценных SVG со встроенным шрифтом. Редактируемые BPMN находятся в models/, отчёты — в reports/. Исходный архив, офисные документы и сырые журналы записи не включены.\n'.encode()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(a.output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,raw in sorted(entries.items()):
            info=zipfile.ZipInfo(name,date_time=(2026,11,2,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,raw)
    with zipfile.ZipFile(a.output) as z:assert z.testzip() is None
    print(json.dumps({'files':len(entries),'bytes':a.output.stat().st_size,'gallery_bytes':len(entries['comparison.html'])}))


if __name__=='__main__':main()
