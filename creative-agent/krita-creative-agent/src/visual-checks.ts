// Image-based checks answered by Luna Decisions. Question texts are shared with
// scripts/evaluate-visual-checks.py so the evaluation measures what ships.
import {readFileSync} from 'node:fs';
import type {Answer, Answers, ChoiceQuestion, DecisionMaker, DecisionPart, DecisionUsage, FallbackReason, NoulQuestion, Questions, ScoreQuestion} from './decisions/types.ts';

/** One failure type a paint pass can introduce (visual-check-questions.json `pass.failures`). */
export type FailureType = {label:string; instructions:string; criteria:NoulQuestion['criteria']; reference_only?:boolean; blockin_exempt?:boolean; severe?:boolean};
/** The shape of visual-check-questions.json. */
export type VisualCheckQuestions = {
 seam:{threshold:number; instructions:string; criteria:NoulQuestion['criteria']; calibration?:string};
 version:number;
 pass:{threshold:number; severe_threshold:number; failures:Record<string,FailureType>;
  location:{instructions:string; cells:Record<string,string>};
  established:{instructions:string; criteria:NoulQuestion['criteria']; threshold:number}};
 progress:{max_checks:number; instructions:string; scale:string[]};
 layer_need:{instructions:string; needs:Record<string,string>};
 move:{texture_over_forms:FailureType; feature:FailureType; any_feature:FailureType};
};
export const QUESTIONS=JSON.parse(readFileSync(new URL('./visual-check-questions.json',import.meta.url),'utf8')) as VisualCheckQuestions;
const noul=({instructions,criteria}:{instructions:string; criteria:NoulQuestion['criteria']}):NoulQuestion=>({type:'noul',instructions,criteria});
const choice=(instructions:string,criteria:Record<string,string>):ChoiceQuestion=>({type:'choice',instructions,criteria});
const probability=(value:Answer|undefined):number|null=>value?.type==='noul' && Number.isFinite(value.noul) && value.noul>=0 && value.noul<=1 ? value.noul:null;

/** Failure probabilities by type, and how established BEFORE looked (null: not asked or malformed). */
export type ArtifactAnswers = {probabilities:Record<string,number>; established:number|null};
export type Finding = {type:string; label:string; probability:number; severe:boolean};
export type LocatedFinding = {type:string; label:string; probability:number; location:string|null};
export type CheckFallback = {fallback:FallbackReason|'no_checks'; elapsed_ms:number};
export type PassCheckResult = CheckFallback | {findings:LocatedFinding[]; probabilities:Record<string,number>; established:number;
 usage:Pick<DecisionUsage,'cost'|'input_tokens'>; location_fallback?:FallbackReason|null; elapsed_ms:number; fallback?:undefined};
export type ProgressCheckResult = CheckFallback | {scores:Record<string,number>; mean:number; usage:DecisionUsage; elapsed_ms:number; fallback?:undefined};

