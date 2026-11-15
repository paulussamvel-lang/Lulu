"""Palette changes persist and recolor the existing editor without losing work."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import config
from src.appearance import PALETTES
from src.config import AppConfig
from src.ui import theme as T
from tests.test_agent_workspace_shell import WorkspaceShellTests


def contrast(a, b):
    def luminance(value):
        rgb=[int(value[i:i+2],16)/255 for i in (1,3,5)]
        rgb=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb]
        return sum(v*w for v,w in zip(rgb,(.2126,.7152,.0722)))
    x,y=sorted((luminance(a),luminance(b)))
    return (y+.05)/(x+.05)


class PalettePersistenceTests(unittest.TestCase):
    def test_all_palettes_survive_save_and_load(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config,'_CONFIG_PATH',Path(directory)/'config.json'):
            for name in ['warm',*PALETTES]:
                cfg=AppConfig(theme=name)
                self.assertTrue(cfg.save())
                self.assertEqual(AppConfig.load().theme,name)
            self.assertEqual(AppConfig(theme='unknown').theme,'warm')

    def test_reading_action_and_rail_contrast(self):
        for name,p in PALETTES.items():
            for background,foreground in [('canvas','ink'),('surface','muted'),('alt','muted'),('accent','surface'),('rail','rail_text'),('rail_active','rail_text'),('rail','rail_muted')]:
                with self.subTest(name=name,pair=(background,foreground)):
                    self.assertGreaterEqual(contrast(p[background],p[foreground]),4.5)


class LivePaletteTests(WorkspaceShellTests):
    # Reuse only fixture methods: keep this test independent from inherited tests.
    def test_live_switch_preserves_document_prompt_and_page(self):
        from PySide6.QtWebEngineWidgets import QWebEngineView
        page=self.widget.page
        self.js("document.getElementById('prompt').value='尚未发送的草稿';void 0")
        output=Path(__file__).resolve().parents[2]/'scratch/palettes'
        output.mkdir(parents=True,exist_ok=True)
        try:
            for name,p in PALETTES.items():
                self.window.cfg.theme=name
                self.window._sync_preferences_to_workbench('theme')
                self.until(lambda:self.js('document.documentElement.dataset.workbenchPalette')==name)
                self.assertIs(self.widget.page,page)
                self.assertEqual(self.js('window.lulu.state.doc.id'),self.eid)
                self.assertEqual(self.js("document.getElementById('prompt').value"),'尚未发送的草稿')
                self.assertEqual(self.js("getComputedStyle(document.body).backgroundColor"),'rgb('+', '.join(str(int(p['canvas'][i:i+2],16)) for i in (1,3,5))+')')
                for width,height in [(1440,900),(1180,760)]:
                    self.window.resize(width,height)
                    for _ in range(6):self.tick()
                    self.window.grab().save(str(output/f'{name}-{width}.png'))
            self.window._switch_page(6)
            settings=self.window.stack.currentWidget()
            self.until(lambda:settings.approved.bridge.is_ready)
            settings.set_category('general')
            values=[]
            settings.approved.page().runJavaScript("JSON.stringify(Array.from(document.querySelectorAll('[data-pref=theme] option')).map(x=>x.value))",values.append)
            self.until(lambda:bool(values))
            self.assertEqual(json.loads(values[0]),[*PALETTES,'warm'])
            changes=[]
            settings.preferences_changed.connect(changes.append)
            with patch.object(settings.cfg,'save',return_value=False):
                settings._preference(lambda *a,**kw:None,key='theme',value='sky')
            self.assertEqual(settings.cfg.theme,'blush')
            self.assertEqual(changes,[])
            with self.assertRaises(ValueError):settings._preference(lambda *a,**kw:None,key='theme',value='invalid')
            settings._preference(lambda *a,**kw:None,key='theme',value='forest')
            self.assertEqual(changes,['theme'])
            self.assertEqual(T.ACTIVE.name,'forest')
            values=[]
            settings.approved.page().runJavaScript('document.documentElement.dataset.workbenchPalette',values.append)
            self.until(lambda:bool(values))
            self.assertEqual(values[0],'forest')
            for _ in range(6):self.tick()
            self.window.grab().save(str(output/'settings-forest.png'))
        finally:
            self.window._apply_workbench_theme('warm')


# Imported fixtures are not additional tests in this module.
for _name in dir(WorkspaceShellTests):
    if _name.startswith('test_'):
        setattr(LivePaletteTests,_name,None)
del WorkspaceShellTests
