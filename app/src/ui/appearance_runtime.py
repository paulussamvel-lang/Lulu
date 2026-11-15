"""Switch colors in-place without recreating pages, drafts, players or workers."""
from __future__ import annotations
from dataclasses import fields
import json
import re
import weakref

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QWidget
from shiboken6 import isValid

from ..appearance import PALETTES, normalize_theme
from . import theme as T, icons


def web_theme_script(name):
    name=normalize_theme(name)
    if name not in PALETTES:
        return "document.getElementById('paul-workbench-colors')?.remove(); delete document.documentElement.dataset.workbenchPalette;"
    p=PALETTES[name]
    variables={
        'bg':p['canvas'],'base':p['canvas'],'canvas':p['canvas'],'paper':p['surface'],
        'surface':p['surface'],'panel':p['alt'],'nav':p['alt'],'rail':p['alt'],
        'ink':p['ink'],'text':p['ink'],'muted':p['muted'],'secondary':p['muted'],'faint':p['muted'],
        'line':p['line'],'line-soft':p['alt'],'soft-line':p['line'],
        'accent':p['accent'],'blue':p['accent'],'blue-dark':p['hover'],'accent-hover':p['hover'],
        'accent-wash':p['alt'],'blue-wash':p['alt'],'wash':p['alt'],'tint':p['alt'],
        'selected':p['alt'],'chip':p['alt'],'hover':p['alt'],'soft':p['canvas'],
        'manuscript-selection':p['selection'],'manuscript-selection-line':p['accent'],
        'manuscript-marker':p['accent'],'manuscript-check':p['accent'],
        'table-header':p['alt'],'green':'#356B48','good':'#356B48','red':'#9B3B42','danger':'#9B3B42',
        'paper-strength':'0',
        'serif':'"PingFang SC", -apple-system, sans-serif',
    }
    declarations=';'.join(f'--{key}:{value}!important' for key,value in variables.items())
    css=f''':root{{{declarations}}}
html[data-workbench-palette],html[data-workbench-palette] body{{background:{p['canvas']}!important;color:{p['ink']}!important;caret-color:{p['accent']}}}
html[data-workbench-palette] body::before{{display:none!important}}
html[data-workbench-palette] .app::after{{display:none!important}}
::selection{{background:{p['alt']};color:{p['ink']}}}
.select-trigger,.select-menu,.control-select{{background:{p['surface']}!important;color:{p['ink']}!important;border-color:{p['muted']}!important}}
.select-option-title,.select-value{{color:inherit!important}}
.select-option-description{{color:{p['muted']}!important}}
.select-option[aria-selected=true],.select-option.is-active{{background:{p['alt']}!important;color:{p['accent']}!important}}
:focus-visible{{outline-color:{p['accent']}!important}}
::-webkit-scrollbar-thumb{{background:{p['muted']};border:3px solid {p['surface']};border-radius:8px}}
.settings-shell .sidebar,.settings-app .sidebar,.app>.sidebar{{background:{p['alt']}!important;color:{p['ink']}!important}}
html[data-workbench-palette] .setting-group,html[data-workbench-palette] .group-card,html[data-workbench-palette] dialog{{background:{p['surface']}!important;border-color:{p['line']}!important}}
html[data-workbench-palette] #app #list .entry.selected{{background:{p['selection']}!important;border-color:{p['accent']}!important;color:{p['selection_ink']}!important}}
html[data-workbench-palette] #app #list .entry.selected *{{color:{p['selection_ink']}!important}}
html[data-workbench-palette] #app :is(#export,#batch-export,#audio-export){{color:{p['accent']}!important;background:{p['alt']}!important}}
.settings-shell,.app,.workspace{{color:{p['ink']}}}
'''
    return """(()=>{if(!document.head)return;document.documentElement.dataset.workbenchPalette=NAME;
let style=document.getElementById('paul-workbench-colors');if(!style){style=document.createElement('style');style.id='paul-workbench-colors';document.head.append(style)}style.textContent=CSS;})();""".replace('NAME',json.dumps(name)).replace('CSS',json.dumps(css))


