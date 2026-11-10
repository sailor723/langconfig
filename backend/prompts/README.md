# Prompts — Chinese is what an agent is sent, English is the archive

A prompt in this app is `deep_agent_templates.config->>'system_prompt'`: the text an agent is handed and the text
the Prompts activity shows. Chinese is the working language, so the two halves live in different places on purpose:

```
the database        deep_agent_templates.config->>'system_prompt'   ← served to agents; Chinese
en-originals/<id>.md                                                 ← the English it came from; never served
pending-zh.txt                                                       ← still English; the honest backlog
zh-native.txt                                                        ← written in Chinese from the start
```

The archive is **outside** the database for the same reason the skill archive is outside the skill roots: a
translation you cannot diff against its source is a claim, not a record. `promote` writes both in one breath —
freeze the English, then write the Chinese — because an archive that exists beside a still-English prompt says a
translation happened when it has not, and that is the one thing this directory must never say.

## Working on one

```bash
python scripts/prompt_zh.py status            # how many are where
python scripts/prompt_zh.py show 214          # the English to translate (--from db)
                              show 214 --from staged   # a draft in .zh-staging/
python scripts/prompt_zh.py check 214         # validate the staged Chinese; changes nothing
python scripts/prompt_zh.py promote 214       # archive the English, write the Chinese to the DB
```

`check` and `promote` refuse a translation that lost a fenced block or changed a code block, dropped an
identifier, number, URL or path that the English prose contains, or left the prose too English. Those are the parts
a reader would type; the argument above them is what a human reviewer reads for.

Guards: `backend/tests/test_prompt_translations.py` — every prompt in exactly one state, every archived prompt
actually Chinese in the DB, code and identifiers preserved, the backlog honest in both directions, and nothing
left staged.
