"""Offline human / prior algorithm / candidate gallery, with editable models."""
from pathlib import Path
import argparse,base64,hashlib,html,json,sys,tempfile,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from bpmn_v23.render import render
from bpmn_v23.typography import FONT
from package_benchmark import inline_svg


def main():
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);p.add_argument('--input-dir',type=Path,required=True);p.add_argument('--previous-dir',type=Path,required=True);p.add_argument('--candidate-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--extras-dir',type=Path);a=p.parse_args()
    report=json.loads(a.report.read_text());entries={'report.json':a.report.read_bytes()};cards=[]
    input_title='Вход со сбитыми координатами' if report['protocol'].get('input_kind')=='perturbed' else 'Ручной референс — исходные координаты'
    scratch=report['protocol'].get('source_geometry_used') is False
    previous_title='Контроль: построение с нуля' if scratch else 'Алгоритм r8'
    candidate_title='Новый алгоритм: с нуля' if scratch else 'Новый алгоритм r9'
    css="@font-face{font-family:'Open Sans';src:url(data:font/ttf;base64,"+base64.b64encode(FONT.read_bytes()).decode()+")}text{font-family:'Open Sans',sans-serif}"
    with tempfile.TemporaryDirectory() as folder:
        for row in report['results']:
            identifier=row['id'];parts=[]
            if row['status']!='success':cards.append('<details><summary>'+html.escape(identifier+' — '+row['status'])+'</summary><pre>'+html.escape(row.get('reason',''))+'</pre></details>');continue
            for key,title,source in [('manual',input_title,a.input_dir/(identifier+'.bpmn')),('previous',previous_title,a.previous_dir/identifier/'process_08_v23.bpmn'),('after',candidate_title,a.candidate_dir/identifier/'process_08_v23.bpmn')]:
                if key not in row or not source.exists():continue
                rel=f'models/{identifier}/{key}.bpmn';entries[rel]=source.read_bytes();preview=Path(folder)/(identifier+'-'+key+'.svg');render(source,preview);prefix=identifier+'-'+key
                scene=inline_svg(preview,prefix);m=row[key]
                metrics=f"Изгибы последовательности: {m['sequence_bends']}; контакты: {m['contacts']}; расстояние документов: {m['mean_anchor_gap']:.1f}; длина документных связей: {m['association_length']:.1f}."
                parts.append(f'<section><h3>{title}</h3><p>{metrics}</p><a download href="{rel}">BPMN</a><button data-zoom="{prefix}">1:1</button><button data-export="{prefix}">SVG</button><div class="diagram" id="{prefix}">{scene}</div></section>')
            cards.append('<details data-name="'+identifier+'"><summary>'+identifier+'</summary><div class="columns">'+''.join(parts)+'</div></details>')
            dest=a.candidate_dir/identifier
            for filename in ('geometry_report.json','semantic_diff.json','run_report.json'):
                if (dest/filename).exists():entries[f'reports/{identifier}/{filename}']=(dest/filename).read_bytes()
    header='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BPMN — ручные референсы и r9</title><style id="font-style">'''+css+'''</style><style>body{font:14px/1.5 'Open Sans',sans-serif;margin:24px;background:#f5f8fb;color:#20364b}details{margin:12px 0;background:white;padding:12px;border:1px solid #d0dbe6}summary{font-weight:bold;cursor:pointer}.columns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.diagram{overflow:auto;border-top:1px solid #ddd}.diagram svg{width:100%;height:auto}.diagram.full svg{width:auto;height:auto}pre{white-space:pre-wrap}button,a{margin-right:10px}@media(max-width:1000px){.columns{grid-template-columns:1fr}}</style><h1>Ручные референсы / r8 / r9</h1><p>Все три версии показаны общим SVG-рендерером: сравниваются координаты и маршруты, а не скриншоты родного редактора. Полный текст сохранён. Исходные ручные Bounds могут иметь диагностируемые наложения. Сохранение хорошего исходного рисунка само по себе не доказывает восстановление без координат. Неудачи и регрессии перечислены в report.json.</p><p>Откройте процесс, увеличьте 1:1; BPMN и экспорт SVG работают без интернета.</p>'''
    if scratch:
        header=header.replace('<title>BPMN — ручные референсы и r9</title>','<title>BPMN — построение с нуля r10</title>').replace('Ручные референсы / r8 / r9','Ручной эталон / контроль с нуля / новый алгоритм с нуля').replace('Сохранение хорошего исходного рисунка само по себе не доказывает восстановление без координат.','В обеих автоматических версиях исходные координаты, размеры, маршруты и позиции подписей удалены до планирования. Внешний готовый вариант не использовался. Эталон доступен только этапу оценки.')
    script=r'''<script>document.querySelectorAll('[data-zoom]').forEach(b=>b.onclick=()=>document.getElementById(b.dataset.zoom).classList.toggle('full'));document.querySelectorAll('[data-export]').forEach(b=>b.onclick=()=>{const svg=document.getElementById(b.dataset.export).querySelector('svg').cloneNode(true);const style=document.createElementNS('http://www.w3.org/2000/svg','style');style.textContent=document.getElementById('font-style').textContent;svg.prepend(style);const u=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)],{type:'image/svg+xml;charset=utf-8'}));const a=document.createElement('a');a.href=u;a.download=b.dataset.export+'.svg';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)});</script></html>'''
    entries['comparison.html']=(header+''.join(cards)+script).encode();entries['FONT-LICENSE.txt']=(FONT.parent/'FONT-LICENSE.txt').read_bytes()
    entries['README.txt']=('Откройте comparison.html. Три версии: исходный ручной референс, '+previous_title+', '+candidate_title+'. Редактируемые модели в models/, проверки в reports/, все регрессии в report.json. Это экспериментальный результат; достижение 80% визуального сходства не подтверждено.\n').encode()
    if a.extras_dir:
        for f in a.extras_dir.rglob('*'):
            if f.is_file() and f.suffix in {'.bpmn','.svg','.json'} and 'log' not in f.name:entries['extras/'+str(f.relative_to(a.extras_dir))]=f.read_bytes()
    entries['SHA256SUMS']=''.join(hashlib.sha256(raw).hexdigest()+'  '+name+'\n' for name,raw in sorted(entries.items())).encode()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(a.output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,raw in sorted(entries.items()):z.writestr(name,raw)
    print(json.dumps({'file':str(a.output),'bytes':a.output.stat().st_size,'entries':len(entries),'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest()}))


if __name__=='__main__':main()
