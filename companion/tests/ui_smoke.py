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
from PyQt5.QtWidgets import QApplication, QDockWidget, QTabWidget, QLabel, QStyle, QStyleOptionComboBox
from PyQt5.QtCore import QProcess, Qt, QMimeData, QTimer
from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtGui import QTextDocument, QTextCursor, QImage, QColor, QPixmap
from PyQt5.QtTest import QTest
root = Path(__file__).resolve().parents[1]
module_path = root.parent / 'plugin/kritamcp/creative_docker.py'
stub = types.ModuleType('krita'); stub.DockWidget = QDockWidget
stub.DockWidgetFactory = object; stub.DockWidgetFactoryBase = types.SimpleNamespace(DockRight=0)
stub.Krita = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(activeDocument=lambda: None))
sys.modules['krita'] = stub
package = types.ModuleType('creative_ui_test'); package.__path__ = [str(module_path.parent)]; sys.modules['creative_ui_test'] = package
spec = importlib.util.spec_from_file_location('creative_ui_test.creative_docker', module_path)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
identity_module = sys.modules['creative_ui_test.creative_document_identity']
app = QApplication([])
panel = module.CreativeAgentDocker(); panel.resize(440, 820); panel.show()
assert panel.source.currentData() == 'current', 'startup without a document must not imply a request for a new painting'
def settle():
    for _ in range(8): app.processEvents()
commands = []
panel.process = types.SimpleNamespace(state=lambda: QProcess.Running, write=lambda data: commands.append(json.loads(data)))
panel.handle_event({'type':'ready','models':[{'provider':'openrouter','id':'deepseek/deepseek-v4.1-flash','name':'DeepSeek V4.1 Flash','configured':True}], 'bridge':{}, 'build':{'version':'1.0.0','build_id':'test-build'}})
assert commands[-1] == {'type':'context','action':'inspect'}
# A generated stand-in canvas, so the test runs on a fresh clone.
(root / 'output').mkdir(parents=True, exist_ok=True)
image_path = str(root / 'output' / 'ui-fixture-canvas.png')
fixture = QImage(384, 512, QImage.Format_RGB32); fixture.fill(QColor('#7a2f2a'))
for y in range(160, 352):
    for x in range(48, 336): fixture.setPixelColor(x, y, QColor('#c4572f'))
assert fixture.save(image_path), 'fixture canvas could not be written'
canvas = {'document_id':'open-painting','name':'DeepSeek — first color-field study','filename':str(root.parent / 'painting.kra'), 'modified':True,
          'width':768,'height':1024,'revision':'r1','content_id':'sha256-one','captured_at':'2026-09-11T10:00:00Z','path':image_path}
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
QTest.keyClick(panel.prompt, Qt.Key_Return)
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
cursor = item['label'].textCursor(); cursor.setPosition(10); cursor.setPosition(30, QTextCursor.KeepAnchor); item['label'].setTextCursor(cursor)
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
assert panel.mode_selector.currentData() == 'plan' and panel.plan_bar.isVisible()
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
assert not panel.execute_button.isVisible(), 'answer required before starting a pending plan'
goal['question'] = None
panel.handle_event({'type':'goal','goal':goal,'mode':'plan','references':[]})
panel.execute_button.click(); assert commands[-1]['start_plan'] is True
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
cursor = unicode_reply['label'].textCursor(); cursor.setPosition(7); cursor.setPosition(15,QTextCursor.KeepAnchor); unicode_reply['label'].setTextCursor(cursor)
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
assert not panel.execute_button.isVisible() and 'review plan' in panel.plan_summary.text()
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
        QTest.keyClick(field, Qt.Key_Return)
    QTimer.singleShot(0, enter)
    panel.model.showPopup()
