// Decision API wire protocols. Callers always use the System One question form
// (`noul` / `choice` with `criteria` / `score` with a level list) and receive
// answers keyed by question name in that form; each protocol translates both ways.
//
//   systemone: OpenRouter /api/alpha/decisions, TypeSafe /v1/systemone, Unsloth Studio /v1/systemone
//   openai:    OpenAI /v1/decisions (predicate / choice with `choices` / score with `levels`)

// parts: ordered strings (text) and images ({data, mimeType} or data URLs).
export function imagePart(image) {
  const url = typeof image === 'string' ? image : 'data:' + (image.mimeType ?? 'image/png') + ';base64,' + image.data;
  if (!/^data:image\/[a-z.+-]+;base64,/i.test(url)) throw new Error('Decision images must be inline data URLs.');
  return url;
}
const isImage = part => typeof part === 'object' || (typeof part === 'string' && part.startsWith('data:'));
const present = parts => (parts ?? []).filter(part => part !== undefined && part !== null);
export const hasImages = parts => present(parts).some(isImage);

const systemone = {
  // Chat-style image_url parts are the form these endpoints read (input_image parts were silently ignored).
  body: ({ model, parts, questions }) => ({ model, questions,
    state: present(parts).map(part => isImage(part) ? { type: 'image_url', image_url: { url: imagePart(part) } } : { type: 'text', text: part }) }),
  answers: body => body && typeof body.answers === 'object' && !Array.isArray(body.answers) ? body.answers : null,
};

const openai = {
  body: ({ model, parts, questions }) => ({
    model,
    input: [{ role: 'user', content: present(parts).map(part => isImage(part) ? { type: 'input_image', image_url: imagePart(part) } : { type: 'input_text', text: part }) }],
    questions: Object.entries(questions).map(([name, q]) => {
      if (q.type === 'noul') {
        // A predicate has no criteria field: carry the true/false descriptions in its instructions.
        const hint = q.criteria ? ` (True: ${q.criteria.true ?? 'yes'} False: ${q.criteria.false ?? 'no'})` : '';
        return { name, type: 'predicate', instructions: q.instructions + hint };
      }
      if (q.type === 'choice') return { name, type: 'choice', instructions: q.instructions,
        choices: Object.entries(q.criteria).map(([value, description]) => ({ value, description })) };
      if (q.type === 'score') return { name, type: 'score', instructions: q.instructions,
        levels: (Array.isArray(q.criteria) ? q.criteria : Object.values(q.criteria)).map(label => ({ label })) };
      throw new Error('Unsupported question type: ' + q.type);
    }),
  }),
  answers: body => {
    if (!Array.isArray(body?.answers)) return null;
    const keyed = {};
    const probabilities = list => Array.isArray(list)
      ? Object.fromEntries(list.map((entry, index) => [String(entry.value ?? entry.label ?? entry.level ?? index), entry.probability ?? entry.p ?? 0]))
      : list;
    for (const answer of body.answers) {
      if (!answer?.name) continue;
      if (answer.type === 'refusal') keyed[answer.name] = { type: 'refusal' };
      else if (answer.type === 'predicate') keyed[answer.name] = { type: 'noul', noul: answer.probability };
      else if (answer.type === 'choice') keyed[answer.name] = { type: 'choice', choice: String(answer.choice), confidence: answer.confidence, probabilities: probabilities(answer.probabilities) };
      else if (answer.type === 'score') keyed[answer.name] = { type: 'score', score: answer.score, confidence: answer.confidence, probabilities: probabilities(answer.probabilities) };
    }
    return keyed;
  },
};

export const PROTOCOLS = { systemone, openai };
