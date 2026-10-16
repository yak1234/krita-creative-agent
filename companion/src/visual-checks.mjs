// Image-based checks answered by Luna Decisions. Question texts are shared with
// scripts/evaluate-visual-checks.py so the evaluation measures what ships.
import {readFileSync} from 'node:fs';
export const QUESTIONS=JSON.parse(readFileSync(new URL('./visual-check-questions.json',import.meta.url),'utf8'));
const noul=({instructions,criteria})=>({type:'noul',instructions,criteria});
const choice=(instructions,criteria)=>({type:'choice',instructions,criteria});
const probability=value=>value?.type==='noul' && Number.isFinite(value.noul) && value.noul>=0 && value.noul<=1 ? value.noul:null;

// Which failure types to ask about. Hard join and duplicated band come from stitched reference
// chunks: on ordinary passes 0 of 6 hand-checked flags were real (they fired on unchanged content).
export const failureTypes=({reference=false}={})=>Object.keys(QUESTIONS.pass.failures).filter(id=>reference || !QUESTIONS.pass.failures[id].reference_only);
// One BEFORE/AFTER request: a yes/no per failure type, plus "is BEFORE an established painting?".
// Flat shapes are the point of a block-in, where flat block, ellipses and hard graphic were false alarms.
// Of the stage wordings tried on labelled pairs only "finished or nearly finished" separated them:
// established paintings 0.95-1, block-ins 0.2-0.87 (one flat graphic picture 0.94).
export function artifactQuestions({reference=false,prefix=''}={}) {
 const questions=Object.fromEntries(failureTypes({reference}).map(id=>[prefix+id,noul(QUESTIONS.pass.failures[id])]));
 questions[prefix+'established']=noul(QUESTIONS.pass.established);
 return questions;
}
/** {probabilities, established} from the answers, or null when an answer is malformed. */
export function artifactAnswers(answers,{reference=false,prefix=''}={}) {
 const probabilities={};
 for(const id of failureTypes({reference})) {
  const p=probability(answers?.[prefix+id]);
  if(p===null)return null;
  probabilities[id]=p;
 }
 const established=probability(answers?.[prefix+'established']);
 return established===null ? null : {probabilities,established};
}
/** Failures at or above the threshold, ignoring block-in-exempt types before the painting is established.
 *  Severe: sure enough (severe_threshold) of a severe type on an established painting to undo the pass. */
export function artifactFindings({probabilities={},established=null}={},threshold=QUESTIONS.pass.threshold) {
 const {failures,severe_threshold}=QUESTIONS.pass;
 const known=established!==null, settled=known && established>=QUESTIONS.pass.established.threshold;
 return Object.entries(probabilities).filter(([id,p])=>p>=threshold && !(known && !settled && failures[id].blockin_exempt))
  .map(([id,p])=>({type:id,label:failures[id].label,probability:p,severe:!!failures[id].severe && p>=severe_threshold && settled}));
}

// Did this pass introduce a recorded failure type? One request for all types,
// a second only to locate what was flagged, so a clean pass costs one call.
export async function passCheck({client,before,after,signal,threshold=QUESTIONS.pass.threshold,reference=false}) {
 const failures=QUESTIONS.pass.failures;
 const first=await client.decide({signal,purpose:'detect-pass-failures',questions:artifactQuestions({reference}),
  parts:['BEFORE (canvas before this paint pass):',before,'AFTER (canvas after this paint pass):',after]});
 if(first.fallback)return {fallback:first.fallback,elapsed_ms:first.elapsed_ms};
 const answered=artifactAnswers(first.answers,{reference});
 if(!answered)return {fallback:'service_or_response_error',elapsed_ms:first.elapsed_ms};
 const {probabilities,established}=answered;
 const flagged=artifactFindings(answered,threshold).map(f=>f.type);
 const usage={cost:first.usage.cost,input_tokens:first.usage.input_tokens};
 if(!flagged.length)return {findings:[],probabilities,established,usage,elapsed_ms:first.elapsed_ms};
 const {instructions,cells}=QUESTIONS.pass.location;
 const second=await client.decide({signal,purpose:'locate-pass-failures',parts:['AFTER (canvas after this paint pass):',after],
  questions:Object.fromEntries(flagged.map(id=>[id,choice(instructions.replace('{label}',failures[id].label),cells)]))});
 usage.cost+=second.usage?.cost ?? 0; usage.input_tokens+=second.usage?.input_tokens ?? 0;
 const location=id=>{const a=second.answers?.[id];return a?.type==='choice' && Object.hasOwn(cells,a.choice) ? a.choice:null;};
 return {findings:flagged.map(id=>({type:id,label:failures[id].label,probability:probabilities[id],location:second.fallback?null:location(id)})),
  probabilities,established,usage,location_fallback:second.fallback ?? null,elapsed_ms:first.elapsed_ms+second.elapsed_ms};
}

// How much did each repeatedly failed review check improve? Scores 0..3 on the
// shared scale; a score separates partial fixes that a yes/no answer misses.
export async function progressCheck({client,previous,current,checks,signal}) {
 const {max_checks,instructions,scale}=QUESTIONS.progress;
 const selected=checks.slice(0,max_checks);
 if(!selected.length)return {fallback:'no_checks',elapsed_ms:0};
 const result=await client.decide({signal,purpose:'score-review-progress',parts:['PREVIOUS (canvas at the previous review):',previous,'CURRENT (canvas now):',current],
  questions:Object.fromEntries(selected.map((check,i)=>[`check_${i}`,{type:'score',instructions:instructions.replace('{check}',String(check.text).slice(0,600)),criteria:scale}]))});
 if(result.fallback)return {fallback:result.fallback,elapsed_ms:result.elapsed_ms};
 const scores={};
 for(const [i,check] of selected.entries()) {
  const value=result.answers[`check_${i}`];
  if(value?.type!=='score' || !Number.isFinite(value.score) || value.score<0 || value.score>scale.length-1)return {fallback:'service_or_response_error',elapsed_ms:result.elapsed_ms};
  scores[check.id]=value.score;
 }
 const values=Object.values(scores);
 return {scores,mean:values.reduce((sum,v)=>sum+v,0)/values.length,usage:result.usage,elapsed_ms:result.elapsed_ms};
}