def bind_web_theme(view, name):
    view._paul_palette_name=normalize_theme(name)
    if not getattr(view,'_paul_palette_bound',False):
        original=view.page().backgroundColor()
        view._paul_background=original
        ref=weakref.ref(view)
        def loaded(ok):
            target=ref()
            if ok and target is not None and isValid(target):
                apply_web_theme(target)
        view.loadFinished.connect(loaded)
        view._paul_palette_bound=True
    apply_web_theme(view)


def apply_web_theme(view):
    name=view._paul_palette_name
    if name in PALETTES:
        view.page().setBackgroundColor(QColor(PALETTES[name]['canvas']))
    elif getattr(view,'_paul_was_themed',False):
        view.page().setBackgroundColor(view._paul_background)
    if name in PALETTES or getattr(view,'_paul_was_themed',False):
        view.page().runJavaScript(web_theme_script(name))
    view._paul_was_themed=name in PALETTES


def color_mapping(previous, current):
    old_c,new_c=T.consumer_theme(previous.name),T.consumer_theme(current.name)
    result={}
    for old,new in [(previous,current),(old_c,new_c)]:
        for field in fields(old):
            a,b=getattr(old,field.name),getattr(new,field.name)
            if isinstance(a,str) and a and isinstance(b,str) and b and (a.startswith('#') or a.startswith('rgba(')):
                result[a.lower()]=b
    return result


def apply_native_theme(window, previous, current):
    mapping=color_mapping(previous,current)
    expression=re.compile('|'.join(re.escape(k) for k in sorted(mapping,key=len,reverse=True)),re.I)
    recolor=lambda value:expression.sub(lambda match:mapping[match[0].lower()],value)
    c=T.consumer_theme(current.name)
    for widget in [window,*window.findChildren(QWidget)]:
        if not isValid(widget):continue
        if widget is not window and widget.styleSheet():
            widget.setStyleSheet(recolor(widget.styleSheet()))
        for attribute in ['_consumer','consumer','_theme','theme']:
            if isinstance(getattr(widget,attribute,None),T.ConsumerTheme):setattr(widget,attribute,c)
        for attribute in ['_consumer_theme_name','consumer_theme_name','_theme_name']:
            if getattr(widget,attribute,None)==previous.name:setattr(widget,attribute,current.name)
        for attribute in ['_lulu_base_text_style','_lulu_scaled_text_style']:
            value=getattr(widget,attribute,None)
            if isinstance(value,str):setattr(widget,attribute,recolor(value))
        font=widget.property('luluFontStyle')
        if isinstance(font,list):widget.setProperty('luluFontStyle',[recolor(s) if isinstance(s,str) else s for s in font])
        in_sidebar=False;parent=widget
        while parent is not None:
            if parent.objectName()=='sidebar':in_sidebar=True;break
            parent=parent.parentWidget()
        icon=getattr(widget,'_paul_icon',None)
        if icon:
            name,color,size,stroke=icon;color=recolor(color)
            if in_sidebar:color=c.rail_foreground or c.ink_soft
            widget.setPixmap(icons.pixmap(name,color,size,stroke));widget._paul_icon=(name,color,size,stroke)
        if in_sidebar and isinstance(widget,QLabel) and widget.styleSheet():
            color=c.rail_foreground or c.ink_soft
            widget.setStyleSheet(re.sub(r'(?<![-\w])color\s*:[^;]+',f'color:{color}',widget.styleSheet()))
        if hasattr(widget,'set_paper_texture_strength'):
            if not hasattr(widget,'_paul_texture_strength'):widget._paul_texture_strength=widget.property('paperTextureStrength') or 0.
            widget.set_paper_texture_strength(0. if current.name in PALETTES else widget._paul_texture_strength)
            if widget.property('paperBaseColor'):
                base=c.rail_background if in_sidebar and c.rail_background else c.canvas
                widget.set_paper_base_color(base)
        widget.update()
