"""Shared, deterministic pixel-measured text layout for DI, validation and SVG."""
from functools import lru_cache
from pathlib import Path
from PIL import ImageFont
FONT=Path(__file__).parent/'assets/OpenSans-Regular.ttf'

@lru_cache(None)
def font(size=14):return ImageFont.truetype(str(FONT),size)

def width(text,size=14):return font(size).getlength(text)

def wrap(text,max_width,size=14):
    lines=[]
    for paragraph in str(text).split('\n'):
        current=''
        for word in paragraph.split():
            if width(word,size)>max_width:
                if current:lines.append(current);current=''
                chunk=''
                for ch in word:
                    if chunk and width(chunk+ch,size)>max_width:lines.append(chunk);chunk=''
                    chunk+=ch
                current=chunk
            elif current and width(current+' '+word,size)>max_width:lines.append(current);current=word
            else:current=(current+' '+word).strip()
        lines.append(current)
    return lines or ['']

def text_box(text,max_width=210,size=14,padding=12):
    lines=wrap(text,max_width,size)
    return max(width(line,size) for line in lines)+padding*2,len(lines)*(size+5)+padding*2

def fits(text,box,size=14,padding=12):
    lines=wrap(text,max(1,box[2]-padding*2),size)
    return all(width(line,size)<=box[2]-padding*2+.01 for line in lines) and len(lines)*(size+5)<=box[3]-padding*2+.01

TASK_FONT=13
TASK_LINE_HEIGHT=18


def balanced_wrap(text,max_width,size):
    """Use the minimum line count, then balance word breaks; keep every word."""
    from functools import lru_cache
    result=[]
    for paragraph in str(text).split('\n'):
        words=paragraph.split();greedy=wrap(paragraph,max_width,size)
        if len(words)>60 or any(width(w,size)>max_width for w in words):result.extend(greedy);continue
        count=len(greedy)
        @lru_cache(None)
        def solve(start,remaining):
            if start==len(words):return (0,()) if remaining==0 else (float('inf'),())
            if remaining<=0:return float('inf'),()
            best=(float('inf'),())
            for end in range(start+1,len(words)+1):
                line=' '.join(words[start:end]);length=width(line,size)
                if length>max_width:break
                tail,lines=solve(end,remaining-1)
                cost=((max_width-length)/max_width)**2*(.4 if remaining==1 else 1)
                if remaining==1 and end-start==1 and len(words)>2:cost+=.25
                if cost+tail<best[0]:best=(cost+tail,(line,)+lines)
            return best
        value,lines=solve(0,count)
        result.extend(lines if value<float('inf') else greedy)
    return result or ['']


@lru_cache(maxsize=8192)
def text_layout(text,w,h,sizes,padding_x,padding_y,marker=0):
    """Fit the measured ink bounds, rather than a nominal line-height estimate."""
    for size in sizes:
        # Prefer a smaller readable font to splitting an otherwise ordinary
        # word across lines (e.g. «Лист-заверитель» / «ь дела»).
        if size!=sizes[-1] and any(width(word,size)>max(1,w-2*padding_x) for word in str(text).split()):continue
        lines=balanced_wrap(text,max(1,w-2*padding_x),size)
        bounds=[font(size).getbbox(line or ' ',anchor='ls') for line in lines]
        lineh=max(size+2,max(b[3]-b[1] for b in bounds)+1)
        top=min(i*lineh+b[1] for i,b in enumerate(bounds));bottom=max(i*lineh+b[3] for i,b in enumerate(bounds));ink=bottom-top
        fit=ink<=h-2*padding_y-marker+.01 and all(width(line,size)<=w-2*padding_x+.01 for line in lines)
        result={'lines':lines,'font_size':size,'line_height':lineh,'ink_height':ink,
                'baselines':[(h-marker-ink)/2-top+i*lineh for i in range(len(lines))],
                'fits':fit,'required_height':ink+2*padding_y+marker}
        if fit:return result
    return result


def task_layout(text,box,kind='task'):
    return text_layout(text,box[2],box[3],(13,12,11,10),6,6,14 if kind in ('callActivity','subProcess') else 0)


def label_layout(text,box):
    return text_layout(text,box[2],box[3],(12,11,10),2,1)


def task_fits(text,box,kind='task'):
    return task_layout(text,box,kind)['fits']
