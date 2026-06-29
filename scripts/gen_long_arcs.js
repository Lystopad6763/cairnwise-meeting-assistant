export const meta = {
  name: 'cairnwise-long-arcs',
  description: 'Повноцінні ДОВГІ зустрічі (~30 хв): 3 проєкти × 10 зустрічей × сегменти (bible -> agenda -> segments)',
  phases: [
    { title: 'Bible', detail: 'склад + таймлайн з агендою (12-16 беатів) і тяглістю, по агенту на проєкт' },
    { title: 'Dialogue', detail: 'кожна зустріч = 4 сегменти по агенді, ~24-30 реплік кожен (~30 хв сумарно)' },
  ],
}

const SEGMENTS = 4

const ROLE_VOICE = { pm: 'Dmytro', dev_be: 'Tetiana', dev_fe: 'Mykyta', qa: 'Lada', customer: 'Oleksa' }
const ROLE_LABEL = {
  pm: 'проджект-менеджер', dev_be: 'бекенд-розробник',
  dev_fe: 'фронтенд/мобільний розробник', qa: 'QA-інженер', customer: 'замовник',
}

const LIFECYCLE = [
  { id: 'm01_discovery_call', type: 'customer_discovery', attendees: ['pm', 'dev_be', 'customer'] },
  { id: 'm02_customer_kickoff', type: 'customer_kickoff', attendees: ['pm', 'dev_be', 'customer'] },
  { id: 'm03_sprint1_planning', type: 'sprint_planning', attendees: ['pm', 'dev_be', 'dev_fe', 'qa'] },
  { id: 'm04_design_review', type: 'design_review', attendees: ['pm', 'dev_be', 'dev_fe'] },
  { id: 'm05_daily_standup', type: 'daily_standup', attendees: ['pm', 'dev_be', 'dev_fe', 'qa'] },
  { id: 'm06_bug_triage', type: 'bug_triage', attendees: ['pm', 'dev_be', 'dev_fe'] },
  { id: 'm07_sprint1_demo', type: 'sprint_demo', attendees: ['pm', 'dev_be', 'dev_fe', 'customer'] },
  { id: 'm08_sprint1_retro', type: 'sprint_retro', attendees: ['pm', 'dev_be', 'dev_fe', 'qa'] },
  { id: 'm09_customer_sync', type: 'customer_sync', attendees: ['pm', 'customer', 'dev_be'] },
  { id: 'm10_project_closing', type: 'project_closing', attendees: ['pm', 'customer', 'dev_be'] },
]

const PROJECTS = [
  { key: 'acme', premise: 'Acme Pay — FinTech платіжний шлюз для маркетплейсу: прийом карток, Apple/Google Pay, автоматичні виплати продавцям, інтеграція Stripe під капотом, мультивалюта, спрощений PCI-скоуп через токенізацію.' },
  { key: 'nimbus', premise: 'Nimbus Analytics — BI-дашборд: графіки й агрегації, фільтри за датами та регіоном, Redis-кеш для важких запитів, експорт у PDF, джерела даних CRM і біллінг.' },
  { key: 'orbit', premise: 'Orbit Logistics — мобільний застосунок трекінгу доставок у реальному часі: мапа, розрахунок ETA, пуш-сповіщення, інтеграція з GPS і API перевізників.' },
]

const BIBLE_SCHEMA = {
  type: 'object',
  properties: {
    cast: {
      type: 'array',
      items: { type: 'object', properties: { role: { type: 'string' }, name: { type: 'string' } }, required: ['role', 'name'] },
    },
    timeline: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          meeting_id: { type: 'string' },
          summary: { type: 'string' },
          agenda: { type: 'array', items: { type: 'string' } },
          decisions: { type: 'array', items: { type: 'string' } },
          action_items: { type: 'array', items: { type: 'string' } },
        },
        required: ['meeting_id', 'summary', 'agenda', 'decisions', 'action_items'],
      },
    },
  },
  required: ['cast', 'timeline'],
}

const SEG_SCHEMA = {
  type: 'object',
  properties: {
    turns: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          voice: { type: 'string', enum: ['Tetiana', 'Mykyta', 'Lada', 'Dmytro', 'Oleksa'] },
          text: { type: 'string' },
        },
        required: ['voice', 'text'],
      },
    },
  },
  required: ['turns'],
}

function chunk(arr, n) {
  if (!arr || !arr.length) return []
  const size = Math.ceil(arr.length / n) || 1
  const out = []
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size))
  return out
}

function biblePrompt(p) {
  const roles = Object.keys(ROLE_VOICE).map((r) => `- ${r} (${ROLE_LABEL[r]})`).join('\n')
  const cyc = LIFECYCLE.map((m, i) => `${i + 1}. ${m.id} [${m.type}] — присутні: ${m.attendees.join(', ')}`).join('\n')
  return `Ти — сценарист продуктового проєкту. Склади «БІБЛІЮ ПРОЄКТУ» для зв'язної серії ДОВГИХ зустрічей (кожна ~30 хв).

ПРОЄКТ "${p.key}": ${p.premise}

1) cast: признач РЕАЛІСТИЧНІ українські імена (різні, не технічні слова) цим 5 ролям:
${roles}

2) timeline: рівно 10 записів у ТОМУ Ж порядку й з тими ж meeting_id, що нижче. Це ЖИВИЙ АРК
   проєкту в часі — від першого дзвінка із замовником до закриття. Рішення й action-items
   НАКОПИЧУЮТЬСЯ і ПОСИЛАЮТЬСЯ на попередні (closing звітує про обіцяне на kickoff; retro згадує
   інцидент із bug_triage; demo показує заплановане на sprint planning).
   Для КОЖНОЇ зустрічі дай:
     - summary (3-4 речення),
     - agenda: 12-16 КОНКРЕТНИХ беатів-тем для обговорення (бо зустріч довга, ~30 хв — потрібно
       багато матеріалу: деталі вимог, оцінки, технічні рішення, ризики, цифри, заперечення, домовленості),
     - decisions (2-4), action_items (2-4, з власником).
${cyc}

Зроби арк правдоподібним для домену: конкретні фічі, дедлайни, метрики, технічні компроміси.
Поверни строго за схемою.`
}

