import test from 'node:test';
import assert from 'node:assert/strict';
import { expandSkillCommand, listSkills } from '../src/skills.mjs';
import { SKILL_COMMANDS, skillCommand, slashMenu } from '../src/skill-commands.ts';

test('the short commands expand to their skill plus the artist\'s text', () => {
  for (const [typed, skill] of [['/trace', 'guided-trace'], ['/colour', 'reference-transfer'], ['/color', 'reference-transfer'],
    ['/from-reference', 'reference-transfer'], ['/refine', 'repaint-area']]) {
    const text = expandSkillCommand(typed + ' the moon and the towers');
    assert.ok(text.startsWith(`<skill name="${skill}"`), typed);
    assert.equal(text.split('<skill name=').length - 1, 1, typed + ' expands once');
    assert.ok(text.endsWith('\n\nthe moon and the towers'), typed + ' keeps the request');
    assert.equal(expandSkillCommand(typed), expandSkillCommand('/skill:' + skill), typed + ' alone is the skill alone');
  }
  assert.equal(expandSkillCommand('/x trace it'), '/x trace it', 'an unknown /x is left as typed');
  assert.equal(expandSkillCommand('/tracer it'), '/tracer it');
  assert.equal(expandSkillCommand('trace the outline'), 'trace the outline');
});

test('one table: every command names a bundled skill and has a one-line description', () => {
  const skills = listSkills().map(s => s.name);
  for (const c of SKILL_COMMANDS) {
    assert.ok(skills.includes(c.skill), c.name);
    assert.ok(c.description.length > 20 && c.description.length <= 120 && !c.description.includes('\n'), c.name);
  }
  assert.equal(skillCommand('/trace the moon')?.move_kind, 'guides', '/trace starts a guide-only move');
  assert.equal(skillCommand('/colour')?.move_kind, undefined);
  assert.equal(skillCommand('/nope'), null);
});

test('the slash menu lists the short commands, then /skill:<name> for every bundled skill', () => {
  const skills = listSkills();
  const menu = slashMenu(skills);
  assert.deepEqual(menu.slice(0, 3).map(m => m.command), ['/trace', '/colour', '/refine']);
  assert.deepEqual(menu.find(m => m.command === '/colour').aliases, ['/color', '/from-reference']);
  assert.deepEqual(menu.slice(3).map(m => m.command), skills.map(s => '/skill:' + s.name));
  for (const m of menu) assert.ok(m.description && !m.description.includes('\n'), m.command);
});

test('the panel gets the menu in the skills event, so it never names a skill itself', async () => {
  const { skillsEvent } = await import('../src/skills.mjs');
  const event = skillsEvent();
  assert.equal(event.type, 'skills');
  assert.deepEqual(event.skills, listSkills().map(({ name, description }) => ({ name, description })), 'older panels keep their list');
  assert.deepEqual(event.commands, slashMenu(listSkills()));
  const withoutGuides = skillsEvent(undefined, { guides: false }).commands.map(c => c.command);
  assert.ok(!withoutGuides.includes('/trace') && withoutGuides.includes('/colour') && withoutGuides.includes('/skill:guided-trace'),
    'without guides /trace is left out; its skill can still be read');
});

test('short commands match whatever the case, with trailing punctuation on the command word', () => {
  assert.equal(skillCommand('/Trace the moon')?.skill, 'guided-trace');
  assert.equal(skillCommand('/COLOUR')?.skill, 'reference-transfer');
  assert.equal(skillCommand('/Color.')?.skill, 'reference-transfer');
  assert.equal(skillCommand('/refine: the towers')?.rest, 'the towers');
  assert.ok(expandSkillCommand('/Trace! the moon').startsWith('<skill name="guided-trace"'));
  assert.ok(expandSkillCommand('/Trace! the moon').endsWith('\n\nthe moon'));
  assert.equal(skillCommand('/tr.ace'), null);
});
