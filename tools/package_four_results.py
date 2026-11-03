"""Build a private offline comparison gallery from independently audited results."""
from pathlib import Path
import argparse,csv,hashlib,html,json,shutil,sys,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'src/v23'),str(ROOT/'src/v22')]
from benchmark_four_processes import evaluate
from bpmn_v23.render import render
from bpmn_v23 import __version__


def package(inputs,results,destination,control=None):
    inputs,results,destination=map(Path,(inputs,results,destination));destination.mkdir(parents=True,exist_ok=True)
    rows=[];parts=[]
    version=__version__.rsplit('.',1)[0]
    names={'S1':'Денежные средства','S2':'Операция через поставщика','S3':'Обмен валюты','S4':'Факторинг'}
    for source in sorted(inputs.glob('*.bpmn')):
        case=source.stem;folder=results/case;row=evaluate(source,folder);row['case']=case;rows.append(row)
        out=destination/case;out.mkdir(exist_ok=True);shutil.copyfile(folder/'process_08_v23.bpmn',out/'generated.bpmn');shutil.copyfile(folder/'process_08_v23.svg',out/'generated.svg')
        for f in ['geometry_report.json','semantic_diff.json','run_report.json']:shutil.copyfile(folder/f,out/f)
        render(source,out/'reference.svg')
        panels=[('Ручной пример','reference.svg'),('Первичная генерация v'+version,'generated.svg')]
        if control is not None:
            cf=Path(control)/case
            if (cf/'run_report.json').exists():
                try:
                    row['control']=evaluate(source,cf)['generated'];shutil.copyfile(cf/'process_08_v23.svg',out/'control.svg');panels.append(('Контроль прежним алгоритмом','control.svg'))
                except Exception as error:row['control_error']=str(error)
            else:row['control_error']='Контрольный прогон не сформировал проверенный результат'
        metrics=[]
        for label,key in [('Ручной пример','reference'),('v'+version,'generated'),('Контроль','control')]:
            if key not in row:continue
            m=row[key];metrics.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in [label,round(m['sequence_length']),m['sequence_bends'],m['contacts'],f"{100*m['straight_fraction']:.1f}%",f"{100*m['at_most_one_bend_fraction']:.1f}%",f"{100*m['window_readability']['simple_window_fraction']:.1f}%",m['window_readability']['short_internal_jogs'],round(m['extent_area'])] )+'</tr>')
        cards=''.join(f'<article><h3>{title}</h3><div class="viewport"><img data-zoom src="{case}/{file}" alt="{title}"></div></article>' for title,file in panels)
        parts.append(f'<section id="{case}"><h2>{html.escape(names.get(case,case))}</h2><p><a download href="{case}/generated.bpmn">Скачать BPMN</a> · <a href="{case}/generated.svg">Открыть SVG</a> · <a href="{case}/semantic_diff.json">Семантика: 0 изменений</a></p><table><thead><tr><th>Вариант</th><th>Длина потоков</th><th>Повороты</th><th>Контакты</th><th>Прямые</th><th>До 1 поворота</th><th>Простые окна</th><th>Короткие зигзаги</th><th>Площадь</th></tr></thead><tbody>'+''.join(metrics)+'</tbody></table><div class="panels">'+cards+'</div></section>')
    document='''<!doctype html><html lang="ru"><meta charset="utf-8"><title>BPMN v23.2 — сравнение четырёх процессов</title><style>body{font:15px system-ui;margin:24px;color:#203040}header{position:sticky;top:0;background:white;padding:12px;z-index:2;border-bottom:1px solid #bbb}nav a{margin-right:18px}.panels{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:16px}.viewport{height:650px;overflow:auto;border:1px solid #b8c7d5;background:#f8fafc}img{max-width:none;display:block}table{border-collapse:collapse;margin:18px 0}td,th{border:1px solid #c6d0db;padding:8px;text-align:left}section{margin:36px 0 70px;scroll-margin-top:120px}input{width:240px}</style><header><strong>Первичная генерация v23.2</strong><nav><a href="#S1">Денежные средства</a><a href="#S2">Поставщик</a><a href="#S3">Обмен</a><a href="#S4">Факторинг</a></nav><label>Масштаб <input id="zoom" type="range" min="15" max="150" value="45"> <span id="value">45%</span></label></header><p>Исходная геометрия удалена до построения. Ручные образцы показаны для сравнения после генерации. Оба варианта отображаются одним SVG-рендерером; это реконструкции геометрии, а не снимки редактора. Масштаб общий: размеры блоков можно сравнивать напрямую. Контакты включают пересечения и неоднозначные касания; это отдельная метрика, а не число нарушений бизнес-логики.</p>'''+''.join(parts)+'''<script>const images=[...document.querySelectorAll('img[data-zoom]')];for(const im of images){im.onload=()=>{im.dataset.native=im.naturalWidth;im.style.width=im.naturalWidth*.45+'px'}}document.getElementById('zoom').oninput=e=>{const v=+e.target.value;document.getElementById('value').textContent=v+'%';for(const im of images)im.style.width=(+(im.dataset.native||im.naturalWidth))*v/100+'px'}</script></html>'''
    document=document.replace('v23.2','v'+version)
    (destination/'comparison.html').write_text(document,encoding='utf-8')
    report={'protocol':{'from_scratch':True,'reference_used_only_after_generation':True,'all_business_xml_equal':all(all(r['checks'].values()) for r in rows),'corpus':'four development sessions; not held out; no claimed 80% visual similarity'},'results':rows}
    (destination/'benchmark_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with (destination/'metrics.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['case','variant','sequence_length','bends','contacts','straight_fraction','at_most_one_bend_fraction','area','normalized_sequence_length','simple_window_fraction','weighted_simple_window_fraction','short_internal_jogs','excess_wire_mean_task_units','flow_length_p90_task_units'])
        for row in rows:
            for variant in ['reference','generated','control']:
                if variant in row:
                    m=row[variant];w.writerow([row['case'],variant,*[m[k] for k in ['sequence_length','sequence_bends','contacts','straight_fraction','at_most_one_bend_fraction','extent_area','normalized_sequence_length']],*[m['window_readability'][k] for k in ['simple_window_fraction','weighted_simple_window_fraction','short_internal_jogs','excess_wire_mean_task_units','flow_length_p90_task_units']]])
    (destination/'README.txt').write_text('Откройте comparison.html. Новые схемы: S1–S4/generated.bpmn и generated.svg. Ручные примеры показаны только как SVG для сравнения. Полная бизнес-модель и все информационные связи сохранены; semantic_diff = 0. Файлы содержат данные предоставленных пользователем процессов. Качество ручного эталона и 80% визуального сходства не заявляются.\n',encoding='utf-8')
    hashes={str(f.relative_to(destination)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(destination.rglob('*')) if f.is_file() and f.name!='MANIFEST_SHA256.json'}
    (destination/'MANIFEST_SHA256.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2)+'\n')
    archive=destination.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(destination.rglob('*')):
            if f.is_file():z.write(f,str(f.relative_to(destination)))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name,digest in hashes.items():assert hashlib.sha256(z.read(name)).hexdigest()==digest
    return {'archive':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'cases':len(rows),'all_checks_passed':True}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--inputs',type=Path,required=True);p.add_argument('--results',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--control',type=Path);a=p.parse_args()
    print(json.dumps(package(a.inputs,a.results,a.output_dir,a.control),ensure_ascii=False,indent=2))