// Which failure types to ask about. Hard join and duplicated band come from stitched reference
// chunks: on ordinary passes 0 of 6 hand-checked flags were real (they fired on unchanged content).
export const failureTypes=({reference=false}={}):string[]=>Object.keys(QUESTIONS.pass.failures).filter(id=>reference || !QUESTIONS.pass.failures[id].reference_only);
// One BEFORE/AFTER request: a yes/no per failure type, plus "is BEFORE an established painting?".
// Flat shapes are the point of a block-in, where flat block, ellipses and hard graphic were false alarms.
// Of the stage wordings tried on labelled pairs only "finished or nearly finished" separated them:
// established paintings 0.95-1, block-ins 0.2-0.87 (one flat graphic picture 0.94).
export function artifactQuestions({reference=false,prefix=''}={}):Questions {
 const questions:Questions=Object.fromEntries(failureTypes({reference}).map(id=>[prefix+id,noul(QUESTIONS.pass.failures[id])]));
 questions[prefix+'established']=noul(QUESTIONS.pass.established);
 return questions;
}
/** {probabilities, established} from the answers, or null when an answer is malformed. */
export function artifactAnswers(answers:Answers|null|undefined,{reference=false,prefix=''}={}):{probabilities:Record<string,number>; established:number}|null {
 const probabilities:Record<string,number>={};
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
export function artifactFindings({probabilities={},established=null}:Partial<ArtifactAnswers>={},threshold=QUESTIONS.pass.threshold):Finding[] {
 const {failures,severe_threshold}=QUESTIONS.pass;
 const known=established!==null, settled=known && established>=QUESTIONS.pass.established.threshold;
 return Object.entries(probabilities).filter(([id,p])=>p>=threshold && !(known && !settled && failures[id].blockin_exempt))
  .map(([id,p])=>({type:id,label:failures[id].label,probability:p,severe:!!failures[id].severe && p>=severe_threshold && settled}));
}

// Did this pass introduce a recorded failure type? One request for all types,
// a second only to locate what was flagged, so a clean pass costs one call.
export async function passCheck({client,before,after,signal,threshold=QUESTIONS.pass.threshold,reference=false}:
 {client:DecisionMaker; before:DecisionPart; after:DecisionPart; signal?:AbortSignal; threshold?:number; reference?:boolean}):Promise<PassCheckResult> {
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
 const second=await locate({client,after,signal,purpose:'locate-pass-failures',labels:Object.fromEntries(flagged.map(id=>[id,failures[id].label])),usage});
 return {findings:flagged.map(id=>({type:id,label:failures[id].label,probability:probabilities[id],location:second.locations[id] ?? null})),
  probabilities,established,usage,location_fallback:second.fallback,elapsed_ms:first.elapsed_ms+second.elapsed_ms};
}
// The ninth of AFTER where each flagged label is most visible (null when not answered), adding the request's cost to usage.
async function locate({client,after,signal,purpose,labels,usage}:{client:DecisionMaker; after:DecisionPart; signal?:AbortSignal; purpose:string;
 labels:Record<string,string>; usage:Pick<DecisionUsage,'cost'|'input_tokens'>}):Promise<{locations:Record<string,string|null>; fallback:FallbackReason|null; elapsed_ms:number}> {
 const {instructions,cells}=QUESTIONS.pass.location;
 const result=await client.decide({signal,purpose,parts:['AFTER (canvas after this paint pass):',after],
  questions:Object.fromEntries(Object.entries(labels).map(([id,label])=>[id,choice(instructions.replace('{label}',label),cells)]))});
 usage.cost+=result.usage?.cost ?? 0; usage.input_tokens+=result.usage?.input_tokens ?? 0;
 const location=(id:string)=>{const a=result.answers?.[id];return !result.fallback && a?.type==='choice' && Object.hasOwn(cells,a.choice) ? a.choice:null;};
 return {locations:Object.fromEntries(Object.keys(labels).map(id=>[id,location(id)])),fallback:result.fallback ?? null,elapsed_ms:result.elapsed_ms};
}

/** A finding of a move check: an artifact, texture over forms, or a covered focal feature (by name when the area is named). */
export type MoveFinding = LocatedFinding & {feature?:string};
export type MoveCheckResult = CheckFallback | {findings:MoveFinding[]; usage:Pick<DecisionUsage,'cost'|'input_tokens'>; elapsed_ms:number; fallback?:undefined};
/** Named features asked about per batch; more would lengthen every request. */
export const MAX_FEATURES=4;
// Did one painting batch of an Agent move make the painting worse? The pass artifacts, plus a broad texture over
// forms BEFORE showed, plus each named focal feature (protected areas, kept or proposed) still as visible as BEFORE.
// A feature BEFORE did not show is never "lost": the question compares with BEFORE.
export async function moveCheck({client,before,after,features,signal}:
 {client:DecisionMaker; before:DecisionPart; after:DecisionPart; features:string[]; signal?:AbortSignal}):Promise<MoveCheckResult> {
 const move=QUESTIONS.move;
 const names=[...new Set(features.map(f=>String(f).trim().slice(0,60)).filter(Boolean))].slice(0,MAX_FEATURES);
 const fill=(t:string,feature:string)=>t.replaceAll('{feature}',feature);
 const featureQuestion=(feature:string):NoulQuestion=>noul({instructions:fill(move.feature.instructions,feature),
  criteria:Object.fromEntries(Object.entries(move.feature.criteria ?? {}).map(([k,v])=>[k,fill(v,feature)])) as NoulQuestion['criteria']});
 const questions:Questions={...artifactQuestions(),texture_over_forms:noul(move.texture_over_forms),
  ...(names.length ? Object.fromEntries(names.map((name,i)=>['feature_'+i,featureQuestion(name)])) : {any_feature:noul(move.any_feature)})};
 const first=await client.decide({signal,purpose:'detect-move-failures',questions,
  parts:['BEFORE (canvas before this painting batch):',before,'AFTER (canvas after this painting batch):',after]});
 if(first.fallback)return {fallback:first.fallback,elapsed_ms:first.elapsed_ms};
 const answered=artifactAnswers(first.answers);
 const texture=probability(first.answers?.texture_over_forms);
 const featureIds=names.length ? names.map((_,i)=>'feature_'+i) : ['any_feature'];
 const featureP=featureIds.map(id=>probability(first.answers?.[id]));
 if(!answered || texture===null || featureP.some(p=>p===null))return {fallback:'service_or_response_error',elapsed_ms:first.elapsed_ms};
 const threshold=QUESTIONS.pass.threshold, settled=answered.established>=QUESTIONS.pass.established.threshold;
 const flagged:{id:string; finding:Omit<MoveFinding,'location'>}[]=artifactFindings(answered,threshold).map(({type,label,probability})=>({id:type,finding:{type,label,probability}}));
 if(texture>=threshold && settled)flagged.push({id:'texture_over_forms',finding:{type:'texture_over_forms',label:move.texture_over_forms.label,probability:texture}});
 featureIds.forEach((id,i)=>{const p=featureP[i] as number; if(p>=threshold)flagged.push({id,finding:{type:'covered_feature',
  ...(names.length ? {feature:names[i],label:fill(move.feature.label,names[i])} : {label:move.any_feature.label}),probability:p}});});
 const usage={cost:first.usage.cost,input_tokens:first.usage.input_tokens};
 if(!flagged.length)return {findings:[],usage,elapsed_ms:first.elapsed_ms};
 const second=await locate({client,after,signal,purpose:'locate-move-failures',labels:Object.fromEntries(flagged.map(f=>[f.id,f.finding.label])),usage});
 return {findings:flagged.map(f=>({...f.finding,location:second.locations[f.id] ?? null})),usage,elapsed_ms:first.elapsed_ms+second.elapsed_ms};
}

// How much did each repeatedly failed review check improve? Scores 0..3 on the
// shared scale; a score separates partial fixes that a yes/no answer misses.
export async function progressCheck({client,previous,current,checks,signal}:
 {client:DecisionMaker; previous:DecisionPart; current:DecisionPart; checks:{id:string; text:unknown}[]; signal?:AbortSignal}):Promise<ProgressCheckResult> {
 const {max_checks,instructions,scale}=QUESTIONS.progress;
 const selected=checks.slice(0,max_checks);
 if(!selected.length)return {fallback:'no_checks',elapsed_ms:0};
 const result=await client.decide({signal,purpose:'score-review-progress',parts:['PREVIOUS (canvas at the previous review):',previous,'CURRENT (canvas now):',current],
  questions:Object.fromEntries(selected.map((check,i)=>[`check_${i}`,{type:'score',instructions:instructions.replace('{check}',String(check.text).slice(0,600)),criteria:scale} satisfies ScoreQuestion]))});
 if(result.fallback)return {fallback:result.fallback,elapsed_ms:result.elapsed_ms};
 const scores:Record<string,number>={};
 for(const [i,check] of selected.entries()) {
  const value=result.answers[`check_${i}`];
  if(value?.type!=='score' || !Number.isFinite(value.score) || value.score<0 || value.score>scale.length-1)return {fallback:'service_or_response_error',elapsed_ms:result.elapsed_ms};
  scores[check.id]=value.score;
 }
 const values=Object.values(scores);
 return {scores,mean:values.reduce((sum,v)=>sum+v,0)/values.length,usage:result.usage,elapsed_ms:result.elapsed_ms};
}

// Is each candidate a seam baked into the painting (seams.py found a faint straight join)? One close-up per request,
// its line across the middle, all at once: about 550 tokens each. A failed request is null, never a guess.
export async function seamCheck({client,crops,signal}:{client:DecisionMaker; crops:{image:DecisionPart; axis:'h'|'v'}[]; signal?:AbortSignal}):Promise<(number|null)[]> {
 const {instructions,criteria}=QUESTIONS.seam;
 return Promise.all(crops.map(async ({image,axis})=>{
  const where=axis==='h' ? 'the horizontal line across the middle of the image' : 'the vertical line down the middle of the image';
  const result=await client.decide({signal,purpose:'confirm-seam',parts:['CLOSE-UP of part of a painting:',image],
   questions:{seam:noul({instructions:instructions.replace('{where}',where),criteria})}});
  return result.fallback ? null : probability(result.answers?.seam);
 }));
}