function segPrompt(p, bible, m, entry, si, total, myBeats, allBeats) {
  const castByRole = {}
  ;(bible.cast || []).forEach((c) => { castByRole[c.role] = c.name })
  const attendees = m.attendees
    .map((r) => `${castByRole[r] || r} — ${ROLE_LABEL[r]}, голос=${ROLE_VOICE[r]}`)
    .join('; ')
  const tl = (bible.timeline || []).map((t, i) => `${i + 1}. ${t.meeting_id}: ${t.summary}`).join('\n')
  const beatLines = allBeats
    .map((g, gi) => g.map((b) => `  ${gi < si ? '[вже обговорено]' : gi === si ? '[➤ ЦЕЙ СЕГМЕНТ]' : '[пізніше]'} ${b}`).join('\n'))
    .join('\n')
  const isLast = si === total - 1
  const wrap = isLast
    ? `Це ОСТАННІЙ сегмент: природно підсумуй і ЯВНО проговори рішення та action-items зустрічі: рішення — ${(entry.decisions || []).join('; ') || '—'}; action-items — ${(entry.action_items || []).join('; ') || '—'}.`
    : `Це НЕ останній сегмент: не підсумовуй і не прощайся — закінчи так, ніби розмова триває далі.`
  const open = si === 0
    ? 'Це ПЕРШИЙ сегмент: природний початок зустрічі для свого типу.'
    : 'Це ПРОДОВЖЕННЯ зустрічі (попередні теми вже обговорені) — починай ПОСЕРЕД розмови, без привітань і без повторного представлення.'

  return `Ти пишеш ЧАСТИНУ (${si + 1} з ${total}) довгого україномовного ТРАНСКРИПТУ зустрічі "${m.id}" [тип: ${m.type}] проєкту "${p.key}".

ПРОЄКТ: ${p.premise}
Повний таймлайн проєкту (для тяглості — посилайся на факти РАНІШИХ зустрічей, де природно):
${tl}

Про цю зустріч: ${entry.summary || ''}
Присутні (кожен — фіксований голос; ІНШИХ не додавай): ${attendees}

Агенда всієї зустрічі (твій сегмент покриває позначені [➤ ЦЕЙ СЕГМЕНТ]):
${beatLines}

${open}
${wrap}

ПРАВИЛА:
- Розкрий СВОЇ беати ГЛИБОКО: 24-30 ЗМІСТОВНИХ реплік (по 2-5 речень), з деталями, цифрами, уточненнями, легкою незгодою — це частина 30-хвилинної зустрічі, не поспішай.
- Природна, ідіоматична УКРАЇНСЬКА (технічні терміни ок: Stripe, Redis, API, ETA, PDF, GPS, PCI).
- "voice" КОЖНОЇ репліки = голос саме того, хто говорить, зі списку присутніх. Різні люди — різні голоси. Speaker-мітки НЕ став.
- Тон відповідає типу зустрічі (${m.type}). Для customer-зустрічей замовник активно говорить. Без вигаданого реального PII.

Поверни строго за схемою (turns[] з {voice, text}).`
}

phase('Bible')
const results = await pipeline(
  PROJECTS,
  (p) => agent(biblePrompt(p), { label: 'bible:' + p.key, phase: 'Bible', schema: BIBLE_SCHEMA }),
  (bible, p) => {
    const tasks = []
    LIFECYCLE.forEach((m) => {
      const entry = (bible.timeline || []).find((t) => t.meeting_id === m.id) || { agenda: [] }
      const groups = chunk(entry.agenda || [], SEGMENTS)
      const total = groups.length || 1
      const realGroups = groups.length ? groups : [[]]
      realGroups.forEach((g, si) => {
        tasks.push(() =>
          agent(segPrompt(p, bible, m, entry, si, total, g, realGroups), {
            label: `seg:${p.key}/${m.id}#${si + 1}`, phase: 'Dialogue', schema: SEG_SCHEMA, model: 'sonnet',
          }).then((r) =>
            r && r.turns ? { project: p.key, meeting_id: m.id, meeting_type: m.type, seg: si, turns: r.turns } : null
          )
        )
      })
    })
    return parallel(tasks)
  }
)

const segments = results.filter(Boolean).flat().filter(Boolean)
const turnsTotal = segments.reduce((a, s) => a + s.turns.length, 0)
log(`Сегментів: ${segments.length}; реплік сумарно: ${turnsTotal} (≈ ${segments.length / SEGMENTS} зустрічей)`)
return { segments }
