"""Exercise real Qt input/rendering behavior without a live model or painting."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['KRITA_CREATIVE_NO_AUTOSTART'] = '1'
# Files the panel writes (pasted references) go to a private folder removed on exit.
import atexit, shutil, tempfile
tempfile.tempdir = tempfile.mkdtemp(prefix='creative-ui-smoke-')
atexit.register(shutil.rmtree, tempfile.tempdir, True)
root = Path(__file__).resolve().parents[1]
module_path = root.parent / 'krita-mcp/krita-plugin/kritamcp/creative_docker.py'
# Qt comes from the plugin's qt_compat, so this runs under PyQt5 or PyQt6 as the plugin does.
package = types.ModuleType('creative_ui_test'); package.__path__ = [str(module_path.parent)]; sys.modules['creative_ui_test'] = package
from creative_ui_test.qt_compat import (QT6, QApplication, QDockWidget, QTabWidget, QLabel, QStyle, QStyleOptionComboBox,
                                        QProcess, Qt, QMimeData, QTimer, QLineEdit, QTextDocument, QTextCursor, QImage, QColor, QPixmap)
QTest = importlib.import_module(('PyQt6' if QT6 else 'PyQt5') + '.QtTest').QTest
stub = types.ModuleType('krita'); stub.DockWidget = QDockWidget
stub.DockWidgetFactory = object; stub.DockWidgetFactoryBase = types.SimpleNamespace(DockRight=0)
active_document = [None]                            # the document Krita reports as active; set before a canvas is attached
stub.Krita = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(activeDocument=lambda: active_document[0]))
stub.Selection = object                             # protection.py imports it; the panel checks use a fake
sys.modules['krita'] = stub
spec = importlib.util.spec_from_file_location('creative_ui_test.creative_docker', module_path)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
identity_module = sys.modules['creative_ui_test.creative_document_identity']
app = QApplication([])
panel = module.CreativeAgentDocker(); panel.resize(440, 820); panel.show()
assert panel.source.currentData() == 'current', 'startup without a document must not imply a request for a new painting'
# The warning about an old plugin copy in the profile: hidden when nothing happened, plain text (no dialog) when something did.
assert panel.profile_notice.textFormat() == Qt.TextFormat.PlainText
assert panel.profile_notice.isHidden() and panel.refresh_profile_notice() == [], 'no profile copy found: no warning'
_profile = Path(tempfile.mkdtemp(prefix='creative-ui-profile-'))
(_profile / 'krita' / 'pykrita-shadowed-2026-10-20' / 'kritamcp').mkdir(parents=True)
(_profile / 'krita' / 'pykrita-shadowed-2026-10-20' / 'kritamcp' / 'build-info.json').write_text(json.dumps({'build_id': 'ec6fec2c' + '0' * 56}))
panel.app_data = lambda: _profile
_lines = panel.refresh_profile_notice()
assert not panel.profile_notice.isHidden() and 'ec6fec2c0000' in panel.profile_notice.text() and 'not deleted' in panel.profile_notice.text(), _lines
shutil.rmtree(_profile, True); del panel.app_data
assert panel.refresh_profile_notice() == [] and panel.profile_notice.isHidden()
def settle():
    for _ in range(8): app.processEvents()
commands = []
panel.process = types.SimpleNamespace(state=lambda: QProcess.ProcessState.Running, write=lambda data: commands.append(json.loads(data)))
panel.handle_event({'type':'ready','models':[{'provider':'openrouter','id':'deepseek/deepseek-v4.1-flash','name':'DeepSeek V4.1 Flash','configured':True}], 'bridge':{}, 'build':{'version':'1.0.0','build_id':'test-build'}})
assert commands[-1] == {'type':'context','action':'inspect'}
# Nothing chosen yet (a fresh install): OpenRouter's Qwen3 VL is pre-selected when it is connected (the artist,
# 2026-10-24); a model the artist chose, or one the companion reports as selected, is never overridden.
_qwen = {'provider':'openrouter','id':'qwen/qwen3-vl-235b-a22b-instruct','name':'Qwen3 VL 235B','configured':True}
_deepseek = {'provider':'openrouter','id':'deepseek/deepseek-v4.1-flash','name':'DeepSeek V4.1 Flash','configured':True}
_direct = {'provider':'deepseek','id':'deepseek-flash','name':'DeepSeek Flash','configured':True}
def _fresh_panel(models, **extra):
    fresh = module.CreativeAgentDocker(); fresh.process = types.SimpleNamespace(state=lambda: QProcess.ProcessState.Running, write=lambda data: None)
    fresh.handle_event({'type':'ready','models':models,'bridge':{},'build':{'version':'1.0.0','build_id':'test-build'},**extra})
    selected = fresh.model.currentData(); fresh.deleteLater(); return selected
assert _fresh_panel([_direct, _deepseek, _qwen]) == {'provider':'openrouter','id':_qwen['id']}, 'fresh install: Qwen3 VL'
assert _fresh_panel([_direct, _deepseek, dict(_qwen, configured=False)]) != {'provider':'openrouter','id':_qwen['id']}, 'not connected: today\u2019s choice'
assert _fresh_panel([_direct, _deepseek, _qwen], selected={'provider':'deepseek','id':'deepseek-flash'}) == {'provider':'deepseek','id':'deepseek-flash'}, 'the artist\u2019s choice stays'
assert _fresh_panel([_direct, _deepseek]) == {'provider':'deepseek','id':'deepseek-flash'}, 'without it: today\u2019s behaviour (first connected provider)'
# A generated stand-in canvas, so the test runs on a fresh clone.
(root / 'output').mkdir(parents=True, exist_ok=True)
image_path = str(root / 'output' / 'ui-fixture-canvas.png')
fixture = QImage(384, 512, QImage.Format.Format_RGB32); fixture.fill(QColor('#7a2f2a'))
for y in range(160, 352):
    for x in range(48, 336): fixture.setPixelColor(x, y, QColor('#c4572f'))
assert fixture.save(image_path), 'fixture canvas could not be written'
canvas = {'document_id':'open-painting','name':'DeepSeek — first color-field study','filename':str(root.parent / 'painting.kra'), 'modified':True,
          'width':768,'height':1024,'revision':'r1','content_id':'sha256-one','captured_at':'2026-09-11T10:00:00Z','path':image_path}
active_document[0] = types.SimpleNamespace(fileName=lambda: canvas['filename'], modified=lambda: True)
panel.handle_event({'type':'context','selected':True,'follow_active':True,'state':'fresh','canvas':canvas})
assert 'painting.kra' in panel.canvas_button.text()
assert canvas['name'] not in panel.canvas_button.text() and canvas['name'] in panel.canvas_button.toolTip()
assert module.canvas_name({'name':'Untitled study','filename':''}) == 'Untitled study'
# A newly created Ask session is observation context, not a proposed painting target.
panel.painting_target={'document_id':'open-painting','filename':None,'name':'Creative painting','mode':'new','bound':False}
panel.goal={'status':'draft','brief':None,'approved_revision':None}
panel.render_target()
assert panel.workspace_label.text()=='Canvas · painting.kra' and not panel.return_button.isVisible()
panel.goal=None; panel.painting_target={}
panel.prompt.setPlainText('Do you see this painting?')
QTest.keyClick(panel.prompt, Qt.Key.Key_Return)
assert commands[-1]['canvas']['document_id'] == 'open-painting'
assert commands[-1]['canvas']['selected'] is True
assert commands[-1]['chat_mode'] == 'ask'
assert commands[-1]['mode'] == 'current', 'opening a canvas after dock startup must use that canvas'
message_id = commands[-1]['message_id']
panel.handle_event({'type':'message_context','message_id':message_id,'status':'included','canvas':canvas})
assert panel.last_user_item['receipt']['content_id'] == 'sha256-one'
receipt_button=panel.last_user_item['layout'].itemAt(1).widget()
assert receipt_button.text()=='▧  painting.kra · included' and canvas['name'] in receipt_button.toolTip()
name_preview=module.ImagePreview(panel,canvas)
details=[label.text() for label in name_preview.findChildren(QLabel) if 'Document title:' in label.text()]
assert len(details)==1 and details[0].startswith('painting.kra') and canvas['name'] in details[0]
name_preview.close()
panel.handle_event({'type':'text','text':'I can see two red color fields on a warm, pale ground. '})
panel.flush_stream(); settle()
item = panel.current_reply
cursor = item['label'].textCursor(); cursor.setPosition(10); cursor.setPosition(30, QTextCursor.MoveMode.KeepAnchor); item['label'].setTextCursor(cursor)
selected_text = cursor.selectedText()
for chunk in ['The upper field ', 'has dry marks at the left, ', 'and a softer finish elsewhere.']:
    panel.handle_event({'type':'text','text':chunk}); panel.flush_stream(); settle()
assert item['label'].textCursor().selectedText() == selected_text, 'streaming must preserve text selection'
panel.handle_event({'type':'message_end'})
assert panel.transcript.toPlainText().count('Creative Agent') == 1, 'stream chunks update one reply'
panel.canvas_remove.click()
assert commands[-1] == {'type':'context','action':'detach'}
panel.handle_event({'type':'context','selected':False,'follow_active':True,'state':'detached','canvas':canvas})
panel.canvasChanged(None); settle()
assert panel.canvas_context['selected'] is False
panel.prompt.setPlainText('What does scumble mean?'); panel.submit()
assert commands[-1]['canvas']['selected'] is False, 'detached canvas must remain excluded'
panel.handle_event({'type':'context','selected':True,'follow_active':True,'state':'fresh','canvas':canvas})
panel.handle_event({'type':'study','id':'test','directory':'/tmp'})
panel.handle_event({'type':'busy','busy':True})
assert panel.stop_button.isEnabled() and not panel.source.isEnabled()
assert panel.prompt.isEnabled(), 'direction can be typed while generating'
panel.stop_button.click(); assert commands[-1] == {'type':'stop'}
panel.handle_event({'type':'busy','busy':False})
assert panel.model.isEnabled(), 'compatible model changes do not require new chat'
panel.handle_event({'type':'canvas','path':image_path,'checkpoint':str(root.parent / 'painting.kra')})
assert 'painting.kra' in panel.save_status.text()
rendered = QTextDocument(); rendered.setHtml(panel.transcript.render('## Stage One: Material\n\n- Keep the red coat\n- Preserve the pose\n\n**Dry texture**'))
assert '##' not in rendered.toPlainText() and '<h2' in rendered.toHtml()
assert '<img' not in panel.transcript.render('![untrusted](https://example.com/image.png)')
goal = {'version':1,'status':'ready','mode':'plan','revision':1,'brief':{
    'title':'Stage One: Material','objective':'Give the upper field a dry, chalky surface.',
    'requirements':['Keep composition, color and outer edges unchanged.','Work only on the upper field.'],
    'characters':[{'name':'Mara','requirements':['Red coat','Curly hair']}],
    'freedom':['Choose the dry brush after calibration.'],
    'steps':[{'title':'Calibrate the brush','done_when':'Broken granular marks without stripes.','scope':'Upper field only','region':[100,150,580,330],'stop_after':True,'max_operations':4}],
    'completion':['Dry breakup at 100%.','No new stripes.']},
    'limits':{'minutes':20,'passes':30},'passes':0,'tokens':0,'reviews':[],
    'question':{'id':'texture','question':'How matte should it look?','options':['Whisper-light tooth','Visibly chalky']}}
panel.handle_event({'type':'goal','goal':goal,'mode':'plan','references':[]})
panel.handle_event({'type':'question',**goal['question']})
assert panel.mode_selector.currentData() == 'plan' and panel.tabs.isTabVisible(panel.plan_tab) and not panel.plan_bar.isHidden()
panel.question_controls[-1].click()
assert commands[-1]['text'] == 'You decide' and commands[-1]['chat_mode'] == 'plan'
dialog = module.PlanDialog(panel, goal)
# A saved plan's retired stage controls (region, stop_after, max_operations) are dropped: steps are only an order.
legacy_free = dict(goal['brief'], steps=[{'title':'Calibrate the brush','done_when':'Broken granular marks without stripes.','scope':'Upper field only'}])
assert dialog.brief() == legacy_free, (dialog.brief(), legacy_free)
assert not hasattr(dialog, 'stage_stop') and not hasattr(dialog, 'stage_region') and not hasattr(dialog, 'stage_operations')
dialog.stage_scope.setText('Upper field core only'); dialog.rules.appendPlainText('Keep the lower field untouched.')
assert dialog.brief()['steps'][0] == {'title':'Calibrate the brush','done_when':'Broken granular marks without stripes.','scope':'Upper field core only'}
assert dialog.brief()['requirements'][-1] == 'Keep the lower field untouched.'
assert dialog.brief()['characters'] == goal['brief']['characters']
dialog.close()
legacy_goal = json.loads(json.dumps(goal)); legacy_goal['brief']['steps'] = [{'title':'Study','done_when':'Texture improves'}]
legacy_dialog = module.PlanDialog(panel, legacy_goal)
assert 'scope' not in legacy_dialog.brief()['steps'][0], 'optional blank scope must not invalidate a legacy plan'
legacy_dialog.close()
# The open chat's AI image allowance: shown and changed in the panel in every mode, and in the plan dialog.
assert panel.ai_images_selector.isVisible() and panel.ai_images_selector.currentData() == 0, 'a chat saved without an allowance shows none'
panel.ai_images_selector.setCurrentIndex(panel.ai_images_selector.findData(1))
assert commands[-1] == {'type':'set_limits','limits':{'minutes':20,'passes':30,'ai_images':1}}, commands[-1]
agent_goal = dict(goal, brief=None, question=None, limits={'minutes':0,'passes':0,'ai_images':3}, ai_images_used=1)
panel.handle_event({'type':'goal','goal':agent_goal,'mode':'agent','references':[]})
assert not panel.tabs.isTabVisible(panel.plan_tab) and panel.ai_images_selector.isVisible(), 'an Agent chat with no plan still shows it'
assert panel.ai_images_selector.currentData() == 3 and panel.ai_images_used.text() == '1 used'
panel.ai_images_selector.setCurrentIndex(panel.ai_images_selector.findData(-1))
assert commands[-1]['type'] == 'set_limits' and commands[-1]['limits']['ai_images'] is None, 'no limit is sent as null'
panel.handle_event({'type':'goal','goal':dict(agent_goal, limits={'minutes':0,'passes':0,'ai_images':7}),'mode':'agent','references':[]})
assert panel.ai_images_selector.currentData() == 7, 'a value set in the plan dialog is shown'
panel.handle_event({'type':'busy','busy':True})
assert not panel.ai_images_selector.isEnabled() and 'Pause' in panel.ai_images_selector.toolTip(), 'disabled while painting'
panel.handle_event({'type':'busy','busy':False})
# Protected areas: a button opens the panel; the agent's proposal waits for Keep, Adjust or Discard; hits are chat lines.
class FakeProtection:
    def __init__(self):
        self.calls = []
        self.areas = [{'id': 'm1', 'name': 'Woman and car', 'state': 'active', 'by': 'agent', 'bounds': [0, 0, 10, 10]},
                      {'id': 'locked-layers', 'name': 'Locked layers', 'state': 'active', 'by': 'automatic', 'count': 2}]
    def _protect_list(self, doc): return list(self.areas)
    def _protect_set_state(self, doc, area_id, state): self.calls.append(('state', area_id, state))
    def _protect_remove(self, doc, area_id): self.calls.append(('remove', area_id))
protection = FakeProtection(); panel.protection = protection; panel.protection_document = lambda: object()
assert panel.protect_button.isVisible() and panel.protect_button.accessibleName() == 'Protected areas'
areas = panel.open_protection(modal=False)
assert [row['name'] for row in areas.rows] == ['Woman and car', 'Locked layers']
assert areas.rows[0]['detail'] == 'made by the agent · you approved' and areas.rows[1]['detail'] == '2 layers · never edited by the agent, but it may paint over them'
assert areas.rows[1]['remove'] is None, 'locked layers are unlocked in Krita, not removed here'
assert [b.text() for b in areas.actions] == ['Ask the agent…', 'Paint over it', 'Use my selection']
areas.rows[0]['remove'].click(); assert protection.calls[-1] == ('remove', 'm1')
areas.close()
panel.handle_event({'type':'protection_proposed','area':{'id':'m2','name':'Sky','state':'pending','by':'agent','bounds':[0,0,5,5]}})
assert "I marked 'Sky' in red. Keep this protection?" in panel.transcript.toPlainText()
assert [b.text() for b in panel.protection_controls] == ['Keep', 'Adjust', 'Discard']
panel.protection_controls[0].click(); assert protection.calls[-1] == ('state', 'm2', 'active')
assert not any(b.isEnabled() for b in panel.protection_controls), 'answered once'
panel.handle_event({'type':'protection_proposed','area':{'id':'m3','name':'River','state':'pending','by':'agent','bounds':[0,0,5,5]}})
panel.protection_controls[2].click(); assert protection.calls[-1] == ('remove', 'm3')
panel.handle_event({'type':'protection_hit','message':"Move 1 reached into 'Sky'. I kept it untouched (about 40% of it was in the way)."})
assert "Move 1 reached into 'Sky'" in panel.transcript.toPlainText()
panel.handle_event({'type':'busy','busy':True})
assert not panel.protect_button.isEnabled() and panel.protect_button.toolTip() == 'Pause to change protection'
panel.handle_event({'type':'busy','busy':False}); assert panel.protect_button.isEnabled()
# Paint over it unlocks the protection group while it lasts (Krita will not paint a mask in a locked group).
class EditDocument:
    def __init__(self): self.active = 'painting-layer'
    def activeNode(self): return self.active
    def setActiveNode(self, node): self.active = node
class EditMask:
    def selection(self): return types.SimpleNamespace(duplicate=lambda: 'saved')
    def setSelection(self, value): self.restored = value
edit_mask, edit_document = EditMask(), EditDocument()
protection._protect_mask_node = lambda doc, area_id: edit_mask
protection._protect_editing = lambda doc, on: protection.calls.append(('editing', on))
panel.protection_document = lambda: edit_document
before_edit_krita = module.Krita
module.Krita = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(action=lambda name: None, activeDocument=lambda: edit_document))
panel.paint_protection({'id': 'm1', 'name': 'Woman and car'})
assert protection.calls[-1] == ('editing', True) and edit_document.active is edit_mask and panel.protection_bar.isVisible()
panel.finish_protection(False)
assert protection.calls[-1] == ('editing', False) and edit_mask.restored == 'saved' and edit_document.active == 'painting-layer'
module.Krita = before_edit_krita
unlimited = module.PlanDialog(panel, dict(goal, limits={'minutes':20,'passes':30,'ai_images':None}))
assert unlimited.ai_images.value() == -1 and unlimited.ai_images.text() == 'No AI image limit'; unlimited.close()
panel.handle_event({'type':'goal','goal':goal,'mode':'plan','references':[]})
assert panel.execute_button.isHidden(), 'answer required before starting a pending plan'
goal['question'] = None
panel.handle_event({'type':'goal','goal':goal,'mode':'plan','references':[]})
panel.execute_button.click(); assert commands[-1]['start_plan'] is True
assert panel.mode_selector.currentData() == 'agent', 'Paint this plan paints in Agent mode, one move per step'
panel.mode_selector.setCurrentIndex(1)
panel.transcript.clear(); panel.empty_state.hide()
panel.last_user_item = panel.transcript.add_message('You','Give the upper field a little more dry texture. Keep its color and shape.')
panel.transcript.add_receipt(panel.last_user_item, canvas)
panel.transcript.add_message('Creative Agent','## Stage One: Material\n\nI’ll test the brushes first, then work on the upper field only.\n\n- Preserve the red palette and outer edges\n- Use uneven, broken marks\n- Stop if new stripes appear')
panel.transcript.add_message('Activity','Inspected canvas · includes unsaved changes',True)
goal['question'] = {'id':'qa-texture','question':'How matte should the surface look?','options':['Whisper-light tooth','Visibly chalky']}
panel.handle_event({'type':'goal','goal':goal,'mode':'plan','references':[]})
panel.transcript.add_question('How matte should the surface look?',['Whisper-light tooth','Visibly chalky'],lambda _:None)
panel.handle_event({'type':'status','phase':'needs_input','message':'Waiting for your preference'})
output = root / 'output' / 'ui-review'; output.mkdir(parents=True, exist_ok=True)
for dark in (True,False):
    panel.apply_theme(dark)
    for width,height in ((360,640),(440,820),(600,900)):
        panel.resize(width,height); settle(); panel.transcript.jump_to_latest(); settle()
        assert panel.width() == width, 'panel must respect narrow size'
        assert panel.transcript.horizontalScrollBar().maximum() == 0
        for control in (panel.prompt,panel.send_button,panel.mode_selector,panel.model,panel.canvas_button):
            assert control.width() > 15
            point = control.mapTo(panel, control.rect().bottomRight())
            assert point.x() <= panel.width() and point.y() <= panel.height(), 'important control clipped: '+str(control.objectName())
        for message in panel.transcript.messages:
            if message['label'].isVisible(): assert message['label'].geometry().bottom() < message['card'].height(), 'message body clipped'
        panel.grab().save(str(output / ('panel-%s-%s.png' % ('dark' if dark else 'light',width))))
# Visually review complete empty, paragraph, streaming, error and dialog states.
panel.apply_theme(True); panel.resize(440, 820)
panel.transcript.clear(); panel.plan_bar.hide(); panel.empty_state.show(); panel.status.setText('Ready'); settle()
panel.grab().save(str(output / 'state-empty-dark.png'))
panel.empty_state.hide()
panel.transcript.add_message('You', 'Do you see the painting? What would you work on next?')
paragraph = panel.transcript.add_message('Creative Agent', 'I can see two red fields against a warm, pale ground. The upper field carries a brighter orange-red glow, while the lower field is deeper and quieter. Their proportions and the narrow gap already hold together.\n\nThe next useful change is surface texture. At the moment the soft gradients dominate; a few irregular, dry marks could add the feeling of pigment catching on canvas without changing the color or silhouette.\n\nI would test that on a separate layer in the upper field first, inspect it at full size, and stop before touching the lower field.')
settle(); panel.transcript.jump_to_latest(); settle(); panel.grab().save(str(output / 'state-paragraph-dark.png'))
panel.handle_event({'type':'busy','busy':True}); panel.handle_event({'type':'status','phase':'thinking','message':'Considering the surface and protected edges…'})
panel.handle_event({'type':'text','text':'A restrained first pass would use '}); panel.flush_stream(); settle()
panel.grab().save(str(output / 'state-streaming-dark.png'))
panel.handle_event({'type':'busy','busy':False}); panel.handle_event({'type':'message_end'})
panel.handle_event({'type':'context','selected':True,'follow_active':True,'state':'error','canvas':canvas,'error':'The current canvas could not be captured.'})
panel.handle_event({'type':'error','message':'The canvas snapshot could not be prepared. Your painting is unchanged.'})
settle(); panel.grab().save(str(output / 'state-error-dark.png'))
assert panel.recovery_button.isVisible() and panel.recovery_button.text() == 'Retry canvas'
panel.handle_event({'type':'context','selected':True,'follow_active':True,'state':'fresh','canvas':canvas})
assert not panel.recovery_button.isVisible()
# Selection offsets in Qt count UTF-16 units, including emoji before the selection.
unicode_reply = panel.transcript.add_message('Creative Agent','🎨 A red coat and a gentle expression. '); settle()
cursor = unicode_reply['label'].textCursor(); cursor.setPosition(7); cursor.setPosition(15,QTextCursor.MoveMode.KeepAnchor); unicode_reply['label'].setTextCursor(cursor)
unicode_selected = cursor.selectedText(); panel.transcript.append_to(unicode_reply,'Keep both as we continue.'); settle()
assert unicode_reply['label'].textCursor().selectedText() == unicode_selected
# Larger text must retain the composer controls inside a narrow panel.
panel.text_size.setValue(18); panel.resize(360, 820); settle()
for control in (panel.prompt,panel.send_button,panel.model,panel.mode_selector,panel.canvas_button):
    assert control.mapTo(panel, control.rect().bottomRight()).x() <= panel.width()
panel.grab().save(str(output / 'state-large-text-light.png'))
panel.text_size.setValue(14); panel.apply_theme(True); panel.resize(440,820)
history = module.HistoryDialog(panel)
history.set_items([{'id':'older-study','title':'Rothko · material study','filename':'painting.kra','status':'paused','thumbnail':image_path}])
# Chat records: sizes, delete (confirmed, never the open chat), export and import (storage-layout E).
history.set_items([{'id':'older-study','title':'Rothko · material study','filename':'painting.kra','status':'paused','thumbnail':image_path,'size_bytes':42_000_000}], 820_000_000)
assert '42 MB' in history.list.item(0).text() and '820 MB' in history.note.text()
history.list.setCurrentRow(0)
history.confirm = lambda title, text: False; sent = len(commands); history.delete_chat(); assert len(commands) == sent, 'cancelled delete sends nothing'
asked = []; history.confirm = lambda title, text: asked.append(text) or True; history.delete_chat()
assert commands[-1] == {'type':'delete_chat','id':'older-study'} and 'not touched' in asked[0]
panel.study_id, sent = 'older-study', len(commands); history.delete_chat(); assert len(commands) == sent and 'Close this chat' in history.note.text(); panel.study_id = None
history.choose_save = lambda title, name: '/tmp/' + name; history.export_chats()
assert commands[-1] == {'type':'export_archive','path':'/tmp/Rothko material study.creative-agent-archive','id':'older-study'}
history.choose_open = lambda title: '/tmp/in.creative-agent-archive'; history.import_archive()
assert commands[-1] == {'type':'import_archive','path':'/tmp/in.creative-agent-archive'}
history.set_items([], None, ''); assert 'Import' in history.note.text()
history.list.clearSelection(); history.list.setCurrentItem(None); history.export_chats(); assert commands[-1]['type'] == 'export_archive' and 'id' not in commands[-1]
history.set_items([{'id':'older-study','title':'Rothko · material study','filename':'painting.kra','status':'paused','thumbnail':image_path,'size_bytes':42_000_000}], 820_000_000)
history.list.setCurrentRow(0); history.show(); settle(); history.grab().save(str(output / 'dialog-history.png')); history.restore()
assert commands[-1] == {'type':'end'}, 'restoring safely ends the current idle chat first'
panel.handle_event({'type':'ended'}); assert commands[-1] == {'type':'resume','id':'older-study'}
panel.handle_event({'type':'study','id':'older-study','directory':'/tmp'})
goal['question'] = None
plan = module.PlanDialog(panel,goal); plan.show(); settle(); plan.grab().save(str(output / 'dialog-plan.png')); plan.close()
review = module.PassReviewDialog(panel)
review.set_passes([{'id':'stage:calibration','kind':'stage','title':'Brush calibration','before_path':image_path,'after_path':image_path,'strength':0.3,'visible':True,'review_actions':['reject']}])
assert not review.visible.isEnabled() and not review.strength.isEnabled() and review.reject_pass.isEnabled()
review.show(); settle(); review.grab().save(str(output / 'dialog-review.png')); review.close()
# Ambiguous outcomes require an explicit inspection and reconciliation click.
panel.handle_event({'type':'uncertain_operations','operations':['unknown-pass'],'message':'Inspect the last operation before continuing.'})
assert not panel.execute_button.isEnabled()
panel.recovery_button.click(); assert commands[-1] == {'type':'inspect_result'}
panel.handle_event({'type':'inspected_result'})
panel.recovery_button.click(); assert commands[-1] == {'type':'reconcile'}
panel.handle_event({'type':'reconciled'}); assert not panel.uncertain_operations
panel.handle_event({'type':'uncertain_operations','operations':[],'message':'Inspection acknowledged.'}); assert not panel.recovery_button.isVisible()
# Selected area is a rectangular observation crop, never painting authorization.
old_krita = module.Krita
selection = types.SimpleNamespace(x=lambda:-20,y=lambda:150,width=lambda:700,height=lambda:330)
readonly_document = types.SimpleNamespace(selection=lambda:selection,width=lambda:768,height=lambda:1024,
    rootNode=lambda:types.SimpleNamespace(uniqueId=lambda:types.SimpleNamespace(toString=lambda:'open-painting')))
module.Krita = types.SimpleNamespace(instance=lambda:types.SimpleNamespace(activeDocument=lambda:readonly_document))
identity_module.Krita=module.Krita
panel.attach_selected_area()
assert commands[-1] == {'type':'context','action':'region','region':{'document_id':module.document_id(readonly_document),'bounds':[0,150,680,330],'name':'Selection bounds'}}
module.Krita = old_krita
identity_module.Krita=module.Krita
crop_path = str(output / 'region-crop.png')
QImage(image_path).copy(100,150,580,330).save(crop_path)
region = dict(canvas,path=crop_path,name='Selection bounds',bounds=[100,150,580,330],state='fresh')
panel.handle_event({'type':'context','selected':True,'follow_active':False,'state':'fresh','canvas':canvas,'region':region})
goal['question'] = None
panel.handle_event({'type':'goal','goal':goal,'mode':'plan','references':[], 'painting_target':{'document_id':'target-other','filename':str(root.parent/'other-study.kra'),'name':'Working painting','mode':'copy','bound':False}})
assert panel.scope_tray.isVisible() and panel.plan_context_button.isVisible() and panel.region_group.isVisible()
assert 'other-study.kra' in panel.workspace_label.text(), 'target identity must not be inferred from the context canvas'
assert 'painting.kra' in panel.canvas_button.text()
assert 'Rectangular crop' in panel.region_button.toolTip() and 'not an exact freehand mask' in panel.region_button.toolTip()
panel.last_user_item = panel.transcript.add_message('You','Look at this part of the upper field.',message_id='region-message')
panel.handle_event({'type':'message_context','message_id':'region-message','status':'included','canvas':canvas,'region':region})
assert panel.last_user_item['region_receipt']['path'] == crop_path
assert panel.last_user_item['region_receipt']['overview_path'] == image_path
preview = module.ImagePreview(panel,dict(region,overview_path=image_path)); preview.show(); settle()
assert preview.location_button.isVisible()
preview.zoom_button.click(); assert preview.actual_pixels and preview.picture.width() == 580
preview.zoom_button.click(); assert not preview.actual_pixels
preview.location_button.click(); assert preview.show_location
preview.grab().save(str(output/'dialog-region-location.png')); preview.close()
# Export is a complete reusable brief, including characters and stop conditions.
panel.attached_references = [{'name':'Rothko study reference.png','path':image_path,'role':'material'}]
export = module.PlanDialog(panel,goal); markdown = export.markdown(); export.close()
for required in ['## Painting target','other-study.kra','## References','Rothko study reference.png','## Characters','Mara','Red coat','## Creative freedom','## Painting order','without stopping between steps','Upper field only','## Final visual checks','No new stripes.','## Allowance']:
    assert required in markdown, 'export missing '+required
for retired in ['Stop after this stage','width 580','Maximum native operations','## Stages']:
    assert retired not in markdown, 'export still mentions '+retired
assert str(root) not in markdown, 'shared brief must not embed the machine’s state directory'
for dark in (True,False):
    panel.apply_theme(dark)
    for width,height in ((360,640),(440,820),(600,900)):
        panel.resize(width,height); settle(); panel.transcript.jump_to_latest(); settle()
        for control in (panel.region_button,panel.region_remove,panel.plan_context_button,panel.send_button,panel.mode_selector):
            point=control.mapTo(panel,control.rect().bottomRight())
            assert point.x() <= panel.width() and point.y() <= panel.height(), 'region/plan context control clipped'
        panel.grab().save(str(output/('context-%s-%s.png'%('dark' if dark else 'light',width))))
panel.handle_event({'type':'context','selected':True,'follow_active':True,'state':'fresh','canvas':dict(canvas,document_id='switched-document',name='Other canvas'), 'region':dict(region,state='unavailable')})
assert panel.region_button.text() == '⌗  Crop unavailable'
assert 'other-study.kra' in panel.workspace_label.text(), 'switching context must preserve target label'
panel.region_remove.click(); assert commands[-1] == {'type':'context','action':'clear_region'}
panel.handle_event({'type':'context','selected':True,'follow_active':True,'state':'fresh','canvas':canvas,'region':None})
assert not panel.region_group.isVisible() and panel.plan_context_button.isVisible()
# Ask's lesson stays reachable beside the plan in every mode, in a window that is not modal.
goal['lesson'] = {'title':'Winter river at night','markdown':'# Lesson: Winter river at night\n\n1. **Block in** the sky.\n2. Glow the lamps.','at':'2026-10-11T22:00:00Z'}
panel.handle_event({'type':'goal','goal':goal,'mode':'agent','references':[]})
assert panel.lesson_button.isVisible() and panel.plan_context_button.isVisible(), 'lesson and plan coexist'
assert 'painter does not read it' in panel.lesson_button.toolTip()
panel.resize(360,640); settle()
point=panel.lesson_button.mapTo(panel,panel.lesson_button.rect().bottomRight())
assert point.x() <= panel.width() and point.y() <= panel.height(), 'lesson chip clipped'
panel.resize(440,820); settle()
panel.lesson_button.click(); settle()
lesson_window = panel.lesson_dialog
assert lesson_window.isVisible() and not lesson_window.isModal(), 'the lesson stays open while painting'
assert 'Glow the lamps' in lesson_window.body.toPlainText() and 'Winter river at night' in lesson_window.windowTitle()
lesson_window.grab().save(str(output/'dialog-lesson.png'))
goal['lesson'] = dict(goal['lesson'],title='Snowy bridge',markdown='# Lesson: Snowy bridge\n\n1. Fog band.')
panel.handle_event({'type':'goal','goal':goal,'mode':'autopilot','references':[]})
assert 'Fog band' in lesson_window.body.toPlainText(), 'an open lesson window follows the newest lesson'
goal['lesson'] = None
panel.handle_event({'type':'goal','goal':goal,'mode':'plan','references':[]})
assert not panel.lesson_button.isVisible() and not lesson_window.isVisible()
goal['target_needs_review'] = True
panel.handle_event({'type':'goal','goal':goal,'mode':'plan','references':[]})
assert panel.execute_button.isHidden() and 'review plan' in panel.plan_summary.text()
goal['target_needs_review'] = False
panel.attached_references=[]; panel.apply_theme(True); panel.resize(440,820)
# Reference purposes are editable directly and remain immutable in sent receipts.
reference = {'id':'ref-material','name':'Surface reference.png','path':image_path,'purpose':'general','notes':'','role':'reference'}
panel.pending_references=[reference]
panel.apply_reference_purpose(reference,'material','Follow the dry tooth; keep our existing palette.')
assert reference['purpose'] == 'material' and 'existing palette' in reference['notes']
reference_dialog = module.ReferencePreview(panel,reference)
assert reference_dialog.purpose.currentData() == 'material'
reference_dialog.show(); settle(); reference_dialog.grab().save(str(output/'dialog-reference-purpose.png')); reference_dialog.close()
panel.pending_references=[]; panel.attached_references=[dict(reference)]
panel.apply_reference_purpose(panel.attached_references[0],'palette','Use color only.')
assert commands[-1] == {'type':'set_reference_purpose','id':'ref-material','path':image_path,'purpose':'palette','notes':'Use color only.'}
receipt_item = panel.transcript.add_message('You','Use this surface as the material reference.',message_id='reference-message')
panel.last_user_item=receipt_item
panel.handle_event({'type':'message_context','message_id':'reference-message','status':'included','references':[reference]})
reference['purpose']='palette'; reference['notes']='Later change'
assert receipt_item['reference_receipts'][0]['purpose'] == 'material'
assert 'existing palette' in receipt_item['reference_receipts'][0]['notes']
panel.attached_references=[dict(reference,purpose='material',notes='Preserve the palette.')]
reference_plan = module.PlanDialog(panel,goal)
assert 'Material & texture' in reference_plan.markdown() and 'Preserve the palette.' in reference_plan.markdown()
reference_plan.show(); settle(); reference_plan.grab().save(str(output/'dialog-plan-with-references.png'))
reference_plan.findChild(QTabWidget).setCurrentIndex(1); settle(); reference_plan.grab().save(str(output/'dialog-plan-reference-details.png')); reference_plan.close()
panel.attached_references=[]
for index,purpose in enumerate(['likeness','composition','palette','material']):
    path=str(output/('reference-fixture-%d.png'%index)); QImage(image_path).save(path)
    panel.attached_references.append({'id':'ref-'+str(index),'path':path,'name':'Reference '+str(index+1),'purpose':purpose,'notes':''})
panel.show_references(); panel.resize(360,740); settle()
for button in panel.reference_remove_buttons:
    assert button.mapTo(panel,button.rect().bottomRight()).x() <= panel.width()
panel.grab().save(str(output/'context-four-reference-purposes.png'))
panel.pending_references=[]; panel.attached_references=[]; panel.show_references()
# Reference parts: the preview opens the reference in Krita; the selection there becomes its own reference.
class PartSelection:
    def __init__(self, width, height, rect=None):
        self.w, self.h, self.mask = width, height, bytearray(width * height)
        if rect:
            for row in range(rect[1], rect[1] + rect[3]): self.mask[row * width + rect[0]:row * width + rect[0] + rect[2]] = b'\xff' * rect[2]
    def _box(self):
        cells = [(i % self.w, i // self.w) for i, v in enumerate(self.mask) if v]
        if not cells: return 0, 0, 0, 0
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        return min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    def x(self): return self._box()[0]
    def y(self): return self._box()[1]
    def width(self): return self._box()[2]
    def height(self): return self._box()[3]
    def pixelData(self, x, y, w, h): return b''.join(bytes(self.mask[r * self.w + x:r * self.w + x + w]) for r in range(y, y + h))
class PartDocument:
    def __init__(self, path):
        image = QImage(path).convertToFormat(QImage.Format.Format_ARGB32)
        self.path, self.W, self.H = path, image.width(), image.height()
        bits = image.constBits(); bits.setsize(image.sizeInBytes()); self.data = bytes(bits); self.sel = None
    depth = 'U8'
    def width(self): return self.W
    def height(self): return self.H
    def colorModel(self): return 'RGBA'
    def colorDepth(self): return self.depth
    def setColorSpace(self, model, depth, profile): self.converted = (model, depth); self.depth = depth; return True
    def pixelData(self, x, y, w, h): return self.data
    def selection(self): return self.sel
    def setModified(self, value): self.modified = value
    def close(self):
        if self in part_documents: part_documents.remove(self)
        return True
part_documents, shown_views, part_tools = [], [], []
def open_part_document(path):
    document = PartDocument(path); part_documents.append(document); return document
part_window = types.SimpleNamespace(addView=lambda document: None, activeView=lambda: 'painting-view', showView=shown_views.append)
before_parts_krita = module.Krita
module.Krita = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(openDocument=open_part_document, activeWindow=lambda: part_window,
    documents=lambda: list(part_documents), action=lambda name: types.SimpleNamespace(trigger=lambda: part_tools.append(name)), activeDocument=lambda: None))
moscow = {'id': 'ref-moscow', 'name': 'New Moscow', 'path': image_path, 'purpose': 'general', 'notes': '', 'role': 'reference'}
panel.attached_references = [moscow]; panel.show_references()
preview = module.ReferencePreview(panel, moscow)
assert [b.text() for b in preview.part_buttons] == ['Select a part in Krita…', 'Crop in Krita…'] and all(b.isEnabled() for b in preview.part_buttons)
preview.close(); busy_preview = module.ReferencePreview(panel, moscow, readonly=True)
assert not any(b.isEnabled() for b in busy_preview.part_buttons) and busy_preview.part_buttons[0].toolTip() == 'Pause the agent to select a part'
busy_preview.close()
panel.start_part(moscow, 'part')
assert panel.part_bar.isVisible() and panel.part_bar_label.text() == 'Selecting a part of New Moscow' and len(part_documents) == 1
assert part_tools == ['KisToolSelectOutline'], 'selecting a part hands the artist the Freehand Selection Tool, never a colour wand'
temporary = part_documents[0].path; assert temporary != image_path and os.path.exists(temporary), 'a copy is opened, never the reference'
panel.use_part()
assert panel.status.text() == 'Select the part first.' and len(part_documents) == 1, 'nothing selected: the document stays open'
W, H = part_documents[0].W, part_documents[0].H
part_documents[0].sel = PartSelection(W, H, [0, 0, W, H // 2])
names = []; panel.part_name = lambda default: names.append(default) or 'Sky'
panel.use_part()
assert names == ['Part of New Moscow'] and not part_documents and not panel.part_bar.isVisible() and shown_views == ['painting-view']
assert not os.path.exists(temporary), 'the temporary copy is removed'
part = panel.pending_references[-1]
assert (part['name'], part['part_of'], part['part_kind'], part['bounds'], part['role']) == ('Sky (part)', image_path, 'part', [0, 0, W, H // 2], 'reference')
assert QImage(part['path']).size() == QImage(image_path).size(), 'a part keeps the size of the original'
os.remove(part['path']); panel.pending_references = []
PartDocument.depth = 'U16'; panel.start_part(moscow, 'part')
assert part_documents[0].converted == ('RGBA', 'U8'), 'a 16-bit reference is read as 8-bit RGBA'
panel.close_part(); PartDocument.depth = 'U8'
panel.start_part(moscow, 'crop'); part_documents.clear(); panel.check_part_session()
assert not panel.part_bar.isVisible(), 'closing the temporary document yourself cancels'
pending = {'path': image_path, 'role': 'reference', 'name': 'Pending.png', 'purpose': 'general', 'notes': ''}
panel.attached_references = []; panel.pending_references = [pending]
panel.start_part(pending, 'crop'); part_documents[0].sel = PartSelection(W, H, [1, 1, 2, 2]); panel.part_name = lambda default: 'Detail'
panel.use_part(); crop = panel.pending_references[-1]
assert (crop['name'], crop['part_kind'], crop['bounds']) == ('Detail (crop)', 'crop', [1, 1, 2, 2]) and QImage(crop['path']).width() == 2, 'a pending reference can be split'
os.remove(crop['path'])
panel.pending_references = [dict(pending, name='R%d' % i) for i in range(4)]; panel.start_part(panel.pending_references[0], 'part')
assert panel.status.text() == 'Remove a reference to add a part.' and not part_documents
module.Krita = before_parts_krita
panel.pending_references=[]; panel.attached_references=[]; panel.show_references()
# A catalog refresh must not hide model verification or switch an existing session.
model_a={'provider':'openrouter','id':'deepseek/deepseek-v4.1-flash','name':'DeepSeek V4.1 Flash','configured':True}
model_b={'provider':'other','id':'candidate','name':'Candidate model','configured':True}
panel.handle_event({'type':'model','model':{'provider':model_a['provider'],'id':model_a['id']}})
panel.handle_event({'type':'status','phase':'checking_model','message':'Checking image and tool support…'})
panel.handle_event({'type':'models','models':[model_a,model_b],'selected':{'provider':'other','id':'candidate'}})
assert panel.status.text() == 'Checking image and tool support…'
assert panel.model.currentData()['id'] == model_a['id']
count = len(commands)
panel.provider_filter.setCurrentIndex(panel.provider_filter.findData('other'))
assert len(commands) == count and panel.model.currentData() is None, 'browsing providers must not change the active route'
def choose_search_result(query):
    def enter():
        dialog = panel.model.findChildren(module.QDialog)[-1]
        field = dialog.findChild(QLineEdit)
        field.setText(query)
        QTest.keyClick(field, Qt.Key.Key_Return)
    QTimer.singleShot(0, enter)
    panel.model.showPopup()
choose_search_result('candidate')
assert commands[-1] == {'type':'set_model','provider':'other','model':'candidate'}, 'search and Enter commit one explicit choice'
count = len(commands)
QTimer.singleShot(0, lambda: panel.model.findChildren(module.QDialog)[-1].reject())
QTest.keyClick(panel.model, Qt.Key.Key_Return)
assert len(commands) == count, 'keyboard Enter opens the picker and Escape/Cancel changes nothing'
panel.handle_event({'type':'model_capability','status':'failed','message':'This route cannot use painting tools.'})
assert panel.model.currentData()['id'] == model_a['id'], 'failed model switches restore the accepted route'
# Providers are visible in the collapsed selector and every Pi route remains
# discoverable, including unconnected and noninteractive routes with reasons.
direct={'provider':'deepseek','id':'deepseek-flash','name':'DeepSeek Flash','configured':True,'interactive':True,'declared_images_supported':False}
unconnected={'provider':'anthropic','id':'claude-example','name':'Claude Example','configured':False,'interactive':True}
batch={'provider':'openrouter','id':'batch-example','name':'Example batch','configured':True,'interactive':False}
panel.handle_event({'type':'models','models':[model_a,model_b,direct,unconnected,batch]})
assert panel.provider_filter.currentText() == 'OpenRouter'
assert panel.model.currentText() == model_a['name']
assert {panel.provider_filter.itemData(index) for index in range(panel.provider_filter.count())}=={'openrouter','other','deepseek','anthropic'}
assert all(panel.model.itemData(i)['provider']=='openrouter' for i in range(panel.model.count()))
assert not panel.model.model().item(panel.model.findData({'provider':'openrouter','id':'batch-example'})).isEnabled()
panel.provider_filter.setCurrentIndex(panel.provider_filter.findData('deepseek'))
assert panel.model.currentData() is None
assert panel.model.count()==1
count = len(commands)
choose_search_result('deepseek-flash')
assert len(commands) == count + 1
assert commands[-1]=={'type':'set_model','provider':'deepseek','model':'deepseek-flash'}
assert not panel.send_button.isEnabled(), 'wait for provider/model acknowledgement before sending'
panel.handle_event({'type':'model','model':{'provider':'deepseek','id':'deepseek-flash'}})
assert panel.provider_filter.currentText()=='DeepSeek' and panel.model.currentText()=='DeepSeek Flash'
panel.provider_filter.setCurrentIndex(panel.provider_filter.findData('anthropic'))
assert panel.model.currentData() is None and panel.send_button.isEnabled(), 'a filter cannot disable the accepted route'
assert not panel.model.model().item(panel.model.findData({'provider':'anthropic','id':'claude-example'})).isEnabled()
panel.handle_event({'type':'model','model':{'provider':model_a['provider'],'id':model_a['id']}})
panel.handle_event({'type':'models','models':[model_a,model_b,direct,unconnected,batch],
    'providers':[{'id':'local-studio','name':'Local Studio','configured':True,'model_count':0}]})
assert panel.provider_filter.findData('local-studio')>=0
panel.provider_filter.setCurrentIndex(panel.provider_filter.findData('local-studio'))
assert 'No models are registered' in panel.provider_note.text() and panel.model.count()==0
panel.handle_event({'type':'model','model':{'provider':model_a['provider'],'id':model_a['id']}})
# The generic settings come from the companion's declarations (src/settings-schema.mjs), as at startup.
import subprocess
SCHEMA=json.loads(subprocess.run(['node','-e',"import('./src/settings-schema.mjs').then(m=>process.stdout.write(JSON.stringify(m.panelSchema())))"],
  cwd=str(Path(__file__).resolve().parents[1]),capture_output=True,text=True,check=True,env={**os.environ,'NODE_OPTIONS':''}).stdout)
panel.handle_event({'type':'settings_schema','fields':SCHEMA})
W=panel.setting_widgets
assert list(W)==['concurrency','move_size','merge_kept','guides','reference_first','assets','ai_images','keep_screen_awake','sharpen_goal','view_size','planner_model','study_folder','routing'], 'one control per generic setting, in declaration order'
W['concurrency'].setCurrentIndex(W['concurrency'].findData(2))
assert commands[-1]=={'type':'set_execution_settings','settings':{'concurrency':2,'reasoning':'auto','routing':'off','native_craft':True,'move_size':'subject','merge_kept':True,'guides':True,'reference_first':True,'assets':'codex','ai_images':0,'keep_screen_awake':False,'sharpen_goal':'ask','view_size':'auto','planner_model':'painter','study_folder':True}}
from creative_ui_test.qt_compat import QCheckBox as _QCheckBox
assert isinstance(W['keep_screen_awake'], _QCheckBox) and not W['keep_screen_awake'].isChecked(), 'the screen setting is a checkbox, off'
assert W['keep_screen_awake'].accessibleName() == 'Keep the screen awake while painting'
W['keep_screen_awake'].setChecked(True); assert commands[-1]['settings']['keep_screen_awake'] is True
W['keep_screen_awake'].setChecked(False); assert commands[-1]['settings']['keep_screen_awake'] is False
panel.handle_event({'type':'execution_settings','settings':{**commands[-1]['settings'],'keep_screen_awake':True}})
assert W['keep_screen_awake'].isChecked() and commands[-1]['settings']['keep_screen_awake'] is False, 'restoring sends nothing back'
assert not panel.awake_indicator.isVisible()
panel.handle_event({'type':'keep_awake','active':True,'display':False}); assert panel.awake_indicator.isHidden(), 'system-only hold: no indicator'
panel.handle_event({'type':'keep_awake','active':True,'display':True}); assert not panel.awake_indicator.isHidden(), 'the screen hold is visible'
panel.handle_event({'type':'keep_awake','active':False,'display':False}); assert panel.awake_indicator.isHidden()
panel.handle_event({'type':'execution_settings','settings':{**commands[-1]['settings'],'keep_screen_awake':False}})   # back to off for the checks below
panel.reasoning_selector.setCurrentIndex(panel.reasoning_selector.findData('high'))
assert commands[-1]['settings']=={'concurrency':2,'reasoning':'high','routing':'off','native_craft':True,'move_size':'subject','merge_kept':True,'guides':True,'reference_first':True,'assets':'codex','ai_images':0,'keep_screen_awake':False,'sharpen_goal':'ask','view_size':'auto','planner_model':'painter','study_folder':True}
W['move_size'].setCurrentIndex(W['move_size'].findData('large'))
assert commands[-1]['settings']['move_size']=='large' and W['move_size'].accessibleName()=='Agent move size'
panel.handle_event({'type':'execution_settings','settings':{'concurrency':1,'reasoning':'auto','routing':'off','native_craft':True,'move_size':'quick'}})
assert W['move_size'].currentData()=='quick', 'the panel follows the saved move size'
W['merge_kept'].setCurrentIndex(W['merge_kept'].findData(False))
assert commands[-1]['settings']['merge_kept'] is False and W['merge_kept'].accessibleName()=='Layers after accepting'
assert W['routing'].accessibleName()=='Decision checks' and not hasattr(panel,'typesafe_key'), 'decision checks use the endpoint settings, not a TypeSafe-only key field'
assert [W['routing'].itemData(i) for i in range(W['routing'].count())]==['off','evaluate','guide']
assert not hasattr(panel,'craft_selector'), 'the painter always has the full Krita toolset'
assert not hasattr(panel,'computer_use_check') and 'computer_use' not in commands[-1]['settings'], 'computer use is gone from the panel'
panel.handle_event({'type':'skills','skills':[{'name':'paint-sky','description':'Paint or replace a sky.'},{'name':'place-subject','description':'Add one subject.'},{'name':'fix-region','description':'Repair one area.'}]})
panel.prompt.setPlainText('/')
assert panel.slash_menu.isVisible() and panel.slash_menu.count()==3, 'typing / lists the skills'
panel.prompt.setPlainText('/pa')
assert [panel.slash_menu.item(i).data(Qt.ItemDataRole.UserRole) for i in range(panel.slash_menu.count())]==['/skill:paint-sky'], 'the list filters as you type (an older companion: skills only)'
panel.choose_skill(panel.slash_menu.item(0))
assert panel.prompt.toPlainText()=='/skill:paint-sky ' and not panel.slash_menu.isVisible(), 'choosing a skill inserts /skill:name'
panel.prompt.setPlainText('/paint-sky a stormy dusk')
assert not panel.slash_menu.isVisible(), 'the menu closes once the request is being typed'
panel.prompt.setPlainText('')
# The companion's commands (its skills event): the short ones with their descriptions, then /skill:<name>.
panel.handle_event({'type':'skills','skills':[{'name':'guided-trace','description':'Sketch guides.'}],'commands':[
  {'command':'/trace','aliases':[],'description':'Draw guides, painting nothing.'},{'command':'/colour','aliases':['/color'],'description':'Lay the reference colours.'},
  {'command':'/skill:guided-trace','aliases':[],'description':'Sketch guides.'}]})
panel.prompt.setPlainText('/')
assert panel.slash_menu.isVisible() and [panel.slash_menu.item(i).data(Qt.ItemDataRole.UserRole) for i in range(panel.slash_menu.count())]==['/trace','/colour','/skill:guided-trace']
assert panel.slash_menu.item(0).text()=='/trace — Draw guides, painting nothing.', 'each command shows its one-line description'
panel.choose_skill(panel.slash_menu.item(1))
assert panel.prompt.toPlainText()=='/colour ' and not panel.slash_menu.isVisible(), 'choosing a command inserts it'
panel.prompt.setPlainText('')
# A new setting is one schema entry: the panel shows it, sends it and restores it with no panel code.
panel.handle_event({'type':'settings_schema','fields':SCHEMA+[{'key':'brush_style','label':'Brush style','accessible':'Brush style','tooltip':'','note':'A test setting.',
  'options':[{'value':'soft','label':'Soft'},{'value':'bold','label':'Bold'}]}]})
W=panel.setting_widgets
W['brush_style'].setCurrentIndex(W['brush_style'].findData('bold'))
assert commands[-1]['settings']['brush_style']=='bold' and W['brush_style'].accessibleName()=='Brush style'
before=len(commands)
panel.handle_event({'type':'execution_settings','settings':{'concurrency':1,'reasoning':'auto','routing':'off','native_craft':True,'move_size':'quick','brush_style':'soft'}})
assert W['brush_style'].currentData()=='soft' and len(commands)==before, 'restoring settings shows them without sending them back'
panel.handle_event({'type':'settings_schema','fields':SCHEMA}); W=panel.setting_widgets
assert W['assets'].accessibleName()=='Image assets' and [W['assets'].itemData(i) for i in range(W['assets'].count())]==['codex','openrouter']
W['assets'].setCurrentIndex(W['assets'].findData('openrouter'))
assert commands[-1]['settings']['assets']=='openrouter', 'the artist can choose OpenRouter for image assets'
panel.handle_event({'type':'execution_settings','settings':{'concurrency':1,'reasoning':'auto','routing':'off','native_craft':True,'move_size':'quick','assets':'codex'}})
assert W['assets'].currentData()=='codex', 'the panel follows the saved image-asset backend'
panel.handle_event({'type':'execution_settings','settings':{'concurrency':1,'reasoning':'auto','routing':'off','native_craft':False,'move_size':'quick'}})
assert commands[-1]['settings']['native_craft'] is True, 'a chat saved as strokes only gets the full toolset back'
panel.handle_event({'type':'visual_check','mode':'evaluate','pass_id':'p1','findings':[{'type':'stripes','label':'mechanical stripes','probability':.93,'location':'bottom_center'}]})
assert 'mechanical stripes (bottom center, 93%)' in panel.transcript.toPlainText() and 'Recorded only.' in panel.transcript.toPlainText()
panel.handle_event({'type':'review_progress','mode':'guide','mean':0.4,'scores':{'check-1':0.4}})
assert 'no real improvement (0.4 of 3)' in panel.transcript.toPlainText()
count=len(commands)
panel.handle_event({'type':'execution_settings','settings':{'concurrency':2,'reasoning':'high'},'effective_reasoning':'off','available_reasoning':['off']})
assert len(commands)==count and 'Now: off' in panel.reasoning_note.text() and 'Auto thinks' not in panel.reasoning_note.text()
panel.handle_event({'type':'execution_settings','settings':{'concurrency':2,'reasoning':'auto'},'effective_reasoning':'medium','available_reasoning':['low','medium'],
                    'reasoning_note':'Auto thinks at medium for the plan and the visual review, and at low while painting.'})
assert panel.reasoning_note.text().startswith('Auto thinks at medium') and 'Now: medium' in panel.reasoning_note.text(), 'the companion describes its Auto policy'
panel.handle_event({'type':'busy','busy':True})
assert not W['concurrency'].isEnabled() and not panel.reasoning_selector.isEnabled() and not panel.provider_filter.isEnabled()
panel.handle_event({'type':'busy','busy':False})
panel.resize(440,820); settle()
# Reading earlier messages must never be pulled to the streaming reply.
for i in range(30): panel.transcript.add_message('Creative Agent','Earlier message %d.\n\nA useful observation about the surface.' % i)
stream = panel.transcript.add_message('Creative Agent','A new answer begins. '); settle()
bar = panel.transcript.verticalScrollBar(); bar.setValue(80); panel.transcript.track_scroll(); before_scroll = bar.value()
assert not panel.transcript.follow and panel.jump_button.isVisible()
for _ in range(10): panel.transcript.append_to(stream,'Another useful detail. '); settle()
assert bar.value() == before_scroll, (before_scroll,bar.value())
panel.jump_button.click(); settle(); assert bar.value() == bar.maximum()
# Input newline and paste image follow actual Qt paths.
panel.prompt.setPlainText('First line'); QTest.keyClick(panel.prompt,Qt.Key.Key_End); QTest.keyClick(panel.prompt,Qt.Key.Key_Return,Qt.KeyboardModifier.ShiftModifier)
assert '\n' in panel.prompt.toPlainText()
image = QImage(20,20,QImage.Format.Format_RGB32); image.fill(QColor('#bf4328')); mime = QMimeData(); mime.setImageData(image)
panel.prompt.insertFromMimeData(mime); assert len(panel.pending_references) == 1
panel.handle_event({'type':'ended'}); assert panel.source.isEnabled() and panel.empty_state.isVisible()
# Returning/restoring focuses existing views, never saves/closes or starts Agent.
def fake_document(identifier, filename=''):
    return types.SimpleNamespace(fileName=lambda:filename,
        rootNode=lambda:types.SimpleNamespace(uniqueId=lambda:types.SimpleNamespace(toString=lambda:identifier)))
focus_calls=[]
other_document=fake_document('other-document','/tmp/other-unsaved-study.kra')
unsaved_target=fake_document('unsaved-target')
open_documents=[other_document,unsaved_target]
open_views=[]
window=types.SimpleNamespace(showView=lambda view:focus_calls.append(('show',view.document())),activate=lambda:focus_calls.append(('activate',None)))
def add_view(document):
    view=types.SimpleNamespace(document=lambda:document,window=lambda:window)
    open_views.append(view); focus_calls.append(('add',document)); return view
window.addView=add_view
existing_view=add_view(unsaved_target); focus_calls.clear()
def open_document(filename):
    doc=fake_document('reopened-target',filename); open_documents.append(doc); focus_calls.append(('open',filename)); return doc
instance=types.SimpleNamespace(documents=lambda:open_documents,views=lambda:open_views,activeDocument=lambda:None,
    activeWindow=lambda:window,openDocument=open_document,windows=lambda:[window])
window.views=lambda:open_views
module.Krita=types.SimpleNamespace(instance=lambda:instance)
identity_module.Krita=module.Krita
panel.painting_target={'document_id':module.document_id(unsaved_target),'name':'Untitled','bound':True}
before_commands=len(commands); assert panel.return_to_painting()
assert focus_calls==[('show',unsaved_target),('activate',None)]
assert len(open_documents)==2 and commands[before_commands:]==[{'type':'context','action':'inspect'}]
instance.activeDocument=lambda:unsaved_target
focus_calls.clear();assert panel.return_to_painting(restored=True)
assert not focus_calls, 'Restoring the already-active canvas must not call showView (Krita 5.3 crash).'
instance.activeDocument=lambda:None
# Explicit history restore waits through end's final busy=false, then focuses only
# after the newly restored study has published its target and become idle.
panel.study_active=False; panel.request_restore({'type':'resume','id':'focus-study'})
panel.handle_event({'type':'busy','busy':False}); assert panel.focus_after_restore
panel.handle_event({'type':'busy','busy':True})
panel.handle_event({'type':'study','id':'focus-study','directory':'/tmp'})
paused_goal=dict(goal,status='paused',question=None)
panel.handle_event({'type':'goal','goal':paused_goal,'mode':'plan','references':[],
    'painting_target':{'document_id':module.document_id(unsaved_target),'name':'Untitled','bound':True}})
focus_calls.clear(); before_commands=len(commands)
panel.handle_event({'type':'busy','busy':False})
assert not panel.focus_after_restore and focus_calls==[('show',unsaved_target),('activate',None)]
assert panel.goal['status']=='paused' and commands[before_commands:]==[{'type':'context','action':'inspect'}]
# The on-disk target opens once, then path matching reuses the unsaved in-memory
# document even when persisted document IDs belong to a previous Krita run.
import tempfile
with tempfile.TemporaryDirectory() as focus_dir:
    target_path=str(Path(focus_dir)/'painting.kra'); Path(target_path).write_bytes(b'UI test fixture')
    panel.painting_target={'document_id':'old-run-id','filename':target_path,'bound':False}
    focus_calls.clear(); assert panel.return_to_painting()
    assert [call[0] for call in focus_calls]==['open','add','show','activate']
    focus_calls.clear(); assert panel.return_to_painting()
    assert [call[0] for call in focus_calls]==['show','activate']
    assert len(open_documents)==3 and open_documents[0] is other_document
    Path(target_path).unlink()
    assert panel.return_to_painting(), 'an open unsaved target must survive a Finder move'
# A clone may only be present in a view and share a layer UUID with its source.
view_only_clone=fake_document('unsaved-target'); clone_view=add_view(view_only_clone)
assert module.document_id(view_only_clone)!=module.document_id(unsaved_target)
panel.painting_target={'document_id':module.document_id(view_only_clone),'name':'Clone','bound':True}
focus_calls.clear(); assert panel.return_to_painting()
assert focus_calls==[('show',view_only_clone),('activate',None)]
panel.painting_target={'document_id':'missing','filename':'/nonexistent/missing-painting.kra','missing':True}
panel.render_target(); panel.update_controls(); focus_calls.clear()
assert panel.return_button.text()=='Locate painting'
assert panel.execute_button.isHidden(), 'a moved target must be relinked before Agent can resume'
assert not panel.return_to_painting(restored=True) and not focus_calls
assert panel.recovery_button.text()=='Locate painting'
for dark in (True,False):
    panel.apply_theme(dark); panel.resize(360,640); settle()
    assert panel.return_button.mapTo(panel,panel.return_button.rect().bottomRight()).x() <= panel.width()
    panel.grab().save(str(output/('target-recovery-%s.png'%('dark' if dark else 'light'))))
module.Krita=old_krita
identity_module.Krita=module.Krita
# Settings fit actual Qt metrics without a horizontal scrollbar, including the
# largest supported text setting. All controls are reachable by keyboard.
panel.study_active=False; panel.source.setCurrentIndex(panel.source.findData('new')); panel.update_controls()
build={'version':'1.0.0','protocol_version':2,'build_id':'eef0123456789'*5}
connection_event={'build':build,'bridge':{'creative_version':'1.0.0','protocol_version':2,'build':build,'private_key':'must never be copied'},'compatible':True}
panel.render_connection(build,connection_event)
assert panel.connection_status.text()=='Connected · matching build'
assert '{' not in panel.diagnostics.text() and len(panel.diagnostics.text().splitlines())==3
panel.copy_diagnostics.click()
assert 'private_key' not in QApplication.clipboard().text() and 'must never' not in QApplication.clipboard().text()
assert json.loads(QApplication.clipboard().text())['ui']['build_id']==build['build_id']
assert not panel.diagnostics_text.isVisible()
settings_controls=[panel.source,panel.name,panel.canvas_width,panel.canvas_height,panel.experiment,
    panel.theme_selector,panel.text_size,W['concurrency'],panel.reasoning_selector,panel.filter,panel.connect_button,panel.restore_button,
    panel.diagnostics_toggle,panel.copy_diagnostics]
for text_size in (14,20):
    panel.text_size.setValue(text_size)
    for width in (480,360):
        panel.options_dialog.resize(width,620); panel.options_dialog.show(); panel.options_dialog.activateWindow(); settle()
        assert panel.options_dialog.width()==width
        assert panel.options_scroll.horizontalScrollBar().maximum()==0
        assert panel.setup_box.width() <= panel.options_scroll.viewport().width()
        for control in settings_controls:
            assert control.focusPolicy()!=Qt.FocusPolicy.NoFocus and control.isEnabled(), (control.accessibleName(),control.objectName(),type(control).__name__,control.isEnabled())
            panel.options_scroll.ensureWidgetVisible(control); settle()
            right=control.mapTo(panel.options_scroll.viewport(),control.rect().bottomRight()).x()
            left=control.mapTo(panel.options_scroll.viewport(),control.rect().topLeft()).x()
            assert 0 <= left < right < panel.options_scroll.viewport().width(), ('Settings control clipped',control.accessibleName(),left,right)
        panel.options_scroll.verticalScrollBar().setValue(0); settle()
        panel.options_dialog.grab().save(str(output/('settings-top-%s-%s.png'%(width,text_size))))
        panel.options_scroll.ensureWidgetVisible(panel.diagnostics_toggle); settle()
        panel.options_dialog.grab().save(str(output/('settings-connection-%s-%s.png'%(width,text_size))))
panel.source.setFocus(); settle(); reached=set()
for _ in range(80):
    focused=app.focusWidget()
    if focused in settings_controls: reached.add(focused)
    QTest.keyClick(focused or panel.options_dialog,Qt.Key.Key_Tab); settle()
assert all(control in reached for control in settings_controls), 'Settings tab order must reach every control'
panel.diagnostics_toggle.click(); settle()
assert panel.diagnostics_text.isVisible() and panel.options_scroll.horizontalScrollBar().maximum()==0
panel.options_dialog.grab().save(str(output/'settings-expanded-360-20.png'))
panel.render_connection(dict(build,build_id='another-ui-build'),connection_event)
assert panel.connection_status.text().startswith('Update required')
panel.diagnostics_toggle.click(); panel.text_size.setValue(14); panel.apply_theme(True)
panel.render_connection(build,connection_event); panel.options_dialog.resize(480,620)
panel.options_scroll.verticalScrollBar().setValue(0); settle(); panel.options_dialog.grab().save(str(output/'settings-top-dark-480-14.png'))
panel.options_scroll.ensureWidgetVisible(panel.diagnostics_toggle); settle(); panel.options_dialog.grab().save(str(output/'settings-connection-dark-480-14.png'))
panel.options_dialog.hide()
# Styled selectors keep a real dropdown hit target and native keyboard behavior.
for theme in ('dark','light'):
    assert not QPixmap(str(module_path.parent/'icons'/('chevron-'+theme+'.svg'))).isNull()
panel.options_dialog.show(); panel.options_dialog.activateWindow()
panel.options_scroll.ensureWidgetVisible(panel.theme_selector); panel.theme_selector.setFocus(); settle()
QTest.keyClicks(panel.theme_selector,'l'); settle(); assert panel.theme_selector.currentText()=='Light'
for control in (panel.theme_selector,panel.source,panel.experiment):
    panel.options_scroll.ensureWidgetVisible(control); settle()
    option=QStyleOptionComboBox(); control.initStyleOption(option)
    arrow=control.style().subControlRect(QStyle.ComplexControl.CC_ComboBox,option,QStyle.SubControl.SC_ComboBoxArrow,control)
    QTest.mouseClick(control,Qt.MouseButton.LeftButton,pos=arrow.center()); settle()
    assert control.view().isVisible(), 'dropdown chevron must open the actual selector'
    control.hidePopup(); settle()
panel.options_dialog.hide()
for control in (panel.mode_selector,):
    option=QStyleOptionComboBox(); control.initStyleOption(option)
    arrow=control.style().subControlRect(QStyle.ComplexControl.CC_ComboBox,option,QStyle.SubControl.SC_ComboBoxArrow,control)
    QTest.mouseClick(control,Qt.MouseButton.LeftButton,pos=arrow.center()); settle()
    assert control.view().isVisible()
    control.hidePopup(); settle()
def inspect_and_close_model_picker():
    dialog = panel.model.findChildren(module.QDialog)[-1]
    assert dialog.windowTitle() == 'Choose a model'
    assert dialog.findChild(QLineEdit).accessibleName() == 'Search models by name or ID'
    dialog.reject()
QTimer.singleShot(0, inspect_and_close_model_picker)
panel.model.showPopup()
for previous_source in ('new', 'copy'):
    panel.source.setCurrentIndex(panel.source.findData(previous_source))
    assert panel.source.currentData() == previous_source
    panel.new_chat()
    assert panel.source.currentData() == 'current', 'new chat must not inherit the previous painting creation choice'
# 'Match <app>' follows the application's palette: Toska's colours under a Toska theme, Dark or Light otherwise
from creative_ui_test.qt_compat import QPalette
from creative_ui_test.panel_theme import TOSKA_NIGHT, TOSKA_DAY, DARK, LIGHT
saved_palette = QPalette(QApplication.palette()); panel.theme_selector.setCurrentIndex(0); settle()
assert panel.theme_mode == 'system'
theme_applies = []; _apply_theme = panel.apply_theme
panel.apply_theme = lambda *args, **kwargs: (theme_applies.append(args), _apply_theme(*args, **kwargs))[1]
for window, expected in (('#141b25', TOSKA_NIGHT), ('#efe8dc', TOSKA_DAY), ('#2a2a2a', DARK), ('#e6e6e6', LIGHT)):
    palette = QPalette(saved_palette); palette.setColor(QPalette.ColorRole.Window, QColor(window)); theme_applies.clear()
    QApplication.setPalette(palette); settle()
    assert len(theme_applies) == 1, ('one apply per palette change', window, len(theme_applies))
    assert {key: panel.theme_colors[key] for key in expected} == expected, (window, panel.theme_colors)
    panel.grab().save(str(output/('match-theme-%s.png' % window.lstrip('#'))))
QApplication.setPalette(saved_palette); settle(); del panel.apply_theme
panel.close()
print('Qt interaction, context receipts, streaming selection/scroll, structured plans, paste and six themed layout checks passed: '+str(output))

# Decision endpoints: live list labels, key hint and visual-check note.
panel.handle_event({'type': 'decisions', 'endpoint': 'openrouter', 'selection': {'endpoint': 'openrouter', 'model': 'openai/gpt-6-luna-decisions'}, 'visual': True,
    'endpoints': [{'id': 'openrouter', 'name': 'OpenRouter', 'custom': False, 'key_configured': True, 'key_hint': ''},
                  {'id': 'openai', 'name': 'OpenAI', 'custom': False, 'key_configured': False, 'key_hint': 'An OpenAI API key'}],
    'models': [{'id': 'openai/gpt-6-luna-decisions', 'images': True, 'price_per_million_input': 0.1}, {'id': 'typesafe/jev-1.13', 'images': False}]})
# Autopilot is offered as experimental, in its label and in the mode tooltip.
autopilot_index = panel.mode_selector.findData('autopilot')
assert panel.mode_selector.itemText(autopilot_index) == 'Autopilot (experimental)', panel.mode_selector.itemText(autopilot_index)
assert 'Autopilot (experimental)' in panel.mode_selector.toolTip(), panel.mode_selector.toolTip()
assert panel.decision_endpoint.count() == 2 and 'needs key' in panel.decision_endpoint.itemText(1)
assert panel.decision_model.currentData() == 'openai/gpt-6-luna-decisions' and 'reads images' in panel.decision_model.currentText()
assert 'text only' in panel.decision_model.itemText(1) and not panel.decision_key.isEnabled()
assert 'Visual checks and pacing are on' in panel.decision_note.text()
print('Decision endpoint controls passed.')

# Four modes, and the Agent move bar: Keep / Undo, refined by typing.
assert [panel.mode_selector.itemData(i) for i in range(panel.mode_selector.count())] == ['ask', 'plan', 'agent', 'autopilot']
commands.clear()
panel.handle_event({'type': 'move', 'move': {'number': 3, 'status': 'ready', 'title': 'Swirling night sky', 'actions': 4, 'strokes': 212}})
assert panel.move_bar.isVisibleTo(panel) and 'Move 3' in panel.move_summary.text() and '212 strokes' in panel.move_summary.text()
panel.busy = False; panel.move_keep.click()
assert commands[-1] == {'type': 'move', 'action': 'keep', 'move': 3} and not panel.move_bar.isVisibleTo(panel)
panel.handle_event({'type': 'move', 'move': {'number': 4, 'status': 'ready', 'title': 'Cypress', 'actions': 1}})
assert 'Luna' not in panel.move_summary.text(), 'no review, no line'
panel.handle_event({'type': 'move', 'move': {'number': 4, 'status': 'ready', 'title': 'Cypress', 'actions': 1, 'review_line': 'Luna undid 1 of 2 batches (Moon covered <b>)'}})
assert 'Luna undid 1 of 2 batches (Moon covered &lt;b&gt;)' in panel.move_summary.text(), panel.move_summary.text()
panel.handle_event({'type': 'move', 'move': {'number': 4, 'status': 'ready', 'title': 'Cypress', 'actions': 1, 'review_line': 'Luna: no regressions in 1 batch', 'likeness_line': 'Goal likeness: ΔE 5.9 → 6.1 over 2 batches; undid 1 (darker than the goal, lower left)'}})
assert 'Goal likeness: ΔE 5.9 → 6.1 over 2 batches; undid 1' in panel.move_summary.text() and 'Luna: no regressions' in panel.move_summary.text(), panel.move_summary.text()
panel.move_undo.click()
assert commands[-1] == {'type': 'move', 'action': 'undo', 'move': 4}
panel.handle_event({'type': 'move', 'move': {'number': 5, 'status': 'empty', 'actions': 0}})
assert not panel.move_bar.isVisibleTo(panel), 'an empty move shows no card'
print('Agent move bar passed.')
