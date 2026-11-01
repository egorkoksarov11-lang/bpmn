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