choose_search_result('candidate')
assert commands[-1] == {'type':'set_model','provider':'other','model':'candidate'}, 'search and Enter commit one explicit choice'
count = len(commands)
QTimer.singleShot(0, lambda: panel.model.findChildren(module.QDialog)[-1].reject())
QTest.keyClick(panel.model, Qt.Key_Return)
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
assert list(W)==['concurrency','move_size','merge_kept','assets','routing'], 'one control per generic setting, in declaration order'
W['concurrency'].setCurrentIndex(W['concurrency'].findData(2))
assert commands[-1]=={'type':'set_execution_settings','settings':{'concurrency':2,'reasoning':'auto','routing':'off','native_craft':True,'move_size':'subject','merge_kept':True,'assets':'codex'}}
panel.reasoning_selector.setCurrentIndex(panel.reasoning_selector.findData('high'))
assert commands[-1]['settings']=={'concurrency':2,'reasoning':'high','routing':'off','native_craft':True,'move_size':'subject','merge_kept':True,'assets':'codex'}
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
assert [panel.slash_menu.item(i).data(Qt.UserRole) for i in range(panel.slash_menu.count())]==['paint-sky'], 'the list filters as you type'
panel.choose_skill(panel.slash_menu.item(0))
assert panel.prompt.toPlainText()=='/paint-sky ' and not panel.slash_menu.isVisible(), 'choosing a skill inserts /name'
panel.prompt.setPlainText('/paint-sky a stormy dusk')
assert not panel.slash_menu.isVisible(), 'the menu closes once the request is being typed'
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
assert len(commands)==count and 'Active model: off' in panel.reasoning_note.text()
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
panel.prompt.setPlainText('First line'); QTest.keyClick(panel.prompt,Qt.Key_End); QTest.keyClick(panel.prompt,Qt.Key_Return,Qt.ShiftModifier)
assert '\n' in panel.prompt.toPlainText()
image = QImage(20,20,QImage.Format_RGB32); image.fill(QColor('#bf4328')); mime = QMimeData(); mime.setImageData(image)
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
assert not panel.execute_button.isVisible(), 'a moved target must be relinked before Agent can resume'
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
            assert control.focusPolicy()!=Qt.NoFocus and control.isEnabled(), (control.accessibleName(),control.objectName(),type(control).__name__,control.isEnabled())
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
    QTest.keyClick(focused or panel.options_dialog,Qt.Key_Tab); settle()
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
    arrow=control.style().subControlRect(QStyle.CC_ComboBox,option,QStyle.SC_ComboBoxArrow,control)
    QTest.mouseClick(control,Qt.LeftButton,pos=arrow.center()); settle()
    assert control.view().isVisible(), 'dropdown chevron must open the actual selector'
    control.hidePopup(); settle()
panel.options_dialog.hide()
for control in (panel.mode_selector,):
    option=QStyleOptionComboBox(); control.initStyleOption(option)
    arrow=control.style().subControlRect(QStyle.CC_ComboBox,option,QStyle.SC_ComboBoxArrow,control)
    QTest.mouseClick(control,Qt.LeftButton,pos=arrow.center()); settle()
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
panel.close()
print('Qt interaction, context receipts, streaming selection/scroll, structured plans, paste and six themed layout checks passed: '+str(output))

# Decision endpoints: live list labels, key hint and visual-check note.
panel.handle_event({'type': 'decisions', 'endpoint': 'openrouter', 'selection': {'endpoint': 'openrouter', 'model': 'openai/gpt-6-luna-decisions'}, 'visual': True,
    'endpoints': [{'id': 'openrouter', 'name': 'OpenRouter', 'custom': False, 'key_configured': True, 'key_hint': ''},
                  {'id': 'openai', 'name': 'OpenAI', 'custom': False, 'key_configured': False, 'key_hint': 'An OpenAI API key'}],
    'models': [{'id': 'openai/gpt-6-luna-decisions', 'images': True, 'price_per_million_input': 0.1}, {'id': 'typesafe/jev-1.13', 'images': False}]})
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
panel.move_undo.click()
assert commands[-1] == {'type': 'move', 'action': 'undo', 'move': 4}
panel.handle_event({'type': 'move', 'move': {'number': 5, 'status': 'empty', 'actions': 0}})
assert not panel.move_bar.isVisibleTo(panel), 'an empty move shows no card'
print('Agent move bar passed.')
